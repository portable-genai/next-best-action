# Compliance FAQ

For compliance, MLRO, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle-to-control map
and the regulator crosswalk appendix), [`SPEC.md`](../../SPEC.md).

### Is this making marketing decisions autonomously?

No. It is a **decision-support** agent: every `RecommendationSet` requires human review
(maker-checker, P-06) and its audit decision is `ESCALATED`. The deterministic engines
produce a documented, replayable recommendation; a qualified operator disposes before any
offer is actioned. Consent-suppressed offers are never recommendable, so the escalation bar
only rises, never lowers, and nothing auto-executes.

### How is customer consent handled?

Mkt5 owns no consent store. It asks sibling **Mkt6** `marketing-compliance-gate` through the
pinned `consent-preference-kit` contract for every candidate channel. Missing, malformed, and
unavailable answers are refusals. The local profile uses obviously-fictional rows behind the
same port and types, while managed profiles refuse to start a decision without a configured
Mkt6 URL. This keeps one legal answer in production while preserving an offline demonstration.

### How is customer PII handled?

Redact-before-everything (P-04, R1): the orchestrator redacts before any model, index,
registry or audit call, and the ADK model-boundary callback redacts again. National-identifier
detection is **jurisdiction-driven** (`pii.jurisdictions`, `MKT_NBA_PII_JURISDICTIONS`) and
sourced from the shared, versioned **`pii-kit`** package (SG / JP / AU home-market rows,
checksum-validated where applicable), so a non-Singapore deployment scrubs and gates on its
own identifiers. That configuration fails closed: an empty jurisdiction set, or a code the
pack carries no rows for, is refused at load rather than quietly narrowing the redactor, the
DLP custom info types and the eval leak check to email and phone. The runtime guardrail / DLP
itself is the sibling **Hrz1** gateway; this repo consumes it rather than re-implementing it.

### How is the work auditable / reproducible?

Every recommendation writes an immutable, already-redacted WORM `AuditEvent` with the decision
and the citation set (P-07). Every recommendation carries source-and-signal `Citation`s
(P-10). The ranking and eligibility math is deterministic, so an auditor can recompute any
order or decision from the same inputs. The enterprise WORM audit system is **Hrz5**; the
in-repo hash-chained store is the offline / local stand-in (see
[security-faq.md](security-faq.md) for its exact tamper-evidence limits).

### What is the model-risk story?

An offline eval gate (`eval/run_eval.py`, `--mode smoke|gate`) scores ranking / eligibility
accuracy, consent-suppression correctness and PII safety against a golden set, failing the
build below threshold (P-08). The `review_safety >= 0.99` metric is a boolean maker-checker
invariant that cannot go falsely green, and `pii_safety >= 0.99` runs the production regex
redactor through the real container and is proven able to fail (with redaction disabled the
PII-bearing cases drop and the gate goes red). The enterprise promotion gate is the sibling
**Hrz4** system; this repo's gate mirrors its thresholds so merges are guarded locally, and
the shared `agent-eval-kit` `PromotionGateClient` (bundle `mkt5-nba`) refuses to run gate mode
outside `MKT_NBA_PROFILE=platform|gcp`. A fork must rebuild the golden set for its own catalog,
or the gate measures the wrong thing.

### Which regulators does this map to?

`COMPLIANCE.md` maps the internal P-01..P-13 / R1..R8 controls to concrete code, plus an
**adopter-owned regulator crosswalk appendix**. To add your regulator, copy the appendix table,
swap the regulator-reference column, and re-review with local counsel; the Mkt5-control column
is stable across regulators. At scale, the sibling control-mapping and compliance-advisory
systems generate and maintain these crosswalks; a large estate should integrate them rather
than hand-maintain the table.

### Is data residency enforced?

Yes, at deploy time: each market pins a single in-country region (JP to Tokyo, AU to Sydney,
SG to Singapore), validated to fail fast, with regional endpoints, a `gcp.resourceLocations`
Org Policy allowlist, CMEK bound per service, and a VPC-SC perimeter (P-03, P-09). Residency is
a deploy-time pin and is orthogonal to portability (a second market is a config + tfvars change,
not a fork). The one honest gap is a CI Terraform `fmt` / `validate` job (audit check D5,
PARTIAL).

### Can we run it against real customer data today?

Not without your own legal, security, and model-risk sign-off. Every seeded customer, offer and
consent record is obviously-fictional, and the docs state throughout that this is a reference
build. The adoption checklist ([`docs/ADOPTING.md`](../ADOPTING.md) section 6) lists the steps,
replace the seed, own the ranking / consent policy, wire your IdP, rebuild the eval golden set,
that must precede any live-data use.

### Which part of the customer lifecycle does it cover?

Per-customer next-best-action / cross-sell recommendation at the point of an offer decision,
across banking and online retail. Enterprise campaign planning (**Mkt2**), creative production
(**Mkt3**), performance attribution (**Mkt4**) and financial-promotions governance (**Mkt6**)
are adjacent catalog systems, not this repo's job. See [features-faq.md](features-faq.md) for
the boundary.
