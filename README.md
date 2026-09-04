# `next-best-action` next-best-action: Recommendations and Cross-Sell

**Industries:** Retail & e-commerce, Banking, Telecom, Insurance, Travel & hospitality, Media

A generic, multi-vertical, APAC **next-best-action** engine. Given a customer (banking) or
shopper (online retail) and an offer catalog, it produces a ranked, fully cited set of
next-best-action recommendations: which offer to surface, on which channel, and why. The
Candidate filtering, eligibility / suitability, and ranking are made by **deterministic,
unit-tested engines**. Marketing consent is a cited decision obtained through `marketing-compliance-gate`'s versioned
client contract, never a second store in this repo. The LLM (Gemini) only explains "why
recommended". Built ports-and-adapters on the **Gemini Enterprise Agent
Platform**, with a working offline `local` profile, a managed `gcp` profile (Vertex AI
recommendations + propensity + BigQuery), and a fail-fast `onprem` profile.

This is repo `next-best-action` in the marketing (`mkt`) catalog. It follows the same engineering bar as
the reference builds (`compliance-advisory`, `cdd-sow-research`, `market-intelligence`) and the reusable skills in `.agents/skills/`.

## Generic, multi-vertical, APAC

`next-best-action` is deliberately **not** a bank-specific tool. It supports both verticals and all three
markets as **config + seed**, never hard-coded:

- **Verticals**: `banking` and `online_retail` are first-class. Eligibility means
  *suitability* (KYC / risk / product-holding) for banking and *availability + affinity*
  (stock + behaviour) for online retail. The same engines serve both because the rules and
  catalog differ in the seed, not the code.
- **Markets**: Japan (`asia-northeast1`), Australia (`australia-southeast1`) and Singapore
  (`asia-southeast1`), each with its residency region, locales (ja + en) and per-market
  marketing-consent regime. Region/locale/vertical are validated config, not branches.
- **Synthetic data**: obviously-fictional customers, offers, rules, consent and propensity
  for both verticals across all three markets.

## The deterministic engines (the heart)

1. **CandidateFilterService** - narrows the catalog to candidates: market/vertical scope,
   minus already-held / conflicting offers, minus out-of-stock retail offers.
2. **EligibilityService** - per-market/vertical rule evaluation (REQUIRE / EXCLUDE /
   REQUIRE_STOCK). Records exactly which rules fired, with citations.
3. **`marketing-compliance-gate` ConsentPort** - one cited decision per channel through `consent-preference-kit`.
   Local uses fictional rows behind the same wire types; managed refuses if `marketing-compliance-gate` is unconfigured.
4. **RankingService** - deterministic `propensity x value` score over the eligible,
   consented offers, min-max normalised, with a stable replayable order.

The `RecommendationService` orchestrator composes the three engines and the ports, guardrails
the input/output, audits every interaction, and sets `requires_human_review=True` on the
result (maker-checker: the agent proposes, a qualified operator disposes).

## Profiles

| Profile  | What it is | Google Cloud SDK |
| -------- | ---------- | ---------------- |
| `local`  | A WORKING offline stack: deterministic recommendation / propensity store, fictional `marketing-compliance-gate` consent stand-in, SQLite FTS5 corpus, deterministic LLM. The dev/test/CI default. | none |
| `gcp`    | Managed stack: Vertex AI recommendations + propensity + BigQuery, `marketing-compliance-gate` consent API, Gemini, File Search, Model Armor, Cloud Logging WORM, Cloud Trace, Gen AI eval. Lazy imports. | `[gcp]` extra |
| `onprem` | Fail-fast `NotImplementedError` placeholders satisfying the same Protocols (exit-portability proof). | none |

Switching profiles is a one-line change of `MKT_NBA_PROFILE` (or `profile:` in
`config/settings.yaml`). Nothing in `src/next_best_action/domain` changes.

## Quick start (offline, no Google Cloud)

```bash
/opt/homebrew/bin/python3.14 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# A banking cross-sell case in Singapore:
MKT_NBA_PROFILE=local mkt-nba recommend cust-sg-bank-1 --market SG --vertical banking

# An online-retail recommendation case in Australia:
MKT_NBA_PROFILE=local mkt-nba recommend cust-au-retail-1 --market AU --vertical online_retail

# The deterministic eligibility breakdown for every candidate offer:
MKT_NBA_PROFILE=local mkt-nba eligibility cust-au-bank-1 --market AU --vertical banking
```

## API

```bash
MKT_NBA_PROFILE=local uvicorn next_best_action.api.app:app --port 8104
curl -s localhost:8104/healthz
curl -s -X POST localhost:8104/v1/recommend \
  -H 'content-type: application/json' \
  -d '{"customer_id":"cust-sg-bank-1","market":"SG","vertical":"banking"}'
```

## UI

A thin Next.js console lives in `ui/` (see `ui/README.md`). It calls the API on port 8104
and renders the cited, human-review-gated recommendation set. It can embed same-origin into a
host portal (`NEXT_PUBLIC_BASE_PATH` + `NEXT_PUBLIC_EMBED=1`) or run standalone.

## Identity and embedding

Identity is server-verified: the client never asserts an `actor`. Every route resolves a verified
`Principal` from the active `IdentityPort` adapter, and that supplies the audit actor. The profile
picks the source: `local` = seeded dev personas (no IdP, offline), `gcp` / `platform` = verify the
Cloud IAP assertion (`MKT_NBA_IAP_AUDIENCE`), `onprem` = the client's own IdP placeholder.

In local mode, pick a demo identity with the `X-Dev-Persona` header (the UI has a picker, shown
only when the profile is `local`):

```bash
curl -s localhost:8104/v1/personas
curl -s -X POST localhost:8104/v1/recommend \
  -H 'content-type: application/json' -H 'X-Dev-Persona: auditor' \
  -d '{"customer_id":"cust-sg-bank-1","market":"SG","vertical":"banking"}'
```

Embedding-surface controls (CSP `frame-ancestors`, per-tenant CORS) and the three deployment shapes
(embedded same-origin reverse-proxy, standalone behind IAP, local dev no-auth) are documented in
[`docs/embedding-and-identity.md`](docs/embedding-and-identity.md).

## The hard gate (green before done)

In a fresh `[dev]`-only venv (no `google-cloud-*`):

```bash
ruff check src tests
ruff format --check src tests
mypy src
pytest -m 'not integration' -q
python eval/run_eval.py        # exit 0
```

See `DEMO.md` for the local (offline) and GCP demos (region + vertical selectable),
`ARCHITECTURE.md` for the hexagon, and `SPEC.md` for the domain contract.

`consent-preference-kit` is a public, commit-locked catalog common, so source installation and
the image build need no credential at all: the `git+https` line in the lockfile resolves
anonymously. Runtime `marketing-compliance-gate` authentication is separate and unchanged: managed profiles mint an
audience-bound Google ID token through Workload Identity; non-GCP/local consumers may use the
kit's `CONSENT_S2S_*` credentials.
