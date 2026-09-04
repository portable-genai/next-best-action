# Architecture - `next-best-action` Next-Best-Action: Recommendations and Cross-Sell

`next-best-action` is a **ports-and-adapters (hexagonal)** service. The domain is pure Python with no
framework dependency; everything external is a port (a `typing.Protocol`) with swappable
adapter families. This is what makes the managed Google Cloud stack replaceable by an
on-premise one without touching domain logic.

## The hexagon

```
                 +--------------------------------------------------+
                 |                   DOMAIN (pure)                  |
   CLI  ----\    |  models  errors  serialization                  |
   API  -----+-> |  CandidateFilterService   EligibilityService    |
   Agent ---/    |  RankingService                                  |
                 |  RecommendationService (orchestrator)           |
                 +-----------------------+--------------------------+
                                         | ports (Protocols)
        +------------------+-------------+------------+------------------+
        |                  |             |            |                  |
   RecommendationPort  ConsentPort  KnowledgeBasePort  LlmPort  GuardrailPort  Audit / Tracer
   (Vertex+BigQuery)   (File Search)    (Gemini)  (Model Armor)   EvalGate / Registry / Tools
        |                  |             |            |                  |
   +----+----+        +----+----+   +----+----+  +----+----+      (gcp / local / onprem
   gcp local onprem    gcp local     gcp local    gcp local         / platform adapters)
                       platform onprem  onprem      platform onprem
```

## The deterministic engines (the heart)

The consequential decisions are made by **pure, stdlib-only, unit-tested** engines. Same
inputs -> same output: no LLM, no clock, no randomness, no network inside them. This is the
`deterministic-domain-service` skill applied: the math an auditor must be able to re-run is
code, not a model call.

1. **CandidateFilterService** (`candidate_service.py`) - scopes the catalog to the
   customer's market/vertical, drops already-held and conflicting offers, drops out-of-stock
   retail offers. Stable order by business value then id.
2. **EligibilityService** (`eligibility_service.py`) - evaluates per-market/vertical rules
   (`REQUIRE` / `EXCLUDE` / `REQUIRE_STOCK`) plus offer-level required attributes. Banking =
   suitability; online retail = availability + segment gating. Records which rules fired,
   with citations.
3. **ConsentPort** (`ports/consent.py`) - asks `marketing-compliance-gate`, the one consent and preference store,
   through the pinned `consent-preference-kit` contract. It is fail-closed on missing answers;
   the local adapter uses fictional data and the on-prem adapter is the client integration seam.
4. **RankingService** (`ranking_service.py`) - combined score
   `propensity_weight*propensity + value_weight*value` over the eligible, consented offers;
   value is min-max normalised; stable tie-break by offer id.

The **RecommendationService** orchestrator composes the three engines and the ports, guards
the input/output (`agent-guardrail-gateway`), traces each step (`agent-observability`), audits the interaction (`agent-observability` WORM), and sets
`requires_human_review=True` (maker-checker). The LLM (`LlmPort`) is called only to write the
"why recommended" explanation over the already-fixed ranking; it never decides a number.

## Adapter families

| Profile | Adapters | Notes |
| ------- | -------- | ----- |
| `local` | deterministic recommendation/propensity store, fictional `marketing-compliance-gate` consent stand-in, SQLite FTS5 corpus, deterministic LLM, heuristic guardrail, append-only audit, no-op tracer, in-repo eval, in-process registry/tools | SDK-free, seedable, the dev/test/CI default |
| `gcp` | Vertex AI recommendations + propensity + BigQuery, `marketing-compliance-gate` consent service, Gemini, File Search, Model Armor, Cloud Logging WORM, Cloud Trace, Gen AI eval, A2A registry, MCP tool catalog | all Google imports are LAZY (method-body), so the module imports under `[dev]` only |
| `onprem` | fail-fast `NotImplementedError` placeholders satisfying the same Protocols | exit-portability / no-lock-in proof |
| `platform` | thin HTTP clients to the shared `agent-guardrail-gateway`-`agent-observability` platform services; the `model-quality-gate` promotion gate is a live client (`RemoteEvaluationAdapter`, bundle `mkt5-nba`), not a placeholder | reuse the platform where natural |

The `Container` (`config.py`) binds each port to a profile's adapter by dotted path from
`config/settings.yaml`. Switching profiles is one line (`MKT_NBA_PROFILE`).

## Generic, multi-vertical, APAC

`Vertical` (banking | online_retail) and `Market` (JP | AU | SG) are enums; per-market
residency regions, locales and per-market/vertical rules and catalog live in **seed + config**
(`adapters/local/_seed.py`, `config/settings.yaml`), never in a hard-coded branch. The
residency region is validated against the per-market allow-list (`adapters/gcp/_region.py`)
before any managed-stack call, so data never leaves the configured boundary.

## Provenance and governance

Every recommendation carries `Citation`s (offer catalog + propensity signal + `marketing-compliance-gate` consent
decision). The result is `requires_human_review=True` (maker-checker). Every interaction is
written to a WORM audit sink. The `model-quality-gate` (`eval/run_eval.py`) blocks promotion if
groundedness, citation accuracy, eligibility accuracy or review safety fall below threshold.
Under the `platform` profile that gate delegates to `model-quality-gate` over HTTP (`POST /v1/evaluations` and
`POST /v1/gate`, bundle `mkt5-nba`), which owns the metric set and thresholds.
