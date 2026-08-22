# Embedding and Identity: client integration guide (D5 next-best-action)

This guide explains how to drop the D5 Next-Best-Action UI into a client's existing web app (or
run it standalone) with the user journey intact and secure single sign-on, and how the backend
enforces per-user identity server-side instead of trusting a client-supplied `actor`.

The single invariant, implemented today and preserved across every deployment shape: **the server
never trusts a client-asserted actor or ACL.** The API resolves a verified `Principal` from the
inbound transport itself, and that `Principal` supplies the audit actor and the entitlement
principals. There is no request-body field a caller can set to say who they are.

## 1. The two pieces

- **Backend** (`src/next_best_action/api/app.py`): FastAPI over the deterministic recommendation
  domain. Every route depends on `CurrentPrincipal`, so the audit actor comes from the active
  `IdentityPort` adapter, never from the body. It also emits the embedding-surface headers (CSP
  `frame-ancestors`, per-tenant CORS).
- **UI** (`ui/`): a thin Next.js console. It can mount under a reverse-proxy sub-path
  (`NEXT_PUBLIC_BASE_PATH`), hide its own chrome when embedded (`NEXT_PUBLIC_EMBED`), and emits
  its own full Content-Security-Policy including `frame-ancestors`
  (`NEXT_PUBLIC_FRAME_ANCESTORS`), because the document a browser frames is the Next.js document,
  not the API response. See Section 3e for the console's policy and where it is enforced.

## 2. Three deployment shapes

| Shape | When | Auth | CORS |
|-------|------|------|------|
| **Embedded, same-origin reverse proxy** | The client controls its edge and wants the agent inside its portal at, e.g., `portal.client.example/agent/*`. | Cloud IAP in front of the shared origin; the backend re-verifies the injected assertion. | None: the iframe is first-party. |
| **Standalone behind Cloud IAP** | No host app; the agent lives on its own URL. | Cloud IAP + Workforce Identity Federation for SSO from the client IdP; backend re-verifies. | Only if UI and API are on different origins (explicit allowlist). |
| **Local dev, no auth** | Demos, tests, offline development. | None: seeded dev personas, no IdP / AD / LDAP. | Localhost dev origins. |

`MKT_NBA_PROFILE` selects the identity source: `local` = seeded personas, `gcp` / `platform` =
verify the IAP assertion, `onprem` = the client's own IdP (fail-fast placeholder today). Unset
is not `local`: the seeded personas are an unauthenticated grant of a tenant identity, so they
are handed out only when the local profile was named deliberately, and every end-user route
answers 401 otherwise.

## 3. Shape A: embed via same-origin reverse proxy (implemented)

Serve the agent under your own origin at a sub-path, then drop an iframe pointing at that
same-origin path. Because the iframe is first-party, there are no third-party-cookie issues and no
CORS to configure. The client owns exactly two things: a proxy route and an iframe tag.

### 3a. Reverse-proxy `/agent/*` to the agent service

nginx:

```nginx
# On https://portal.client.example
location /agent/ {
    proxy_pass         http://agent-ui.internal:3000/;    # the Next.js UI
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
}

# The UI's API calls (NEXT_PUBLIC_API_BASE=/agent/api) resolve same-origin too:
location /agent/api/ {
    proxy_pass         http://agent-backend.internal:8104/;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    # IAP runs in front of this origin, so x-goog-iap-jwt-assertion is present on the
    # inbound request and forwarded through to the backend for re-verification.
}
```

If the parent app is itself Next.js, use `rewrites()` in its own config instead:

```js
// next.config.mjs of the PARENT app
const nextConfig = {
  async rewrites() {
    return [
      { source: "/agent/api/:path*", destination: "http://agent-backend.internal:8104/:path*" },
      { source: "/agent/:path*",     destination: "http://agent-ui.internal:3000/:path*" },
    ];
  },
};
export default nextConfig;
```

### 3b. Mount the UI under the sub-path and hide its chrome

```bash
# Environment for the agent UI (build-time)
NEXT_PUBLIC_BASE_PATH=/agent      # mount the UI (and assets) under the sub-path
NEXT_PUBLIC_API_BASE=/agent/api   # same-origin API calls (no CORS needed)
NEXT_PUBLIC_EMBED=1               # hide the UI's own header/nav chrome when embedded
```

### 3c. The iframe tag (host page)

```html
<!-- On https://portal.client.example, inside your existing page -->
<iframe
  src="/agent/"
  title="Next-Best-Action Agent"
  style="width:100%; height:800px; border:0;"
  loading="lazy">
</iframe>
```

Height caveat: give the iframe a sized container. In normal document flow `height:100%` collapses,
and there is no child-to-parent resize message today, so content-driven height cannot push it
taller. A fixed pixel height (or a host-side sized container) is the reliable option.

