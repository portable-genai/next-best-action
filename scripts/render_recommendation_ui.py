#!/usr/bin/env python3
"""Dependency-free HTML renderer for a D5 recommendation set (audit-first demo).

Reads a recommendation-set JSON (written by ``scripts/demo.py``) and renders a single,
self-contained HTML file with no JavaScript and no external assets: the ranked, cited
recommendations, the score bars, the LLM "why recommended" explanation, the suppressed
offers, and the maker-checker "human review required" banner. Used for static demo
artifacts and screenshots that never drift (the input is deterministic).

Every result section carries a stable ``data-panel='<slug>'`` hook and every load-bearing
figure carries its own ``data-*`` attribute (``data-nba-*`` for the set-level counts,
``data-rec-*`` for rank/score/propensity/value/channel/citations, ``data-suppressed-*``
for the eligibility and consent suppression reasons, ``data-review-required`` for the
maker-checker state). Those hooks are the F2 evidence surface: the served-path stage of
``scripts/demo_selftest.py`` and the headless-browser walkthrough in
``tests/browser/test_served_demo_ui.py`` read the figures back through them, so the
assertions survive any restyling but break the moment a figure stops being rendered.

Usage::

    python scripts/render_recommendation_ui.py scripts/out/sg_banking_cust-sg-bank-1.json
    # writes scripts/out/<same-stem>.html
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

_CSS = """
body { font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       color: #131b27; background: #f5f7fa; margin: 0; padding: 24px; }
.wrap { max-width: 880px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 4px; }
.tags span { display: inline-block; border: 1px solid #bdd2ff; background: #eef4ff; color: #2237ad;
             border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 600; margin-right: 6px; }
.banner { border: 1px solid #fcd34d; background: #fffbeb; color: #92400e; font-weight: 600;
          border-radius: 8px; padding: 10px 12px; font-size: 12px; margin: 12px 0; }
.panel { border: 1px solid #cdd7e4; background: #fff; border-radius: 12px; margin: 16px 0;
         box-shadow: 0 1px 2px rgba(11,16,26,.06), 0 8px 24px rgba(11,16,26,.06); }
.panel h2 { font-size: 13px; margin: 0; padding: 10px 16px; border-bottom: 1px solid #e6ebf2; }
.panel .body { padding: 16px; }
.rec { border-bottom: 1px solid #e6ebf2; padding: 12px 0; }
.rec:last-child { border-bottom: 0; }
.rank { background: #2945d6; color: #fff; border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 700; }
.meta { color: #7790ae; font-size: 12px; }
.bar { display: inline-block; width: 160px; height: 8px; border: 1px solid #cdd7e4; border-radius: 6px;
       background: #e6ebf2; overflow: hidden; vertical-align: middle; }
.bar > i { display: block; height: 100%; background: linear-gradient(90deg,#5d87fb,#2945d6); }
.cit { display: flex; gap: 8px; align-items: baseline; border: 1px solid #cdd7e4; background: #f5f7fa;
       border-radius: 6px; padding: 4px 8px; margin-top: 6px; font-size: 12px; }
.cit .lab { border: 1px solid #bdd2ff; background: #eef4ff; color: #2237ad; border-radius: 4px;
            padding: 0 6px; font-family: ui-monospace, Menlo, monospace; font-size: 11px; font-weight: 600; }
.sup { color: #546b8b; font-size: 13px; }
"""

_SOURCE_LABEL = {
    "offer_catalog": "OFFER",
    "eligibility_rule": "RULE",
    "propensity": "MODEL",
    "consent": "CONSENT",
    "policy": "POLICY",
}


def _esc(text: object) -> str:
    return html.escape(str(text))


def _bar(value: float) -> str:
    pct = round(float(value or 0) * 100)
    return (
        f'<span class="bar" data-score-pct="{pct}"><i style="width:{pct}%"></i></span> '
        f'<span class="meta">{pct}%</span>'
    )


def _panel(slug: str, title: str, inner: str) -> str:
    """One result section with a stable, styling-independent evidence hook (F2)."""
    return (
        f'<div class="panel" data-panel="{slug}"><h2>{_esc(title)}</h2>'
        f'<div class="body" data-panel-body="{slug}">{inner}</div></div>'
    )


def _citations(cits: list[dict]) -> str:
    if not cits:
        return '<div class="meta" data-citation-count="0">(no citations)</div>'
    rows = []
    for c in cits:
        lab = _SOURCE_LABEL.get(c.get("source_type", ""), "SRC")
        rows.append(
            f'<div class="cit" data-citation-source="{_esc(c.get("source_id", ""))}" '
            f'data-citation-type="{_esc(c.get("source_type", ""))}">'
            f'<span class="lab">{lab}</span>'
            f"<span>{_esc(c.get('title', ''))}</span>"
            f'<span class="meta" style="margin-left:auto">{_esc(c.get("source_id", ""))}</span></div>'
        )
    return f'<div data-citation-count="{len(cits)}">{"".join(rows)}</div>'


def render(data: dict) -> str:
    market = _esc(data.get("market"))
    vertical = _esc(data.get("vertical"))
    review = bool(data.get("requires_human_review"))
    banner = ""
    if review:
        banner = (
            '<div class="banner" data-review-required="true">HUMAN REVIEW REQUIRED — '
            "maker-checker gate. Do not surface these offers to the customer until a "
            "qualified operator signs off.</div>"
        )

    recommendations = data.get("recommendations", [])
    recs = []
    for r in recommendations:
        channel = r.get("channel") or "n/a"
        recs.append(
            f'<div class="rec" data-rec-offer="{_esc(r.get("offer_id"))}" '
            f'data-rec-rank="{_esc(r.get("rank"))}" '
            f'data-rec-score="{_esc(r.get("score"))}" '
            f'data-rec-propensity="{_esc(r.get("propensity"))}" '
            f'data-rec-value="{_esc(r.get("value_score"))}" '
            f'data-rec-kind="{_esc(r.get("kind"))}" '
            f'data-rec-channel="{_esc(channel)}" '
            f'data-rec-citations="{len(r.get("citations", []))}">'
            f'<span class="rank">#{_esc(r.get("rank"))}</span> <b>{_esc(r.get("name"))}</b> '
            f'<span class="meta">[{_esc(r.get("kind"))}] · channel {_esc(channel)} · '
            f"propensity {_esc(r.get('propensity'))} · value {_esc(r.get('value_score'))}</span> "
            f"{_bar(r.get('score', 0))}"
            f'<div class="meta" style="color:#33445b">{_esc(r.get("explanation", ""))}</div>'
            f"{_citations(r.get('citations', []))}"
            "</div>"
        )
    recs_html = "".join(recs) or '<div class="meta">none</div>'
    recs_html = f'<div data-rec-count="{len(recommendations)}">{recs_html}</div>'

    ineligible = data.get("suppressed", [])
    consent_suppressed = data.get("consent_suppressed", [])
    suppressed = []
    for e in ineligible:
        reasons = "; ".join(e.get("reasons", []))
        suppressed.append(
            f'<div class="sup" data-suppressed-offer="{_esc(e.get("offer_id"))}" '
            f'data-suppressed-basis="eligibility" data-suppressed-reason="{_esc(reasons)}">'
            f"<b>{_esc(e.get('offer_id'))}</b>: {_esc(reasons)}</div>"
        )
    for c in consent_suppressed:
        suppressed.append(
            f'<div class="sup" data-suppressed-offer="{_esc(c.get("offer_id"))}" '
            f'data-suppressed-basis="consent" data-suppressed-reason="{_esc(c.get("reason"))}" '
            f'data-suppressed-channel="{_esc(c.get("channel") or "n/a")}">'
            f"<b>{_esc(c.get('offer_id'))}</b>: {_esc(c.get('reason'))}</div>"
        )
    sup_panel = (
        _panel(
            "suppressed",
            "Suppressed (ineligible / consent)",
            f'<div data-suppressed-count="{len(suppressed)}">{"".join(suppressed)}</div>',
        )
        if suppressed
        else ""
    )

    header = (
        f'<div data-nba-set="{_esc(data.get("id"))}" '
        f'data-nba-customer="{_esc(data.get("customer_id"))}" '
        f'data-nba-market="{market}" data-nba-vertical="{vertical}" '
        f'data-nba-recommendations="{len(recommendations)}" '
        f'data-nba-ineligible="{len(ineligible)}" '
        f'data-nba-consent-suppressed="{len(consent_suppressed)}" '
        f'data-nba-review="{str(review).lower()}"></div>'
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>D5 Next-Best-Action — {_esc(data.get("customer_id"))}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
{header}
<h1>Next-best-action — {_esc(data.get("customer_id"))}</h1>
<div class="tags"><span>{market}</span><span>{vertical}</span></div>
{banner}
{_panel("summary", "Summary", _esc(data.get("summary")))}
{_panel("recommendations", "Recommendations (ranked, deterministic)", recs_html)}
{sup_panel}
</div></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: render_recommendation_ui.py <result.json>", file=sys.stderr)
        return 2
    in_path = Path(args[0])
    data = json.loads(in_path.read_text(encoding="utf-8"))
    out_path = in_path.with_suffix(".html")
    out_path.write_text(render(data), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
