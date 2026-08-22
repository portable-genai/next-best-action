#!/usr/bin/env python3
"""Credential-free anti-rot check for the real D5 presenter demo.

Two stages, both executed, neither reading hard-coded prose:

1. **In-process** : ``scripts/demo.py`` runs the real recommendation service over every
   synthetic scenario and every artifact is rendered.
2. **Served** : the REAL presenter server from ``scripts/demo_server.py`` is started on an
   ephemeral port and the whole artifact index plus every artifact page is fetched over
   HTTP. Every figure asserted at this stage is read out of the SERVED bytes through the
   stable ``data-*`` evidence hooks and compared with the value the RUNNING app computed,
   so a renderer that stops emitting a figure, a server that stops listing an artifact, or
   a hook that gets renamed all fail here. The old check only asserted that a rendered
   string contained some prose, which stayed true no matter what the figures said.

The headless-browser journey over the same served pages lives in
``tests/browser/test_served_demo_ui.py`` and needs the pinned ``[demo]`` extra.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from pathlib import Path

import demo
import demo_server
from render_recommendation_ui import render


def _hook(page: str, attribute: str) -> str:
    """Read one stable ``data-*`` evidence hook out of served markup."""
    match = re.search(rf"{attribute}='([^']*)'", page) or re.search(rf'{attribute}="([^"]*)"', page)
    assert match, f"evidence hook {attribute} is missing from the served page"
    return match.group(1)


def _hooks(page: str, attribute: str) -> list[str]:
    return re.findall(rf"{attribute}='([^']*)'", page) or re.findall(
        rf'{attribute}="([^"]*)"', page
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_in_process() -> list[Path]:
    assert demo.main() == 0
    paths = sorted(demo._OUT.glob("*.json"))
    assert len(paths) == len(demo._SCENARIOS) == 6
    for path in paths:
        data = _load(path)
        assert data["requires_human_review"] is True
        assert data["recommendations"]
        page = render(data)
        assert page.startswith("<!doctype html>")
        assert _hook(page, "data-review-required") == "true"
    print("PASS demo self-test: 6/6 live recommendation sets generated and rendered")
    return paths


def _assert_served_artifact(page: str, data: dict) -> None:
    """Served bytes vs what the running recommendation service actually computed."""
    recommendations = data["recommendations"]
    ineligible = data.get("suppressed") or []
    consent_suppressed = data.get("consent_suppressed") or []

    # Set-level figures.
    assert _hook(page, "data-nba-set") == data["id"]
    assert _hook(page, "data-nba-customer") == data["customer_id"]
    assert _hook(page, "data-nba-market") == data["market"]
    assert _hook(page, "data-nba-vertical") == data["vertical"]
    assert _hook(page, "data-nba-recommendations") == str(len(recommendations))
    assert _hook(page, "data-nba-ineligible") == str(len(ineligible))
    assert _hook(page, "data-nba-consent-suppressed") == str(len(consent_suppressed))
    assert _hook(page, "data-nba-review") == str(bool(data["requires_human_review"])).lower()

    # The maker-checker gate is a rendered state, not a sentence someone might reword.
    assert _hook(page, "data-review-required") == "true"

    # Result panels the artifact page is supposed to show.
    panels = _hooks(page, "data-panel")
    for slug in ("summary", "recommendations"):
        assert slug in panels, f"the served page lost the {slug} panel hook"
    if ineligible or consent_suppressed:
        assert "suppressed" in panels, "the served page lost the suppressed panel hook"

    # Every ranked recommendation, in order, with the figures the deterministic scorer
    # assigned it. A renderer that stops recomputing one of these fails here.
    assert _hook(page, "data-rec-count") == str(len(recommendations))
    assert _hooks(page, "data-rec-offer") == [r["offer_id"] for r in recommendations]
    assert _hooks(page, "data-rec-rank") == [str(r["rank"]) for r in recommendations]
    assert _hooks(page, "data-rec-score") == [str(r["score"]) for r in recommendations]
    assert _hooks(page, "data-rec-propensity") == [str(r["propensity"]) for r in recommendations]
    assert _hooks(page, "data-rec-value") == [str(r["value_score"]) for r in recommendations]
    assert _hooks(page, "data-rec-channel") == [(r["channel"] or "n/a") for r in recommendations]
    assert _hooks(page, "data-rec-citations") == [
        str(len(r.get("citations") or [])) for r in recommendations
    ]

    # Every suppression, with the basis the engine suppressed it on. Eligibility rows come
    # first, then consent rows, which is the order the renderer builds them in.
    expected_suppressed = [e["offer_id"] for e in ineligible] + [
        c["offer_id"] for c in consent_suppressed
    ]
    assert _hooks(page, "data-suppressed-offer") == expected_suppressed
    assert _hooks(page, "data-suppressed-basis") == ["eligibility"] * len(ineligible) + [
        "consent"
    ] * len(consent_suppressed)
    if expected_suppressed:
        assert _hook(page, "data-suppressed-count") == str(len(expected_suppressed))

    # Every live citation the running app produced is on the served page.
    served_sources = _hooks(page, "data-citation-source")
    for rec in recommendations:
        for citation in rec.get("citations") or []:
            assert citation["source_id"] in served_sources, citation["source_id"]


def check_served(paths: list[Path]) -> None:
    """Drive the REAL presenter server over HTTP and assert live figures from served bytes."""
    server = demo_server.make_server(0, render=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with urllib.request.urlopen(f"{base}/", timeout=20) as response:  # noqa: S310
            assert response.status == 200
            index = response.read().decode("utf-8")

        # The index lists exactly the artifacts the run just produced, no more and no less.
        assert "artifact-index" in _hooks(index, "data-panel")
        assert _hook(index, "data-artifact-count") == str(len(paths))
        assert _hooks(index, "data-artifact") == [p.stem for p in paths]

        for path in paths:
            with urllib.request.urlopen(f"{base}/{path.stem}.html", timeout=20) as response:  # noqa: S310
                assert response.status == 200
                page = response.read().decode("utf-8")
            _assert_served_artifact(page, _load(path))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        "PASS served: the artifact index, every panel hook and every live figure read back "
        "over HTTP from the running demo server"
    )


def main() -> int:
    paths = check_in_process()
    check_served(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
