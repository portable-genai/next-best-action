# Spec - `next-best-action` Next-Best-Action: Recommendations and Cross-Sell

## Purpose

Given a customer (banking) or shopper (online retail) and an offer catalog, produce a ranked,
fully cited set of next-best-action recommendations: which offer to surface, on which channel,
and why. The consequential decisions are deterministic and auditable; the LLM only explains.

## Domain types (the contract)

- **Vertical** - `banking` | `online_retail` (config-driven, both first-class).
- **Market** - `JP` | `AU` | `SG`, each with a residency region and locales (config + seed).
- **Citation** - provenance on every recommendation and decision; `source_type` is one of
  `offer_catalog` | `eligibility_rule` | `propensity` | `consent` | `policy` | `other`.
- **Customer** - id, market, vertical, `attributes` (the facts rules read), `holdings`
  (already held / purchased), `affinities` (category -> 0..1).
- **Offer** - id, name, `kind` (product/upgrade/promotion/bundle/service), `category`,
  `base_value` (firm-side, normalised in ranking), `required_consent_channel`,
  `required_attributes`, `excluded_if_held`, `stock` (retail availability).
- **CandidateSet** - the offers surviving the candidate filter.
- **EligibilityRule** - per-market/vertical rule with an `effect` (`REQUIRE` / `EXCLUDE` /
  `REQUIRE_STOCK`), the `attribute` and `value` it checks, optional kind/category scope, and
  a citation.
- **EligibilityResult** - `ELIGIBLE` | `INELIGIBLE`, the reasons and failed rule ids.
- **ConsentRecord / ConsentDecision** - per-channel marketing-consent state and the gating
  decision (allowed + channel + reason + citation).
- **PropensitySignal** - a 0..1 model score per (customer, offer).
- **RankedOffer / Ranking** - the deterministic score breakdown and ordered list.
- **Recommendation** - a ranked offer bundled with its eligibility outcome, consent decision,
  LLM explanation and citations.
- **RecommendationSet** - the top-level aggregate: the recommendations, the suppressed
  (ineligible) and consent-suppressed offers, the summary, citations, and
  `requires_human_review=True`.

## Ports

| Port | Responsibility | Primary GCP adapter |
| ---- | -------------- | ------------------- |
| `RecommendationPort` | customer profile, offer catalog, eligibility rules, propensity signals | Vertex AI recommendations + propensity + BigQuery |
| `ConsentPort` | cited marketing permission from the single `marketing-compliance-gate` system of record | `marketing-compliance-gate` over `consent-preference-kit` |
| `KnowledgeBasePort` | offer / policy corpus retrieval | File Search / Agent Search |
| `LlmPort` | "why recommended" explanation (narration only) | Gemini |
| `GuardrailPort` | input/output screening (`agent-guardrail-gateway`) | Model Armor |
| `AuditSinkPort` | immutable WORM audit (`agent-observability`) | Cloud Logging locked bucket |
| `ObservabilityTracerPort` | reasoning-loop traces + token metrics (`agent-observability`) | Cloud Trace / OTel |
| `EvaluationGatePort` | `model-quality-gate` promotion gate | Gen AI evaluation service |
| `AgentRegistryPort` | A2A AgentCard registry (`agent-registry`) | A2A registry |
| `ToolCatalogPort` | governed MCP tool catalog | MCP 2026-07-28 |

## Pipeline (RecommendationService.recommend)

1. `guardrail.screen(INPUT)` - blocked input is a hard error (audited BLOCKED).
2. `recommendations.customer(...)` + `recommendations.catalog(...)`.
3. `CandidateFilterService.filter(...)` - empty candidate set is a hard error.
4. `EligibilityService.evaluate_all(...)` against per-market/vertical rules.
5. `ConsentPort.decide(...)` against `marketing-compliance-gate` for each selected channel; unavailable is a refusal.
6. `recommendations.propensity(...)` (degrades to value-only ranking if unavailable).
7. `RankingService.rank(...)` over the eligible AND consented offers.
8. `llm.generate(...)` per recommendation - explanation only.
9. assemble `RecommendationSet` (`requires_human_review=True`).
10. `guardrail.screen(OUTPUT)`; `audit.record(...)`.

## Invariants

- An ineligible or consent-suppressed offer is **never** recommended.
- An already-held or out-of-stock (retail) offer is **never** a candidate.
- Every recommendation carries at least one citation.
- The result always sets `requires_human_review=True` (maker-checker).
- The pipeline is deterministic under the local profile (same inputs -> same output).

## Quality gate (`model-quality-gate` thresholds)

- `recommendation_groundedness >= 0.80`
- `citation_accuracy >= 0.90`
- `eligibility_accuracy >= 0.90`
- `review_safety >= 0.99`

Under the `platform` profile the promotion gate is a real HTTP client to `model-quality-gate`
(`RemoteEvaluationAdapter`), not a stub: `POST /v1/evaluations` and `POST /v1/gate` with a
structured target (`{model, prompt_version, dataset_id, system}`) and a server-side metric
bundle named `mkt5-nba`. The adapter never sends a metric list; naming the bundle lets `model-quality-gate`
own the metric set and the thresholds above, so model-risk policy stays on the platform rather
than duplicated per consumer. The `gcp` profile uses the Gen AI evaluation service; `local`
runs the in-repo eval (`eval/run_eval.py`).
