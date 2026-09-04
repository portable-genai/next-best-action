# On-prem migration (exit / portability): General Principle P-12

The whole point of the ports-and-adapters shape is that `next-best-action`'s exit story is **demonstrable,
not aspirational**. Switching from the managed GCP stack to a sovereign / on-premise stack is a
one-line profile change (`MKT_NBA_PROFILE=onprem`) plus filling in the adapter bodies. The
domain core, the services, the API, the CLI and the agent wiring do not change.

## What "onprem" gives you today

Setting `MKT_NBA_PROFILE=onprem` rebinds every port to a placeholder adapter under
`src/next_best_action/adapters/onprem/`. Those adapters:

- construct cleanly with **no Google Cloud SDK installed** (the contract test proves it),
- structurally satisfy the same `Protocol` as the managed GCP adapter, and
- raise `NotImplementedError` from every method that must not silently no-op (recommendation,
  knowledge base, LLM, guardrail, PII redaction, audit, evaluation, agent registry, tool
  catalog), while non-essential ports return safe defaults (the tracer is a no-op).

This is what makes the contract test `tests/contract/test_port_parity.py` meaningful: it
imports and constructs each on-prem placeholder and asserts interface parity, and separately
proves the `local` family is a WORKING offline stack implementing the same interfaces.

## The migration checklist

To run `next-best-action` on a sovereign / on-premise platform, implement these adapter bodies (the only
files that change):

| Port | On-prem file | What to implement |
|------|--------------|-------------------|
| `RecommendationPort` | `onprem/recommendation.py` | An on-prem propensity / recommendation model source |
| `ConsentPort` | `onprem/consent.py` | The client's consent and preference centre, preserving the canonical fail-closed decision contract |
| `KnowledgeBasePort` | `onprem/knowledge_base.py` | An on-prem governed RAG store for offer / product context (R3) |
| `LlmPort` | `onprem/llm.py` | An on-prem model-serving endpoint (e.g. Gemma on your own serving stack) |
| `GuardrailPort` | `onprem/guardrail.py` | An on-prem prompt / response screening backend (R1) |
| `PIIRedactionPort` | `onprem/redaction.py` | An on-prem PII de-identifier, driven by the same `pii-kit` rows (R1, P-04) |
| `AuditSinkPort` | `onprem/audit.py` | An on-prem immutable (WORM) audit store (R2) |
| `ObservabilityTracerPort` | `onprem/tracer.py` | An on-prem tracing backend (a no-op is acceptable) |
| `EvaluationGatePort` | `onprem/evaluation.py` | An on-prem eval backend and promotion gate (R5) |
| `AgentRegistryPort` | `onprem/registry_agent.py` | An on-prem A2A agent catalog (R4) |
| `ToolCatalogPort` | `onprem/tool_catalog.py` | An on-prem governed MCP tool catalog (R4) |
| `IdentityPort` | `onprem/identity.py` | Your on-prem IdP / SSO assertion verifier (drives the fail-closed tenant ACL) |

Nothing under `src/next_best_action/domain/` changes. The recommendation pipeline, the
deterministic candidate-filter, eligibility / suitability and ranking engines, the external
consent decision contract,
fail-closed cross-tenant authorization, the maker-checker policy, the citation mapping, the
serialization, and the prompts are all profile-agnostic. The agent wiring
(`src/next_best_action/agent/`) is unchanged too: the FunctionTool calls the same domain
services and resolves identity through the same `IdentityPort`, so it runs against whichever
adapter family the profile binds.

## Why this matters for a regulated buyer

A bank's or retailer's personalisation function cannot accept a workload it cannot exit,
especially one that touches customer data. Because the domain depends only on Protocols, the
regulator-facing properties (redact-before-everything, fail-closed tenancy, consent-gated
offers, cited recommendations, WORM audit) survive a platform change unchanged, and the
migration is a bounded, testable piece of work rather than a rewrite. The `local` family is the
proof that the off-cloud path already runs end to end today.
