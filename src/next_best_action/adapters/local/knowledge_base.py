"""Local knowledge-base adapter (KnowledgeBasePort) — SQLite FTS5 offer/policy corpus.

The ``local`` profile's stand-in for **File Search / Agent Search** over the offer / policy
corpus (whose GCP adapter is Agent Search, and whose platform adapter is the shared A2
Enterprise KB): a ``sqlite3`` database with an **FTS5** virtual table over the seeded
fictional passages, queried with BM25 (``ORDER BY rank``). It is SDK-free, deterministic
and seedable, so the same code grounds the offline CLI run and the unit tests. There is no
Google emulator for Agent Search, so this path is unconditional.

Passages carry ``market:``/``vertical:`` tags; a query scoped to a market/vertical only
returns passages tagged for it (or untagged), so retrieval stays generic and APAC. Default
DB path is under a per-package local dir; tests pass ``:memory:`` for an ephemeral index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import (
    Citation,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)
from ._seed import CORPUS_PASSAGES

_DEFAULT_DB_DIR = Path.home() / ".next_best_action"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

# FTS5 query syntax is strict; keep only word characters so a free-text query never trips
# an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_TAG_SEP = "␟"  # unit-separator: joins tags into one UNINDEXED column safely.


class LocalKnowledgeBaseAdapter:
    """Index + retrieve offer/policy passages from a local SQLite FTS5 store (BM25)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        db_path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._db_path = db_path
        # check_same_thread=False + an RLock: deps.get_container is process-wide while the
        # sync API endpoints run in Starlette's worker threadpool, so search() is called
        # from worker threads other than the one that opened the connection. The RLock
        # serialises access and is re-entrant so seed -> _insert does not deadlock.
        self._lock = threading.RLock()
        self._conn = self._connect(db_path)
        self._init_schema()
        if self._is_empty():
            self.seed(CORPUS_PASSAGES)

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    text,
                    source_id UNINDEXED,
                    source_type UNINDEXED,
                    title UNINDEXED,
                    url UNINDEXED,
                    page UNINDEXED,
                    published_date UNINDEXED,
                    score UNINDEXED,
                    tags UNINDEXED
                )
                """
            )
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM passages").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #
    def seed(self, passages: tuple[RetrievedPassage, ...] | list[RetrievedPassage]) -> int:
        """Replace the index contents with ``passages`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM passages")
            return self._insert(list(passages))

    def _insert(self, passages: list[RetrievedPassage]) -> int:
        rows = []
        for p in passages:
            c = p.citation
            rows.append(
                (
                    p.text,
                    c.source_id,
                    c.source_type.value,
                    c.title,
                    c.url,
                    "" if c.page is None else str(c.page),
                    c.published_date or "",
                    f"{p.score:.6f}",
                    _TAG_SEP.join(p.tags),
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO passages "
                "(text, source_id, source_type, title, url, page, published_date, score, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # KnowledgeBasePort
    # ------------------------------------------------------------------ #
    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Return ranked, market/vertical-scoped passages with page-level citations."""
        match = self._build_match(query.text)
        if not match:
            sql = "SELECT * FROM passages ORDER BY score DESC LIMIT ?"
            params: list[object] = [max(query.top_k, 1) * 4]
        else:
            sql = "SELECT * FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?"
            params = [match, max(query.top_k, 1) * 4]
        wanted_tags = self._scope_tags(query)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        out: list[RetrievedPassage] = []
        for row in rows:
            passage = self._row_to_passage(row)
            if self._scope_ok(passage.tags, wanted_tags):
                out.append(passage)
            if len(out) >= max(query.top_k, 1):
                break
        return out

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _scope_tags(query: RetrievalQuery) -> set[str]:
        wanted: set[str] = set()
        if query.market is not None:
            wanted.add(f"market:{query.market.value}")
        if query.vertical is not None:
            wanted.add(f"vertical:{query.vertical.value}")
        return wanted

    @staticmethod
    def _scope_ok(passage_tags: tuple[str, ...], wanted: set[str]) -> bool:
        """A passage is in scope when it is untagged or carries every requested scope tag."""
        if not wanted:
            return True
        if not passage_tags:
            return True
        return wanted.issubset(set(passage_tags))

    @staticmethod
    def _build_match(text: str) -> str:
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_passage(row: sqlite3.Row) -> RetrievedPassage:
        page_raw = row["page"]
        page = int(page_raw) if page_raw not in (None, "") else None
        try:
            score = float(row["score"])
        except (TypeError, ValueError):
            score = 0.0
        tags = tuple(t for t in (row["tags"] or "").split(_TAG_SEP) if t)
        citation = Citation(
            source_id=row["source_id"],
            source_type=LocalKnowledgeBaseAdapter._parse_source_type(row["source_type"]),
            title=row["title"],
            url=row["url"],
            page=page,
            published_date=row["published_date"] or None,
            snippet=(row["text"] or "")[:280],
            score=score,
        )
        return RetrievedPassage(text=row["text"], citation=citation, score=score, tags=tags)

    @staticmethod
    def _parse_source_type(value: str | None) -> SourceType:
        try:
            return SourceType(str(value))
        except (ValueError, AttributeError):
            return SourceType.POLICY