### 3d. Allow the parent origin to frame the UI

`frame-ancestors` is only honored on the HTTP response of the **document the browser actually
frames**. In this same-origin shape the framed document is served through your proxy, so both the
backend and the Next.js UI emit the policy. Set the allowlist in **both** places so the framed
document is covered regardless of which server answers:

```bash
# Backend (FastAPI middleware, api/app.py):
export MKT_NBA_FRAME_ANCESTORS="https://portal.client.example"
# multiple parents are space-separated, per the CSP grammar:
# export MKT_NBA_FRAME_ANCESTORS="https://portal.client.example https://admin.client.example"

# UI (Next.js proxy, ui/proxy.ts, policy built in ui/lib/csp.mjs):
export NEXT_PUBLIC_FRAME_ANCESTORS="https://portal.client.example"
```

The backend emits `X-Frame-Options` alongside the CSP for the two policies the legacy header can
express: `SAMEORIGIN` for `'self'` and `DENY` for `'none'`. It cannot express a multi-origin
allowlist, so none is sent there and the CSP directive governs that case alone.

`MKT_NBA_FRAME_ANCESTORS` is read in three states, because a variable you emptied is a
configuration and not an omission:

| State | Result |
|-------|--------|
| unset | `frame-ancestors 'self'` plus `X-Frame-Options: SAMEORIGIN` (the shipped default). |
| set and empty | `frame-ancestors 'none'` plus `X-Frame-Options: DENY`, and a warning is logged. Emptying the allowlist means nobody may frame this, so it tightens; it never inherits the unset default. |
| set to origins | Exactly those origins, whitespace normalised. |

Before this rule, an empty value went straight into the header, so the response carried
`frame-ancestors` with an empty directive that browsers discard as a parse error, and the
`X-Frame-Options` fallback was skipped as well: the clickjacking control disappeared with no
sign that it had.

`NEXT_PUBLIC_FRAME_ANCESTORS` is read the same three ways, by `frameAncestors()` in
`ui/lib/csp.mjs`. That is deliberate: the two halves of one embedding posture must not disagree,
and an operator who empties the allowlist to lock the surface down would otherwise get the
permissive default from Next and the restrictive one from FastAPI.

### 3e. The console's own Content-Security-Policy

A console that emits exactly one directive, `frame-ancestors`, has no policy worth the name. That is an anti-clickjacking
control and nothing else: there was no `default-src`, no `script-src`, no `object-src` and no
`base-uri`, so the framed document had no default-deny at all. It now serves a full policy, and
two facts about how it is built are load-bearing.

**One policy module, one emitter.** The policy is built once, in `ui/lib/csp.mjs`, and emitted
once, from `ui/proxy.ts`. `ui/next.config.mjs` deliberately carries NO
`Content-Security-Policy`: its `headers()` table is static, and a script nonce is per-request. If
both layers emitted a CSP the browser would intersect them and the stricter value would win per
directive, so the nonce-less static copy would block the very scripts the nonce exists to allow.
The static table keeps only what is genuinely static: `X-Content-Type-Options: nosniff` and
`Referrer-Policy: no-referrer`.

**The nonce and the rendering mode must agree.** `script-src` is
`'self' 'nonce-<per-request>' 'strict-dynamic'`. The nonce is not optional decoration: Next
serves its hydration bootstrap as an INLINE script carrying the Flight payload, so a bare
`script-src 'self'` blocks it, `__next_f` never fills, React never attaches, and the console
renders its controls as dead markup while the headers, the build and every test stay green.

The trap on the other side is worse. Next can only stamp a per-request nonce onto the scripts of
a DYNAMICALLY rendered route. A statically prerendered page was built before the nonce existed,
so it emits bare script tags while the header advertises a nonce, and `'strict-dynamic'` has
already switched off the `'self'` fallback that was at least loading the chunk scripts: adding a
nonce to a static route blocks strictly MORE than the unfixed policy did. Two things therefore
guard it:

- `app/layout.tsx` sets `export const dynamic = "force-dynamic"`, and `next.config.mjs` refuses
  to build or boot without it (`assertHydratableCsp`, evaluated at module scope).
- `ui/scripts/assert-hydratable.mjs` starts the BUILT server, fetches the served document, and
  asserts every `<script>` tag carries the nonce the response header advertises. A header
  assertion cannot see this failure, because the header is byte-identical in the working case and
  in the broken one. It runs last in `make ui-check` and as its own CI step.

`ui/proxy.ts` sets the policy on the REQUEST headers as well as the response, and both are
required: the request header is where Next reads the nonce it stamps into the markup, the
response header is what the browser enforces.

## 4. Shape B: standalone behind Cloud IAP (implemented)

When there is no host application, deploy the agent on its own URL:

