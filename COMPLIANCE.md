# COMPLIANCE: Mkt5 Next-Best-Action Recommendations and Cross-Sell Engine

This maps every General Principle (P-01..P-13) and dependency rule (R1..R8) to a concrete
control in **this** repo. Where a principle does not apply to Mkt5, it is marked **n/a** with
the reason. Mkt5 is the **only per-customer** marketing repo, so its data-protection, tenancy
and consent controls are load-bearing (contrast Mkt1..Mkt4, which handle no customer PII).

> The customer, offer and consent data in `tests/`, `eval/` and the local seed is
> **fictional**. This build is a reference piece and is **not** intended for live customer data
> without your own legal, security and model-risk sign-off.

---

## General Principles

| # | Principle | How Mkt5 implements it | Evidence |
|---|-----------|----------------------|----------|
| **P-01** | Managed-first, minimal surface | Only the managed services the pinned stack uses are enabled; the agent is hosted on Agent Runtime | `infra/terraform/apis.tf`, `agent/root_agent.py` |
| **P-02** | No vendor lock-in (ports and adapters) | Domain depends only on `Protocol` ports; a profile switch rebinds adapters with no domain change. The `local` family proves the same domain runs entirely off-cloud (deterministic recommender and LLM, no Google Cloud SDK) | `ports/`, `config.py`, `adapters/local/*`, `adapters/onprem/*` |
| **P-03** | Data residency (in-country) | **PARTIAL, and the gap is Agent Search.** Region selected at deploy from a residency allowlist, with per-market overrides (JP / AU / SG), validated to fail fast; regional endpoints; `gcp.resourceLocations` Org Policy; VPC-SC perimeter. **Agent Search serves no Cloud region at all** (`global`, `us` and `eu` only), so the retrieval corpus cannot be in-country at any setting: it defaults to `global`, which carries no residency guarantee. `us` or `eu` confines it to one jurisdiction and is the stronger choice where a residency obligation bites, and `gcp.resourceLocations` must be wide enough to permit whichever is chosen. | `config/settings.yaml` (`markets`), `infra/terraform/variables.tf`, `org_policy.tf`, `vpc_sc.tf` |
| **P-04** | Minimise PII to the model | `redaction.redact` runs before any model call, and the model-boundary callback redacts again; the internal customer key is pseudonymized; spans capture no content. The national-id detectors come from the shared `pii-kit` | `domain/recommendation_service.py`, `adapters/gcp/dlp_redaction.py` (`pii_kit`), `agent/callbacks.py` |
| **P-05** | Grounding over fine-tuning | Offer context is retrieved from the governed Hrz2 KB; the model explains, it is not trained on customer data | `ports/knowledge_base.py`, `domain/recommendation_service.py` |
| **P-06** | Human-in-the-loop / maker-checker | Every `RecommendationSet` is `requires_human_review=True`; a human signs off before an offer is actioned, and consent-suppressed offers are never recommendable; the escalation is ROUTED to the Hrz7 maker-checker console (rule R8), not left as a boolean | `domain/recommendation_service.py`, `ports/consent.py`, `ports/review_router.py`, `adapters/*/review_router.py` |
| **P-07** | Auditable and explainable by design | Every recommendation writes a WORM `AuditEvent` (already redacted) with the decision and citations; the ADK after-agent callback audits again at the model boundary | `domain/recommendation_service.py`, `adapters/gcp/cloud_logging_audit.py`, `agent/callbacks.py` |
| **P-08** | Eval-gated promotion | Offline eval gate scores ranking / eligibility accuracy, consent-suppression correctness and PII safety; Hrz4 at promotion | `eval/run_eval.py`, `ports/observability.py` (`EvaluationGatePort.gate`) |
| **P-09** | Defense in depth / zero trust | CMEK, least-privilege IAM, private endpoints, a distinct agent identity; **fail-closed object authorization** (a customer outside the verified principal's tenant is denied); redact then screen twice | `infra/terraform/kms.tf`, `iam.tf`, `domain/recommendation_service.py` (cross-tenant deny), `agent/callbacks.py` |
| **P-10** | Provenance on every claim | Every recommendation carries a source-and-page `Citation` and an explanation; the model only explains the deterministic ranking | `domain/models.py` (`Citation`), `domain/ranking_service.py` |
| **P-11** | Cost and latency control | A small triage-tier model handles routing / pre-checks; the reasoning model only explains the already-computed ranking | `config.py` (`ModelSettings.triage`) |
| **P-12** | Reversibility / documented exit | The `local` adapters run the whole pipeline off-cloud today (the working proof), and the `onprem` placeholders satisfy the same Protocols as the fail-fast sovereign target; the contract test proves parity for both | `adapters/local/*`, `adapters/onprem/*`, `tests/contract/test_port_parity.py`, `docs/onprem-migration.md` |
| **P-13** | Fair, consented marketing (advertising compliance) | Every candidate channel is checked against Mkt6 through its versioned client contract; an unavailable or non-allow answer is suppressed, never recommended. Eligibility / suitability remains deterministic in Mkt5 | `ports/consent.py`, `adapters/{local,gcp,onprem}/consent.py`, `domain/eligibility_service.py` |

---

## Dependency rules

Mkt5's mandatory dependencies are **Hrz1, Hrz2, Hrz3, Hrz4 (gate), Hrz5 and Mkt6** (see
`systems/`). Each rule is satisfied by consuming the sibling service through a `platform`
adapter (with an on-prem stub), never by re-implementing the concern.

