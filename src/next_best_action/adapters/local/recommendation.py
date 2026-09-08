"""Local recommendation adapter (RecommendationPort) : the laptop's DuckDB feature store.

The ``local`` profile's stand-in for **BigQuery plus Vertex AI**: a DuckDB file holding the
same four tables the managed dataset holds, in the same column order, self-seeded from the
shipped book under ``next_best_action/data/demo_book/``. DuckDB is an embedded engine in a
wheel, so this needs no service, no credentials and nothing to start, and the offline gate
stays offline while the store it exercises is still SQL.

Holding the same shape as the managed store is the point. Two stores that merely both work
are two stores nobody can compare; two stores over one book and one column order can be run
side by side and their answers held against each other.

**Propensity is read, not computed, and that is a behaviour change worth stating.** This
adapter used to derive a score at request time from the customer's affinity blended with a
value prior, while the managed adapter has always read rows and refused to recommend an offer
with no signal. The two profiles therefore disagreed about what a propensity is: a function
here and a feature table there, so the local profile could rank an offer the deployment would
refuse. In production a model writes those rows, which makes reading them the real shape. The
scores the old formula produced are shipped in the book, so nothing about the demo's numbers
changed; what changed is that both profiles now get them the same way, including the refusal.

Consent is not served here. It belongs to `marketing-compliance-gate` and is read from that
service, so the ranking engine never gets a second, private answer to a question another
system owns.
"""

from __future__ import annotations

from pathlib import Path

from hex_service_kit.demobook import DuckDbStore

from ... import demo_book
from ...config import Settings
from ...domain.errors import UnknownCustomerError
from ...domain.models import (
    Customer,
    EligibilityRule,
    Market,
    Offer,
    PropensitySignal,
    Vertical,
)

#: Default on-disk location for the laptop store (overridable via settings.local.book_path).
_DEFAULT_BOOK_PATH = Path.home() / ".next_best_action" / "book.duckdb"

_SOURCE = "DuckDB propensity feature table (local)"


class LocalRecommendationAdapter:
    """Serve customers, offers, rules and propensity from the laptop's DuckDB book."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "book_path", "") or str(_DEFAULT_BOOK_PATH)
        self._store = DuckDbStore(demo_book.BOOK, path)
        self._conn = self._store.connection

    def close(self) -> None:
        """Close the connection (the CLI and tests reopen the same file)."""
        self._store.close()

    # ------------------------------------------------------------------ #
    # RecommendationPort
    # ------------------------------------------------------------------ #
    def customer(self, customer_id: str, market: Market, vertical: Vertical) -> Customer:
        columns = ", ".join(demo_book.CUSTOMERS.columns)
        rows = self._conn.execute(
            f"SELECT {columns} FROM customers "
            "WHERE customer_id = ? AND market = ? AND vertical = ?",
            [customer_id, market.value, vertical.value],
        ).fetchall()
        if len(rows) != 1:
            known = [
                row[0]
                for row in self._conn.execute(
                    "SELECT customer_id FROM customers ORDER BY 1"
                ).fetchall()
            ]
            raise UnknownCustomerError(
                f"unknown customer '{customer_id}' in {market.value}/{vertical.value}; "
                f"seed customers: {known}"
            )
        row = dict(zip(demo_book.CUSTOMERS.columns, rows[0], strict=True))
        if not str(row.get("tenant") or "").strip():
            # Fail closed exactly as the managed adapter does: a customer with no owning
            # tenant is unreachable rather than public.
            raise ValueError("customer row has no tenant partition")
        return demo_book.to_customer(row)

    def catalog(self, market: Market, vertical: Vertical) -> tuple[Offer, ...]:
        columns = ", ".join(demo_book.OFFERS.columns)
        rows = self._conn.execute(
            f"SELECT {columns} FROM offers "
            "WHERE market = ? AND vertical = ? AND active = TRUE ORDER BY offer_id LIMIT ?",
            [market.value, vertical.value, self._settings.recommendation.max_candidates],
        ).fetchall()
        return tuple(
            demo_book.to_offer(dict(zip(demo_book.OFFERS.columns, row, strict=True)))
            for row in rows
        )

    def eligibility_rules(self, market: Market, vertical: Vertical) -> tuple[EligibilityRule, ...]:
        columns = ", ".join(demo_book.ELIGIBILITY_RULES.columns)
        rows = self._conn.execute(
            f"SELECT {columns} FROM eligibility_rules "
            "WHERE market = ? AND vertical = ? AND active = TRUE ORDER BY rule_id",
            [market.value, vertical.value],
        ).fetchall()
        return tuple(
            demo_book.to_rule(dict(zip(demo_book.ELIGIBILITY_RULES.columns, row, strict=True)))
            for row in rows
        )

    def propensity(
        self, customer: Customer, offers: tuple[Offer, ...]
    ) -> tuple[PropensitySignal, ...]:
        """Read one stored signal per candidate offer, refusing when any is missing.

        The refusal is deliberate parity with the managed adapter. An offer with no signal is
        an offer nothing has scored, and ranking it on a default would put a number in front
        of a customer that no model produced.
        """
        if not offers:
            return ()
        names = {offer.id: offer.name for offer in offers}
        placeholders = ", ".join("?" for _ in offers)
        rows = self._conn.execute(
            "SELECT customer_id, offer_id, market, vertical, score, model_version, computed_at "
            "FROM propensity_signals "
            "WHERE customer_id = ? AND market = ? AND vertical = ? "
            f"AND offer_id IN ({placeholders})",
            [customer.id, customer.market.value, customer.vertical.value, *names],
        ).fetchall()
        columns = demo_book.PROPENSITY_SIGNALS.columns
        by_offer = {str(row[1]): dict(zip(columns, row, strict=True)) for row in rows}
        missing = [offer.id for offer in offers if offer.id not in by_offer]
        if missing:
            raise RuntimeError(f"local propensity has no signal for offers: {missing}")
        return tuple(
            demo_book.to_signal(by_offer[offer.id], names[offer.id], _SOURCE) for offer in offers
        )