1. Deploy backend and UI behind the same HTTPS load balancer and Cloud IAP.
2. Set `MKT_NBA_PROFILE=gcp` and `MKT_NBA_IAP_AUDIENCE` so the backend verifies the IAP assertion.
3. Point the UI at the backend with `NEXT_PUBLIC_API_BASE`. If UI and backend are on **different**
   origins, also set `MKT_NBA_CORS_ORIGINS` to the UI origin (explicit allowlist, never `"*"`):

   ```bash
   export MKT_NBA_CORS_ORIGINS="https://agent.client.example"
   export NEXT_PUBLIC_API_BASE="https://api.agent.client.example"
   ```

4. Share the URL with authorized users. IAP + Workforce Identity Federation gives SSO from the
   corporate IdP; the backend independently re-verifies the signed `x-goog-iap-jwt-assertion`
   (`adapters/gcp/iap_identity.py`), the defense that survives an edge bypass.

Leave `MKT_NBA_FRAME_ANCESTORS` at its `'self'` default: nothing should iframe a standalone deploy.

## 5. Shape C: run locally, no auth (implemented)

Local mode (`MKT_NBA_PROFILE=local`) runs the whole pipeline offline: SQLite-backed retrieval, a
deterministic recommendation / propensity store, a deterministic LLM, and **no IdP, AD, or LDAP**.
Identity is resolved from a small set of seeded dev personas (`adapters/local/identity.py`),
selected by an `X-Dev-Persona` request header, with the first persona as the default.

```bash
# Backend (repo root)
export MKT_NBA_PROFILE=local
make run-api                      # uvicorn on http://localhost:8104

# UI (in ./ui)
cp .env.local.example .env.local  # NEXT_PUBLIC_API_BASE defaults to http://localhost:8104
npm install && npm run dev        # http://localhost:3000
```

The UI fetches `GET /v1/personas` and sends the chosen id as `X-Dev-Persona`. The picker renders
only when `GET /healthz` reports `profile == "local"`. The seeded personas deliberately span
different entitlements and tenants, including a cross-tenant one, so per-user and per-tenant
authorization is demoable offline:

| Persona id | Subject | Tenant | Entitlement principals |
|-----------|---------|--------|------------------------|
| `analyst` | `demo.analyst@bank.example` | `demo-bank` | `group:nba-analyst`, `group:marketing` |
| `approver` | `demo.approver@bank.example` | `demo-bank` | `group:nba-analyst`, `group:marketing`, `group:nba-approver` |
| `auditor` | `demo.auditor@bank.example` | `demo-bank` | `group:audit` |
| `other-tenant` | `user@other-tenant.example` | `other-bank` | `group:nba-analyst` |

```bash
curl -s http://localhost:8104/v1/personas | jq .
curl -s -X POST http://localhost:8104/v1/recommend \
  -H 'Content-Type: application/json' -H 'X-Dev-Persona: auditor' \
  -d '{"customer_id":"cust-sg-bank-1","market":"SG","vertical":"banking"}' | jq .
```

In secure profiles `X-Dev-Persona` is ignored entirely (Section 6), so leaving persona-selection
code in the UI is harmless in production. `/v1/personas` returns an empty list outside `local`.

## 6. The identity contract

`get_principal` (`api/security.py`) builds a `RequestContext` from inbound headers only, asks the
active `IdentityPort` adapter to resolve a verified `Principal`, and maps any `IdentityError` to a
hard 401. `RecommendationService.recommend(...)` receives `actor=principal.actor` from that
verified `Principal`; the request body carries no `actor` field to discard. There is no path by
which a caller can assert who they are or what they may see.

The `Principal` (`domain/identity.py`) models everything enforcement needs: `subject` (the audit
actor), `principals` (entitlement groups/ACL), `tenant` (multi-tenant partition), `assurance`
(auth-strength hint), and `source` (which adapter resolved it).

Identity source per profile:

| Profile | Adapter | Behavior |
|---------|---------|----------|
| `local` | `LocalPersonaIdentityAdapter` | Seeded personas via `X-Dev-Persona`; unknown id is a 401; no IdP. |
| `gcp` / `platform` | `IapIdentityAdapter` | Verifies the IAP-injected signed assertion (signature, audience, issuer, expiry); `tenant` from `hd`; Google SDK imports are lazy so the SDK-free profiles stay import-clean. |
| `onprem` | `OnPremIdentityAdapter` | Fail-fast `NotImplementedError` placeholder for the client's own IdP (OIDC / SAML): an unverified identity is never accepted. |

Defense in depth: the edge (Cloud IAP / Apigee) authenticates at ingress, Hrz1 applies central
guardrail policy, and this backend re-validates and derives identity itself. Each layer assumes the
others may be bypassed; this is the seam that defeats actor spoofing and the confused-deputy risk.

## 7. Configuration reference

