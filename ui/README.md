# Mkt5 Next-Best-Action: Demo UI

A thin demo console for **Mkt5**, the Next-Best-Action: Recommendations and Cross-Sell system.
It is a thin presentation layer over the Mkt5 FastAPI backend: it ranks the next-best-action
for a customer (banking) or shopper (online retail) in a chosen market and vertical, and
renders the audit-first result (the ranked, cited recommendations with propensity / value
score bars and the LLM "why recommended" explanation, plus the offers suppressed for
ineligibility or missing consent) with the maker-checker "human review required" banner. It
never bypasses the guardrail or the review gate: it only shows what the backend returns.

Built with **Next.js (App Router) + TypeScript + Tailwind**. Dependencies are kept minimal:
`next`, `react`, `react-dom`, `tailwindcss`, `postcss`, `autoprefixer`, `typescript`, and the
`@types` packages, nothing else.

## Generic and APAC

The market selector covers **Japan / Australia / Singapore** (each labelled with its
residency region), and the vertical selector covers **banking** and **online retail**. The
console is vertical-agnostic: it renders whatever the backend returns for the selected
market and vertical.

## Configure the backend

Nothing to configure to run against `make run-api`: `NEXT_PUBLIC_API_BASE` already
defaults to the Mkt5 API port 8104. Write the override yourself only when the API is
somewhere else, and write it before `npm run build`, because Next inlines every
`NEXT_PUBLIC_*` value at build time:

```bash
echo 'NEXT_PUBLIC_API_BASE=https://api.elsewhere.example' > .env.local
```

## Run

```bash
# 1. start the Mkt5 API (from the repo root)
MKT_NBA_PROFILE=local uvicorn next_best_action.api.app:app --port 8104

# 2. start the console
cd ui && npm install && npm run dev
```

Then open http://localhost:3000.

## Source map

| Path | What it owns |
|------|--------------|
| `app/` | The App Router pages. `layout.tsx` sets `export const dynamic = "force-dynamic"`, which the nonce CSP requires (see below). |
| `components/` | The audit-first result view: ranked cited recommendations, suppressed offers, the review banner. |
| `lib/api.ts`, `lib/types.ts` | The typed client for the Mkt5 API and the shapes it returns. |
| `lib/csp.mjs` | The Content-Security-Policy, built ONCE. Also `frameAncestors` (three-state, mirroring the backend), `generateNonce` and the build-time `assertHydratableCsp` refusal. |
| `proxy.ts` | The only emitter of the CSP. Mints a per-request nonce and sets the policy on both the request headers (where Next reads the nonce it stamps) and the response headers (what the browser enforces). |
| `next.config.mjs` | Base path, and the static-only headers (`nosniff`, `Referrer-Policy`). Emits NO CSP: two layers emitting one would be intersected by the browser and the stricter value would win per directive. |
| `scripts/assert-hydratable.mjs` | Starts the BUILT server and asserts the served document actually hydrates. |
| `tests/csp.test.mjs` | `node:test` cover for what a policy STRING can decide. Not sufficient on its own; the header is identical in the working and broken cases. |

## Gate

```bash
make ui-install   # npm ci, proves the lockfile still resolves
make ui-check     # tsc --noEmit, node:test, next build, assert-hydratable
```

`assert-hydratable` runs LAST, against the artefact the build just produced, and it is the only
check that can see the failure that matters. Everything cheaper has been fooled by it: the CSP
string was right, `tsc` was clean, the build succeeded and a screenshot looked like a working
console, while `script-src 'self'` blocked Next's inline hydration bootstrap so React never
attached and no control did anything. The check refuses to reason about the policy at all. It
fetches the document a browser would fetch and asserts that every directive is present and
non-empty, that the response advertises a nonce, and that every `<script>` tag carries that same
nonce.

If it fails saying the script tags do not carry the nonce, the route went back to being
statically prerendered: check that `app/layout.tsx` still sets `export const dynamic =
"force-dynamic"`. `next build` must print the route as `ƒ (Dynamic)`, never `○ (Static)`.
