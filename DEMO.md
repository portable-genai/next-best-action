# Demo - `next-best-action` Next-Best-Action: Recommendations and Cross-Sell

Two demos: a fully **offline local demo** (no Google Cloud, deterministic, repeatable) and a
**GCP demo** on the managed stack. Both are region- and vertical-selectable.

The story to tell: candidate filtering, eligibility / suitability, and ranking are made by
**deterministic engines** an auditor can re-run. Consent is a deterministic, cited `marketing-compliance-gate` decision
consumed through the same versioned contract in both deployment shapes: a fictional local
stand-in offline and the real service on GCP. The LLM only writes the "why recommended"
explanation; nothing auto-executes (every result is maker-checker gated).

---

## 1. Local demo (offline, no Google Cloud)

### Setup

```bash
/opt/homebrew/bin/python3.14 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

### A. CLI - a banking cross-sell and an online-retail recommendation

```bash
# Singapore banking: the customer already holds savings (suppressed), the wealth upgrade is
# consent-suppressed (phone consent denied), the rewards credit card is the next-best-action.
MKT_NBA_PROFILE=local mkt-nba recommend cust-sg-bank-1 --market SG --vertical banking

# Australia online retail: stock-gated availability + affinity ranking.
MKT_NBA_PROFILE=local mkt-nba recommend cust-au-retail-1 --market AU --vertical online_retail

# Japan banking: a multi-currency FX wallet leads on affinity.
MKT_NBA_PROFILE=local mkt-nba recommend cust-jp-bank-1 --market JP --vertical banking
```

Point out, in the output: the per-recommendation **citations** (offer catalog + propensity
model + consent record), the **propensity / value score** breakdown, the **suppressed**
sections (ineligible and consent), and the **HUMAN REVIEW REQUIRED** banner.

### B. The deterministic eligibility breakdown

```bash
# Australia banking: this customer has an adverse credit flag, so the home-loan (lending)
# offer is excluded by the per-market rule; the offset account stays eligible.
MKT_NBA_PROFILE=local mkt-nba eligibility cust-au-bank-1 --market AU --vertical banking
```

### C. The audit-first static artifacts (no JS, no API)

```bash
MKT_NBA_PROFILE=local python scripts/demo.py                 # writes scripts/out/*.json
python scripts/demo_server.py --render                        # render + serve on :8711
# open http://localhost:8711/
```

### D. Presenter-paced browser walkthrough (Playwright)

A guided, narrated run over the same static pages: a real Chrome window opens, each step is
announced on the terminal (never on screen, so the audience sees a clean page) and waits for
you to press Enter before it clicks through to the next customer scenario.

```bash
# one-time
.venv/bin/pip install playwright && .venv/bin/playwright install chromium

# terminal 1
MKT_NBA_PROFILE=local python scripts/demo.py
python scripts/demo_server.py --render

# terminal 2
.venv/bin/python scripts/demo_playwright.py
```

Unattended (self-test / recording): `HEADLESS=1 DEMO_AUTO=1 .venv/bin/python scripts/demo_playwright.py`.

### E. The API + the thin console

```bash
# Terminal 1 - the real FastAPI service on the `next-best-action` port:
MKT_NBA_PROFILE=local uvicorn next_best_action.api.app:app --port 8104

# Terminal 2 - the Next.js console, on a PRODUCTION build:
cd ui && npm install && npm run build && npm run start
# open http://localhost:3000, pick a customer / market / vertical, click "Recommend".
```

`NEXT_PUBLIC_API_BASE` needs no setting here: the console already defaults to `:8104`, the
port terminal 1 binds. Demo the built console, never `make run-ui`: that target is the
developer loop and serves `next dev`, and the standing rule for every demo in the fleet is
`org-metadata/docs/demos/demo-inventory.md`: production builds only.

### F. The eval gate (`model-quality-gate`)

```bash
MKT_NBA_PROFILE=local python eval/run_eval.py    # exit 0 when every metric clears threshold
```

### Switching region + vertical

Every command above takes `--market JP|AU|SG` and `--vertical banking|online_retail`. The
seed has fictional customers, offers, rules, consent and propensity for both verticals across
all three markets, so the demo is identical in shape in each.

---

## 2. GCP demo (managed stack)

### Setup

```bash
pip install -e ".[gcp,dev]"
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project
export MKT_NBA_PROFILE=gcp
export MKT_MARKET=SG          # JP -> asia-northeast1, AU -> australia-southeast1, SG -> asia-southeast1
export MKT_VERTICAL=banking   # or online_retail
```

The residency region is resolved from the active market and **validated** against the
per-market allow-list before any call, so data stays inside the configured boundary. The
managed adapters wire **Vertex AI recommendations + propensity + BigQuery** for the customer
/ catalog / propensity inputs, **File Search** for the offer / policy corpus, **Gemini** for
the explanation, **Model Armor** for guardrails, **Cloud Logging** (WORM) for audit, **Cloud
Trace** for traces, and the **Gen AI evaluation service** for the promotion gate.

```bash
mkt-nba recommend cust-sg-bank-1 --market SG --vertical banking
python eval/run_eval.py --use-gcp
```

The deterministic engines and the domain orchestration are **identical** to the local
profile: only the adapters change. That is the no-lock-in promise - and the `onprem` profile
(fail-fast placeholders satisfying the same Protocols) is the proof you can exit the cloud.
