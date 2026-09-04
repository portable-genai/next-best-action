# Demo scripts - `next-best-action` Next-Best-Action: Recommendations and Cross-Sell

All scripts are SDK-free and run against the in-process `local` stack (no Google Cloud, no
API key). They drive the real `RecommendationService` over six synthetic customers spanning
both verticals across JP, AU and SG. Run them from the repo root with the domain package on
the path:

```bash
export PYTHONPATH=src
export MKT_NBA_PROFILE=local
```

| Script | What it does |
|--------|--------------|
| `demo.py` | Runs the real recommendation service over six customers, prints a readable trace to stdout, and writes each audit view to `scripts/out/*.json`. Also the end-to-end smoke test for the slice. |
| `render_recommendation_ui.py` | Dependency-free static HTML renderer: turns one `demo.py` JSON file into a page (ranked recommendations, the suppressed/ineligible panel, citations, the human-review banner). |
| `demo_server.py` | Static file server (stdlib only) over `scripts/out/`: `--render` renders every `*.json` first, then serves an index linking to each page. `make demo-server`, then open `http://localhost:8711`. Unlike the other D-series demo servers this one has no in-process session or "Next" button; each scenario is its own static page. |
| `demo_playwright.py` | Headed, presenter-paced Playwright walkthrough: opens the index, clicks through the six customer pages in order on your cue, and spotlights the panel to look at. See [`../DEMO.md`](../DEMO.md) for the two-terminal run. |
| `demo_selftest.py` | Generates and renders every synthetic recommendation scenario, verifies the complete page set, and runs in `make gate`. |
| `portability_demo.py` | Proves the bounded local profile and portable audit contract without requiring Google Cloud. |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |

Every scenario is obviously-fictional synthetic data (see `demo.py` for the fixed set), so
screenshots and the walkthrough narration never drift between runs.