| Rule | Requirement | How Mkt5 satisfies it | Evidence |
|------|-------------|---------------------|----------|
| **R1** | Customer PII handling: Hrz1 guardrail + DLP redaction | **Load-bearing.** The full safety pipeline runs on every recommendation: redact (Cloud DLP, with the shared `pii-kit` national-id detectors), screen INPUT, screen OUTPUT, and the model-boundary callback redacts + screens again. Customer PII never reaches the model, a span or the audit sink | `domain/recommendation_service.py`, `ports/safety.py`, `adapters/gcp/dlp_redaction.py`, `agent/callbacks.py` |
| **R2** | Audit to Hrz5 | Every recommendation writes an immutable, already-redacted WORM `AuditEvent`; the `platform` adapter posts to Hrz5 `/v1/audit` | `adapters/gcp/cloud_logging_audit.py`, `adapters/platform/remote_audit.py` |
| **R3** | Governed RAG via Hrz2 | Offer / product context is retrieved via the Hrz2 governed KB (`KnowledgeBasePort`) so the explanation is grounded | `ports/knowledge_base.py`, `adapters/platform/remote_knowledge_base.py` |
| **R4** | Register in Hrz3 | The A2A AgentCard is published at `/.well-known/agent-card.json` and resolvable via Hrz3; the governed MCP tool catalog scopes access least-privilege | `agent/agent_card.py`, `api/app.py`, `adapters/platform/remote_registry.py`, `adapters/gcp/mcp_tool_catalog.py` |
| **R5** | Hrz4 promotion gate | `EvaluationGatePort.gate` checks the Hrz4 thresholds before promotion; the offline gate guards merges | `ports/observability.py`, `adapters/platform/remote_evaluation.py`, `eval/run_eval.py` |
| **R6** | Validated by Rsk3 at intake | As a new project, Mkt5 is validated by the Rsk3 intake validator externally. n/a in-repo | intake handled by Rsk3 externally |
| **R7** | Marketing compliance via Mkt6 | Mkt5 makes per-customer offers, so it asks Mkt6 through `consent-preference-kit` for each candidate channel. The managed adapter has no BigQuery fallback and refuses an unconfigured store; local is a fictional stand-in behind the same wire contract | `ports/consent.py`, `adapters/{local,gcp,onprem}/consent.py`, `tests/unit/test_consent_port.py` |
| **R8** | Route `requires_human_review` to Hrz7 | Every escalated `RecommendationSet` is submitted to the Hrz7 Human-Review & Maker-Checker Console via the shared `review-kit` client (redact-before-wire: the internal customer key is pseudonymized and national ids / email / phone are masked, so no raw customer identifier reaches Hrz7). `local` enqueues to a transactional outbox so the routing path runs offline, `gcp`/`platform` submit over S2S to Hrz7's service intake (`HRZ_HUMAN_REVIEW_URL`); the verified principal's tenant is threaded onto the wire | `ports/review_router.py`, `adapters/{local,platform,onprem}/review_router.py`, `adapters/_review_payload.py` |

---

## Specific data-protection emphasis (R1, customer PII; C2..C4 PASS)

- **Redact before the model, span and audit (P-04).** The orchestrator redacts before any
  outbound call; the national-identifier detectors are **jurisdiction-driven** and sourced from
  the shared, versioned `pii-kit` (SG / HK / JP / AU rows), so a non-SG deployment scrubs and
  gates on its own identifiers. The ADK callback redacts again at the model boundary.
- **Fail-closed object authorization (C2, P-09).** Identity is server-verified; a customer whose
  tenant does not match the verified principal's is **denied** (`AuthorizationError`), so a
  demo-bank operator can never pull an other-bank customer. This holds on the agent tool path
  too (the tool resolves the principal via the IdentityPort, never from model input; a
  cross-tenant denial test proves it).
- **Consent-gated offers (C3, P-13).** Every candidate is consent-checked per channel; an offer
  without consent is suppressed and can never be presented as recommendable.
- **Jurisdiction PII pack (C4).** The redaction / DLP forms and the eval PII-safety scorer use
  the shared `pii-kit`, so the leak-class check cannot go
  falsely green.
- **Fictional data only.** The synthetic customer fixtures use obviously-fake ids and must not
  be treated as real. Live customer data requires sign-off before any deployment.

---

## Appendix: regulator crosswalk (adopter-owned)

The `P-*` / `R*` catalog above is this build's internal control language; a regulated adopter
maps it onto its own supervisor's requirements. The rows below are a **reference mapping** for
the home markets (JP / AU / SG); a fork adds a column per additional regulator. This appendix
is *adopter-owned*: a template, not legal advice.

| Mkt5 control | Reference regime | What a supervisor looks for |
|---|---|---|
| P-04 redact-before-everything; R1 safety pipeline | PDPA (SG), APP (AU), APPI (JP) | Customer PII minimised before processing and protected in transit and at rest |
| P-09 fail-closed tenancy (C2) | MAS TRM / APRA CPS 234 (access control) | Least-privilege, server-side authorization; no cross-tenant object leak |
| P-13 / R7 consent + suitability (C3) | PDPA / APP marketing consent; suitability rules | Marketing consent honoured per channel; offers eligibility / suitability-checked |
| P-06 maker-checker; P-10 provenance | MAS FEAT (Accountability); record-keeping | A human disposes of every recommendation; each offer traceable to its rule / citation |
| P-03 residency; P-12 exit | MAS Outsourcing / Cloud guidelines | In-country data residency and a demonstrable exit / portability plan |
| P-08 quality / model-risk gate | MAS FEAT; model-risk expectations | A promotion gate with ranking-accuracy / PII-safety metrics and model documentation |

**To add another regulator**: copy this table, replace the reference column with that
supervisor's instrument and section numbers, and re-review the third column with local
counsel. The Mkt5-control column is stable across regulators; only the mapping changes. The
sibling **Rsk2 control-mapping toolkit** and **Rsk1 compliance assistant** generate and
maintain these crosswalks at scale.
