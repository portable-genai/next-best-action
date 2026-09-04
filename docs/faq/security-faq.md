# Security FAQ

For an application-security team reviewing this repo before adopting it as a base. Answers
reflect the current code. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md),
[`docs/embedding-and-identity.md`](../embedding-and-identity.md).

### How is a request authenticated? Can a client spoof its identity?

No. Identity is resolved **server-side** from the transport context by an `IdentityPort`
adapter (`api/security.py` -> `IdentityPort.resolve`), never from the request body. The
request schema (`api/schemas.py`, `RecommendRequestModel`) carries no `actor` field, and any
client-asserted actor or ACL is discarded. Every route depends on a verified
`CurrentPrincipal`, and the audit actor comes from that principal. Per profile: `local` =
seeded dev personas (no IdP, offline only), `gcp` / `platform` = the Cloud IAP-injected
signed assertion (`MKT_NBA_IAP_AUDIENCE`), `onprem` = a client-IdP placeholder. An
unresolved identity is a 401.

### How is object-level authorization (multi-tenant isolation) enforced?

`Customer.tenant` partitions every customer, and `recommendation_service` runs a fail-closed
deny **immediately after the customer fetch**, before any offer is built, ranked or audited:
a customer whose tenant does not match the verified principal is refused. It is mapped to
HTTP **403, not 404**, so the response does not confirm the customer exists. `recommend()`
takes the verified `Principal`, not a free-text actor. A cross-tenant denial test proves the
seeded `other-bank` persona is refused `demo-bank` customers, red-before at both the domain
and HTTP layers.

### How is customer PII kept away from the model, spans and audit?

Redact-before-everything at **both boundaries**: the orchestrator calls the redaction port on
the raw text before `guardrail.screen`, so PII never reaches the model, and the ADK agent's
model-boundary callbacks (`agent/callbacks.py`) independently redact (DLP) then screen (Model
Armor) then audit (WORM) on every prompt and response, with span content capture disabled by
default. Audit writes go through a pseudonymizer: the internal customer key is hashed to
`cust#<12hex>` (including consent-citation source ids that embedded it) and national ids /
email / phone are masked, so the WORM sink holds only already-redacted `redacted_prompt` /
`redacted_response` fields. The national-identifier detectors come from the shared, versioned
**`pii-kit`** package, pinned to an exact commit in the lockfiles and read by the local
regex redactor, the GCP DLP custom info types and the eval leak check from one source.

### What about the service-to-service calls in the `platform` profile?

The outbound S2S path (`adapters/platform/_s2s.py`) attaches a bearer credential and enforces
an https-only base-URL check outside loopback. The two live outbound calls, the `model-quality-gate` eval
client (`remote_evaluation.py`, the shared `PromotionGateClient`) and the `human-review-console` review router
(the shared `review-kit` client), both carry the S2S bearer; the remaining platform
delegates are phase stubs. The receiving platform services own verification.

### Is the demo/dev server safe? Does anything bind 0.0.0.0 by default?

Under the `local` profile the Makefile binds the API to **loopback** (`API_HOST ?= 127.0.0.1`).
The stdlib demo server (`scripts/demo_server.py`) is clearly dev-only and offline. CORS never
uses `*`: the allowlist is explicit (`MKT_NBA_CORS_ORIGINS`), the dev-origin fallback and the
`X-Dev-Persona` header are **local-profile-only**, so a secure deploy that forgets to set
origins trusts nothing cross-origin.

### What HTTP security headers are set?

Both the API middleware and `ui/next.config.mjs` emit CSP `frame-ancestors` (plus a
conditional `X-Frame-Options`) for the embedding surface. Being honest about the gap: the rest
of the baseline (`X-Content-Type-Options: nosniff`, `Referrer-Policy`, HSTS on secure
profiles, a full `default-src 'self'` CSP with scoped `connect-src`) is **not yet** emitted on
either surface, and is tracked as an open item (audit check C6, PARTIAL) in
[`docs/practices-audit.md`](../practices-audit.md).

### How tamper-evident is the audit trail? What are its limits?

The `local` audit store wraps the shared `hex_service_kit.audit.HashChainedAuditLog`: a
SHA-256 hash chain with SQLite `UPDATE` / `DELETE` triggers enforcing append-only, JSONL
export / restore, and a `verify_chain()` that catches in-place edits and interior deletions.
The module docstring states its honest limits (a chain carrying no secret cannot alone detect
tail truncation or a full rewrite). In production the `gcp` profile uses a locked WORM bucket
(`retention_days: 2557`, ~7 years) which provides non-rewritability itself. This repo does not
*replace* the platform audit system (`agent-observability`); see [features-faq.md](features-faq.md).

### Supply chain: are dependencies pinned and scanned?

Yes. Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`, py3.12) are
installed in CI and the Docker build; the base image is pinned by digest; GitHub Actions are
SHA-pinned; `dependabot.yml` proposes bumps; and a CI job runs `pip-audit` (on the lockfiles)
and `npm audit` (on the UI). `ruff` is pinned exactly. The shared commons packages
(`hex-service-kit`, `agent-eval-kit`, `pii-kit`, `review-kit`) are pinned by tag and
resolved to exact SHAs in the lockfiles.

### Where are secrets? Are any committed?

No secret values are in the repo. `config/settings.yaml` names only the env vars holding
secrets (`*_env` / `${VAR}`); values are read at construction time and never logged. A
literal-secret grep over `config/` is clean. The seed customers, offers and consent records
are obviously-fictional.

### What is explicitly out of scope / a residual risk?

- The full security-header baseline is not yet on either surface (C6, PARTIAL).
- The hash chain needs the external anchor (or the WORM bucket) to resist truncation.
- The `platform` delegates other than the eval client and review router are phase stubs.
- This is a reference build: run your own pen-test, threat model, and model-risk review
  before any live-data deployment (stated throughout the docs).
