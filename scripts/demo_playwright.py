"""Presenter-controlled Playwright walkthrough of the live D5 next-best-action demo.

Unlike the other D-series demo servers, ``scripts/demo_server.py`` here has no in-process
session or "Next" button: it serves the static, dependency-free HTML pages that
``render_recommendation_ui.py`` writes to ``scripts/out/`` (one per customer scenario) plus
an index that links to each. This script opens the index, then clicks through the six
customer scenarios in the index's own order, one per step, **paced by the presenter**:
before each step it prints what is about to happen and waits for you to press Enter, then
navigates and highlights the panel to look at. You stay in control.

Usage (two terminals)::

    # terminal 1 - render the artifacts and serve them
    python scripts/demo.py                    # writes scripts/out/*.json
    make demo-server                          # or: MKT_NBA_PROFILE=local PYTHONPATH=src \\
                                               #   .venv/bin/python scripts/demo_server.py --render

    # terminal 2 - the guided walkthrough (a real Chrome window opens)
    .venv/bin/pip install playwright && .venv/bin/playwright install chromium  # one-time
    .venv/bin/python scripts/demo_playwright.py

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8711)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter - advance automatically (self-test / recording)
    SLOWMO_MS   per-action slow-motion in ms (default 250 headed, 0 headless)
    CHROME_PATH explicit Chromium/Chrome binary (else Playwright's own)
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:8711")
HEADLESS = os.environ.get("HEADLESS") == "1"
AUTO = os.environ.get("DEMO_AUTO") == "1"
SLOWMO = int(os.environ.get("SLOWMO_MS", "0" if HEADLESS else "250"))
CHROME_PATH = os.environ.get("CHROME_PATH") or None

# (page stem, narration, panel to spotlight) - the index's own alphabetical order.
STEPS = [
    (
        "au_banking_cust-au-bank-1",
        "An Australia banking customer with an adverse credit flag: the per-market "
        "eligibility rule excludes the home-loan offer before ranking even runs, so the "
        "'Suppressed' panel shows one ineligible offer and only the offset account "
        "survives as the single next-best-action.",
        ".sup",
    ),
    (
        "au_online_retail_cust-au-retail-1",
        "An Australia online-retail customer: two ranked offers, stock-gated availability "
        "and affinity deciding the order. The explanation under each is the model's job; "
        "the rank and score are not.",
        ".rec",
    ),
    (
        "jp_banking_cust-jp-bank-1",
        "A Japan banking customer: a multi-currency FX wallet leads on affinity over a "
        "time deposit. Same eligibility and ranking engine, a different market's product "
        "catalog.",
        ".rec",
    ),
    (
        "jp_online_retail_cust-jp-retail-1",
        "A Japan online-retail customer: a loyalty programme beats a bento subscription. "
        "The score bar is the deterministic propensity-times-eligibility figure, not a "
        "model guess.",
        ".bar",
    ),
    (
        "sg_banking_cust-sg-bank-1",
        "A Singapore banking customer where phone consent was denied: the wealth-upgrade "
        "offer is suppressed for consent, not ineligibility, so the 'Suppressed' panel "
        "gives the reason and the rewards credit card becomes the sole next-best-action. "
        "The HUMAN REVIEW REQUIRED banner still gates it either way.",
        ".banner",
    ),
    (
        "sg_online_retail_cust-sg-retail-1",
        "A Singapore online-retail customer closes the walkthrough with two ranked offers. "
        "Every recommendation across all six customers cites the offer catalog, the "
        "propensity model and the consent record behind it.",
        ".cit",
    ),
]


def _pause(prompt: str) -> None:
    if AUTO:
        time.sleep(1.2)
        return
    try:
        input(prompt)
    except EOFError:  # non-interactive stdin
        time.sleep(1.0)


def _spotlight(page, selector: str | None) -> None:
    if not selector:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        page.eval_on_selector_all(
            selector,
            "els => els.forEach((e,i)=>{ if(i<6){ e.style.transition='box-shadow .3s';"
            " e.style.boxShadow='0 0 0 3px #3a60f0'; setTimeout(()=>e.style.boxShadow='',1600);} })",
        )


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(BASE + "/", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    if not _reachable():
        print(f"Cannot reach the demo server at {BASE}.")
        print("Start it first:  python scripts/demo.py && make demo-server")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, executable_path=CHROME_PATH)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()

        print("\n=== D5 next-best-action live demo - press Enter to advance each step ===\n")
        page.goto(BASE + "/", wait_until="load")

        for i, (stem, say, spotlight) in enumerate(STEPS):
            print(f"[{i + 1}/{len(STEPS)}] {say}")
            _pause("        press Enter to run this step... ")
            link = page.locator(f"a[href='{stem}.html']")
            if link.count():
                link.click()
                page.wait_for_load_state("load")
            page.wait_for_timeout(200)
            _spotlight(page, spotlight)
            page.wait_for_timeout(700)
            if i < len(STEPS) - 1:
                page.goto(BASE + "/", wait_until="load")  # back to the chooser for the next click
            print()

        print("Demo complete. The browser stays open for questions.")
        _pause("        press Enter to close the browser... ")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
