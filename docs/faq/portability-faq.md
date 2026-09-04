# Portability FAQ

For architecture, cloud-governance, and exit-planning teams. The claim this repo makes is
"no vendor lock-in" (General Principle P-02 / P-12), enforced by the hexagon and the contract
tests rather than only asserted. Cross-references:
[`ARCHITECTURE.md`](../../ARCHITECTURE.md), [`docs/onprem-migration.md`](../onprem-migration.md),
[`DEMO.md`](../../DEMO.md).

### What does "portable" actually mean here?

Three axes, each with a rehearsed exit: **compute** (the whole stack migrates by a one-line
profile change, no domain edits), **data** (the audit trail exports in an open, documented
format and reloads elsewhere with the hash chain re-verified), and **experience / identity**
(identity resolves across hosts by an adapter swap, not a rewrite).

### How does the profile switch work?

The pure-domain core speaks only to `typing.Protocol` **ports**; four **adapter families**
implement them, and `config/settings.yaml` binds one adapter per port per profile. Setting
`MKT_NBA_PROFILE` (or `profile:` in the settings) rebinds the entire stack:

- `local`: a WORKING offline stack (deterministic recommendation / propensity store, SQLite
  FTS5 corpus, deterministic LLM, regex redaction, hash-chained audit). No Google Cloud SDK.
  The default for dev / test / CI.
- `gcp`: real managed services (Vertex AI recommendations + propensity + BigQuery, Gemini,
  File Search, Model Armor, Cloud DLP, Cloud Logging WORM, Cloud Trace, Gen AI Evals).
- `platform`: thin HTTP clients delegating to the sibling horizontal-platform and
  marketing services.
- `onprem`: placeholder stubs that still satisfy every Protocol (the sovereign-exit target);
  a primary CLI command exits 2 by design.

No `domain/` code changes across any of these. The contract test
(`tests/contract/test_port_parity.py`) proves both `local` and `onprem` construct and satisfy
every port with a single `Settings` arg and no cloud SDK installed, and
`test_behavioral_parity.py` proves the `local` adapters are byte-identical across reruns while
the `onprem` and scaffolded `platform` placeholders fail fast (`NotImplementedError`) rather
than returning a silent wrong answer.

### How do we get our data out?

The `local` audit trail (`adapters/local/audit.py`, wrapping
`hex_service_kit.audit.HashChainedAuditLog`) exports to JSON Lines and reloads into a fresh
store with the hash chain re-verified (`verify_chain()`). The exit story for the audit trail
is "copy the JSONL file", not "migrate a product". Domain objects (recommendations, offers,
citations) serialize to plain JSON via `to_jsonable` (the shared `hex-service-kit`
serialization), the same walker the platform HTTP clients use, so evidence rehydrates without
a proprietary format.

### Is on-prem / sovereign deployment real or aspirational?

The `onprem` adapters are deliberate fail-fast placeholders (they raise `NotImplementedError`)
that nonetheless satisfy every Protocol and construct with a single `Settings` arg, so the
*interface contract* for a sovereign migration is proven and enforced by CI today. The actual
on-prem implementations are the migration work, scoped in
[`docs/onprem-migration.md`](../onprem-migration.md). The sovereign-DLP option behind the
redaction port is the sibling `onprem-dlp` (CPU-only, on-prem scrub).

### Does residency compromise portability?

No: residency is a deploy-time pin (the per-market region, Org Policy resource-location
allowlist, CMEK, VPC-SC), and portability is the ability to change *where* the stack runs by
configuration. They are orthogonal. Each market's region is validated to fail fast, and a
second market or region is a config + tfvars change, not a fork.

### Is the portability claim executable end to end?

Partly, and this repo is honest about the gap. The profile swap and port parity are proven by
the contract and behavioral-parity tests, and the audit export / reload round-trips through
`verify_chain()`. What does **not** yet exist is a single `scripts/portability_demo.py` that
runs the whole tour (profile swap plus export / reload plus identity swap) behind one gating
exit code; that executable proof is tracked as an open item (audit check F3, FAIL) in
[`docs/practices-audit.md`](../practices-audit.md). Until then, the property is demonstrated by
the test suite rather than a one-command script.
