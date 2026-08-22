# Features FAQ

For product, compliance, and delivery teams: what this agent does per customer, what is
deterministic vs LLM, and where its responsibilities **stop** and a sibling catalog system
takes over. Cross-references: [`README.md`](../../README.md), [`DEMO.md`](../../DEMO.md),
[`SPEC.md`](../../SPEC.md).

### What does Mkt5 actually produce?

A ranked, fully cited **RecommendationSet** for one customer (banking) or shopper (online
retail): which offer to surface, on which channel, and why. From the customer, the offer
catalog and the propensity signals it produces an ordered list of eligible, consented
offers, each recommendation carrying its evidence as `Citation`s (the offer, the propensity
signal, the Mkt6 consent decision, the eligibility rules that fired) and a short "why recommended"
explanation, with a WORM audit event for the whole interaction. It is generic and APAC: the
active `vertical` (banking / online_retail) and `market` (JP / AU / SG) are settings, not
branches.

### What is deterministic vs done by the LLM?

The consequential decisions are **deterministic and replayable** (pure stdlib,
unit-tested): candidate filtering (`candidate_service.py`), eligibility / suitability
(`eligibility_service.py`), and the `propensity x value` ranking (`ranking_service.py`). Mkt6's
consent decision is deterministic and cited but remains behind `ConsentPort`, so it is not
reimplemented here. The LLM only **explains** the
already-fixed ranking; it never chooses, scores, or reorders offers. An auditor can recompute
the exact recommendation order from the same inputs without the model. An empty candidate set
raises `NoCandidatesError` rather than letting the model invent an ungrounded offer.

### Is anything auto-actioned?

No. Every `RecommendationSet` sets `requires_human_review=True` (maker-checker) and its audit
decision is `ESCALATED`; the agent proposes and a qualified operator disposes. Consent-
suppressed offers are never recommendable in the first place, so a human never sees an offer
the customer has not consented to on that channel.

### How does consent work?

Mkt5 asks the Mkt6 consent and preference store for every candidate channel through the pinned
`consent-preference-kit` contract. An absent, malformed, or unavailable answer suppresses the
offer; there is no BigQuery consent fallback. Local uses fictional consent rows behind the same
port and wire types, so the offline demo exercises the real boundary without a network call.

### Which capabilities does this repo own vs integrate from the catalog?

This is one system in a catalog of composable GRC systems. It **owns** the per-customer
next-best-action domain logic and its cited outputs. It **integrates** (via the `platform`
profile's HTTP adapters) several cross-cutting concerns owned by sibling platform systems, do
not rebuild these in a fork:

| Concern | Owned by (catalog id / repo) | Mkt5's role |
|---|---|---|
| Runtime guardrail: PII redaction, prompt-injection / jailbreak defense | **Hrz1** `agent-guardrail-gateway` | consumes it on every recommendation (input + output screen) |
| Governed RAG / offer + policy knowledge base with citations | **Hrz2** `enterprise-knowledge-base` | retrieves grounded offer / policy context from it |
| Agent registry, versioning, identity, entitlements | **Hrz3** `agent-registry` | publishes its A2A AgentCard for discovery |
| AI-quality / eval / model-risk promotion gate | **Hrz4** `model-quality-gate` | its eval metrics gate promotion; the offline gate mirrors it |
| Observability + immutable WORM prompt/response audit | **Hrz5** `agent-observability` | writes audit events to it; traces spans through it |
| Human-review / maker-checker console | **Hrz7** `human-review-console` | routes every escalated recommendation to it (rule R8) |
| Financial-promotions / marketing-compliance governance | **Mkt6** `marketing-compliance-gate` | asks its consent service through the versioned client contract on every customer-facing candidate (rule R7) |
| On-prem, CPU-only DLP scrub before egress | **Rsk6** `onprem-dlp` | the sovereign-DLP option behind the redaction port |

So the guardrail, knowledge base, audit sink, eval platform, human-review console and
marketing-compliance governor are *dependencies*, not features of this repo.

### How does this relate to the other marketing systems in the catalog?

Mkt5 is the **only per-customer** marketing system, so its data-protection, tenancy and
consent controls are load-bearing. The broader-audience marketing repos handle no customer
PII and are a different job: **Mkt1** market intelligence / competitor analysis, **Mkt2**
campaign planning and budget allocation, **Mkt3** brand-safe creative studio, **Mkt4**
performance marketing and attribution, and **Mkt6** marketing-compliance / financial-
promotions governance (which Mkt5 consumes). Check
[the organization's repository index](https://github.com/portable-genai) before building a
capability that may already have a home.

### Can I use this for a non-banking recommendation product?

Yes, that is the point of the core / vertical split. The reusable core (citations,
grounding, the three deterministic engines, consent port, audit, eval, maker-checker) transfers to retail
affinity, telecom upsell, insurance next-best-offer, and similar per-customer surfaces. You
replace the offer / customer models and the seed and retune the ranking and consent policy.
See [`docs/ADOPTING.md`](../ADOPTING.md) and [adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` runs the offline recommend flow and renders the static, audit-first HTML panels
(`scripts/out/`); `make demo-server` is a live, presenter-controlled offline server.
Everything runs on synthetic, fictional customers and offers with no cloud and no API key.