| Variable | Where | Default | Purpose |
|----------|-------|---------|---------|
| `MKT_NBA_PROFILE` | backend | (none) | Selects the adapter stack: `local` \| `gcp` \| `platform` \| `onprem`. Unset is refused, not `local`: no dev personas, no CORS dev origins. |
| `MKT_NBA_IAP_AUDIENCE` | backend | (unset) | Expected IAP audience (the protected resource path); required in secure mode. |
| `MKT_NBA_CORS_ORIGINS` | backend | dev localhost origins | Comma-separated per-tenant CORS allowlist; never `"*"`. Not needed for same-origin embedding. Set and empty denies every origin rather than falling back to the dev origins. |
| `MKT_NBA_FRAME_ANCESTORS` | backend | `'self'` | CSP `frame-ancestors` for the API responses; space-separated parent origins. Set and empty means `'none'`, not the default. |
| `NEXT_PUBLIC_API_BASE` | UI | `http://localhost:8104` | Backend base URL; set to the proxied sub-path (e.g. `/agent/api`) for same-origin embedding. |
| `NEXT_PUBLIC_BASE_PATH` | UI | (blank) | Mounts the UI and assets under a reverse-proxy sub-path; blank keeps standalone. |
| `NEXT_PUBLIC_EMBED` | UI | (unset) | `1` hides the UI's own header/chrome so the host owns it. |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | UI | `'self'` | CSP `frame-ancestors` for the Next.js-served UI document (the framed document). Read in the same three states as the backend variable: set and empty means `'none'`, not the default. |
| `X-Dev-Persona` | request header | (none) | Local profile only: selects the seeded dev persona. Ignored in secure profiles. |

## 8. Integration checklist

- [ ] Choose a shape (Section 2) and set `MKT_NBA_PROFILE` accordingly.
- [ ] Same-origin embed: add the reverse-proxy route, set `NEXT_PUBLIC_BASE_PATH`,
      `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_EMBED=1`, and the iframe tag with a sized container.
- [ ] Set `MKT_NBA_FRAME_ANCESTORS` (backend) and `NEXT_PUBLIC_FRAME_ANCESTORS` (UI) to the parent
      origin(s); leave both at `'self'` for standalone.
- [ ] Secure mode: put Cloud IAP in front, set `MKT_NBA_IAP_AUDIENCE`, and verify the backend
      rejects a request with no / bad assertion.
- [ ] Cross-origin standalone only: set `MKT_NBA_CORS_ORIGINS` to the UI origin (never `"*"`).
- [ ] Confirm no request body carries an `actor`: the verified `Principal` is the audit actor.

## 9. Security checklist

- [ ] The API discards any client-asserted actor/ACL; the audit actor comes from `Principal.actor`.
- [ ] `IdentityError` maps to 401; an unknown persona and a missing/invalid IAP assertion both 401.
- [ ] `onprem` fails closed (`NotImplementedError`), never returns an anonymous principal.
- [ ] CORS is an explicit allowlist, never `"*"`; methods limited to GET/POST/OPTIONS.
- [ ] `frame-ancestors` is set on the framed document (UI) and the API; `X-Frame-Options:
      SAMEORIGIN` only when the value is `'self'`.
- [ ] The console serves a full default-deny CSP from ONE place (`ui/proxy.ts`, built by
      `ui/lib/csp.mjs`); `next.config.mjs` emits no CSP of its own.
- [ ] `make ui-check` is green, `assert-hydratable` included: the served document's script tags
      carry the advertised nonce, so the page actually hydrates.
- [ ] Google SDK imports stay lazy so `local` / `onprem` import with no cloud SDK installed.
- [ ] The IAP assertion is never logged.

## 10. Further layers (out of scope for this slice)

This slice implements the same-origin embed, the standalone-behind-IAP shape, and local no-auth
personas. The following hardening layers are documented but not built here, and mirror the fuller
reference implementation in `cdd-sow-research` (see its `docs/embedding-and-identity.md`):

- **Cross-origin embedding without a proxy** (a host-IdP bearer token verified against the client's
  JWKS, a versioned loader / web component, and a `postMessage` host-to-iframe contract) for hosts
  that can run neither a reverse proxy nor IAP/WIF.
- **Launch-in-new-tab (OIDC login)** as the simplest portable option, with its own session cookie
  and `401 -> /auth/login` flow.
- **Per-hop OAuth2 token exchange (OBO)** plus **Workload Identity Federation** and **mTLS** to the
  Hrz platform services, so a token leaked from the frame cannot be replayed elsewhere.
- **Step-up / DPoP** (acr/amr) for high-value actions, per-tenant fail-closed ACL partitioning, and
  Trusted Types on the bundles.

Each of these fits behind the same `IdentityPort` seam by configuration, with no domain change.
