"""F2: the presenter demo is driven through a real headless browser, not a string.

``scripts/demo_selftest.py`` starts the real server and reads the served bytes, which covers
the server/renderer path browserlessly. This file closes the other half: a pinned headless
Chromium loads the SERVED pages, follows the presenter's own artifact links, and reads every
asserted figure back out of the LIVE DOM through the stable ``data-*`` evidence hooks.
Nothing here is compared against hard-coded prose; every expectation is recomputed from the
artifacts the running recommendation service just produced.

Playwright is pinned in the ``[demo]`` extra. The browser binary is a network download, so a
fork's day-one offline gate must not depend on it: the module skips when the extra or the
browser is absent, and ``make demo-browser`` runs it for anyone who has installed it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="the pinned [demo] extra is not installed"
)


def _load(name: str) -> ModuleType:
    """Import a sibling demo script the same way ``make demo-server`` does."""
    for path in (SCRIPTS, REPO_ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo = _load("demo")
demo_server = _load("demo_server")


@pytest.fixture(scope="module")
def served() -> Iterator[tuple[str, list[Path]]]:
    """The REAL presenter server over the REAL artifacts, on an ephemeral port."""
    assert demo.main() == 0
    paths = sorted(demo._OUT.glob("*.json"))
    assert len(paths) == len(demo._SCENARIOS)

    server = demo_server.make_server(0, render=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(served: tuple[str, list[Path]]) -> Iterator[Any]:
    try:
        with playwright_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - environment-dependent
                pytest.skip(f"no pinned browser binary available: {exc}")
            context = browser.new_context()
            yield context.new_page()
            context.close()
            browser.close()
    except NotImplementedError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"playwright cannot run here: {exc}")


def _attributes(page: Any, selector: str, attribute: str) -> list[str]:
    """Read one attribute off every matching element in the LIVE DOM, in document order."""
    return page.locator(selector).evaluate_all(
        f"els => els.map(e => e.getAttribute({attribute!r}))"
    )


def _attribute(page: Any, selector: str, attribute: str) -> str:
    locator = page.locator(selector)
    assert locator.count() == 1, f"{selector} is not on the live page exactly once"
    return locator.get_attribute(attribute)


def test_the_served_index_lists_exactly_the_artifacts_the_run_produced(page, served) -> None:
    base, paths = served
    page.goto(f"{base}/", wait_until="load")

    assert page.locator("[data-panel='artifact-index']").count() == 1
    assert _attribute(page, "[data-panel='artifact-index']", "data-artifact-count") == str(
        len(paths)
    )
    assert _attributes(page, "[data-artifact]", "data-artifact") == [p.stem for p in paths]


def test_the_served_demo_walks_every_artifact_in_a_real_browser(page, served) -> None:
    base, paths = served
    page.goto(f"{base}/", wait_until="load")

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        recommendations = data["recommendations"]
        ineligible = data.get("suppressed") or []
        consent_suppressed = data.get("consent_suppressed") or []

        # Follow the presenter's OWN link rather than constructing the URL ourselves, so a
        # broken index is a failure here and not an invisible detour.
        page.locator(f"[data-artifact='{path.stem}']").click()
        page.wait_for_load_state("load")

        # Set-level figures, read out of the LIVE DOM, checked against the running app.
        for attribute, expected in (
            ("data-nba-set", data["id"]),
            ("data-nba-customer", data["customer_id"]),
            ("data-nba-market", data["market"]),
            ("data-nba-vertical", data["vertical"]),
            ("data-nba-recommendations", str(len(recommendations))),
            ("data-nba-ineligible", str(len(ineligible))),
            ("data-nba-consent-suppressed", str(len(consent_suppressed))),
            ("data-nba-review", str(bool(data["requires_human_review"])).lower()),
        ):
            assert _attribute(page, f"[{attribute}]", attribute) == expected, attribute

        # The maker-checker gate is a rendered state, not a sentence someone might reword.
        assert _attribute(page, "[data-review-required]", "data-review-required") == "true"

        for slug in ("summary", "recommendations"):
            assert page.locator(f"[data-panel='{slug}']").count() == 1, slug
        if ineligible or consent_suppressed:
            assert page.locator("[data-panel='suppressed']").count() == 1

        # Every ranked recommendation, in order, with the figures the deterministic scorer
        # assigned it.
        assert _attribute(page, "[data-rec-count]", "data-rec-count") == str(len(recommendations))
        for attribute, expected_list in (
            ("data-rec-offer", [r["offer_id"] for r in recommendations]),
            ("data-rec-rank", [str(r["rank"]) for r in recommendations]),
            ("data-rec-score", [str(r["score"]) for r in recommendations]),
            ("data-rec-propensity", [str(r["propensity"]) for r in recommendations]),
            ("data-rec-value", [str(r["value_score"]) for r in recommendations]),
            ("data-rec-channel", [(r["channel"] or "n/a") for r in recommendations]),
            (
                "data-rec-citations",
                [str(len(r.get("citations") or [])) for r in recommendations],
            ),
        ):
            assert _attributes(page, f"[{attribute}]", attribute) == expected_list, attribute

        # Every suppression, with the basis the engine suppressed it on.
        assert _attributes(page, "[data-suppressed-offer]", "data-suppressed-offer") == [
            e["offer_id"] for e in ineligible
        ] + [c["offer_id"] for c in consent_suppressed]
        assert _attributes(page, "[data-suppressed-basis]", "data-suppressed-basis") == [
            "eligibility"
        ] * len(ineligible) + ["consent"] * len(consent_suppressed)

        # Every live citation the running app produced is in the live DOM.
        rendered_sources = _attributes(page, "[data-citation-source]", "data-citation-source")
        for rec in recommendations:
            for citation in rec.get("citations") or []:
                assert citation["source_id"] in rendered_sources, citation["source_id"]

        page.go_back(wait_until="load")
