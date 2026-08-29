// Unit cover for the parts of the CSP a STRING can decide.
//
// These are NOT sufficient, and the reason is the whole point of `scripts/assert-hydratable.mjs`.
// Every assertion here passed on the half-configured console that shipped dead markup: the header
// is byte-identical whether or not the rendered document carries the nonce it advertises. Only a
// check that starts the built server and reads the emitted `<script>` tags can tell those two
// cases apart. These tests cover the policy's shape; that check covers whether it works.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  UnhydratableCspError,
  WildcardOriginError,
  assertHydratableCsp,
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
} from "../lib/csp.mjs";

// Every assertion below is about the policy a DEPLOYMENT serves, so every one of them names the
// environment it is asserting. `contentSecurityPolicy` widens `script-src` and `connect-src` on a
// development server and only there, and a test that left NODE_ENV unset would silently be
// checking the dev policy while claiming to pin the shipped one.
const PROD = { NODE_ENV: "production" };

/** Split a policy string into a directive map. */
function directives(csp) {
  return new Map(
    csp
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...value] = part.split(/\s+/);
        return [name, value.join(" ")];
      }),
  );
}

test("the policy carries every directive a default-deny needs", () => {
  const d = directives(contentSecurityPolicy(PROD, "n0nce"));
  for (const name of [
    "default-src",
    "base-uri",
    "form-action",
    "object-src",
    "script-src",
    "style-src",
    "img-src",
    "font-src",
    "connect-src",
    "frame-ancestors",
  ]) {
    assert.ok(d.has(name), `missing ${name}`);
  }
  assert.equal(d.get("object-src"), "'none'");
  assert.equal(d.get("base-uri"), "'self'");
});

test("no directive is ever emitted empty, in any of the three env states", () => {
  for (const env of [{}, { NEXT_PUBLIC_FRAME_ANCESTORS: "" }, { NEXT_PUBLIC_FRAME_ANCESTORS: "  " }]) {
    for (const nonce of [undefined, "n0nce"]) {
      for (const [name, value] of directives(contentSecurityPolicy({ ...PROD, ...env }, nonce))) {
        // An empty directive is a CSP parse error, which browsers DISCARD: the restriction
        // silently disappears instead of tightening.
        assert.notEqual(value, "", `${name} is empty for ${JSON.stringify(env)}`);
      }
    }
  }
});

test("script-src takes the nonce and strict-dynamic only when a nonce is supplied", () => {
  assert.equal(
    directives(contentSecurityPolicy(PROD, "abc123")).get("script-src"),
    "'self' 'nonce-abc123' 'strict-dynamic'",
  );
  assert.equal(directives(contentSecurityPolicy(PROD)).get("script-src"), "'self'");
});

test("frame-ancestors is three-state, mirroring the service", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), "'none'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "   " }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.example  https://sso.example" }),
    "https://portal.example https://sso.example",
  );
});

test("X-Frame-Options is sent only for the two policies it can express", () => {
  assert.equal(frameOptions("'self'"), "SAMEORIGIN");
  assert.equal(frameOptions("'none'"), "DENY");
  assert.equal(frameOptions("https://portal.example"), "");
});

test("connect-src widens to the API ORIGIN, not the full URL", () => {
  const d = directives(
    contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "https://api.example:8104/v1/recommend" }),
  );
  assert.equal(d.get("connect-src"), "'self' https://api.example:8104");
});

test("a rooted API base stays same-origin rather than being refused", () => {
  // A host portal mounting this console under its own route sets exactly this. Same-origin is
  // already covered by 'self', so it widens nothing, and refusing it answered 500 on a working
  // deployment. What must never happen is the value being dropped while it names a real origin,
  // which is the case below.
  assert.doesNotThrow(() => contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "/apps/x/api" }));
});

test("a protocol-relative API base is refused rather than read as same-origin", () => {
  assert.throws(
    () => contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "//api.example/v1" }),
    /must name its scheme/,
  );
});

test("an API base that is neither absolute nor rooted is refused", () => {
  assert.throws(
    () => contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "api.example/v1" }),
    /NEXT_PUBLIC_API_BASE/,
  );
});

test("nonces are unique and base64", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i += 1) {
    const nonce = generateNonce();
    assert.match(nonce, /^[A-Za-z0-9+/]+={0,2}$/);
    seen.add(nonce);
  }
  assert.equal(seen.size, 50);
});

test("a layout without force-dynamic is refused", () => {
  assert.throws(() => assertHydratableCsp("export const metadata = {};"), UnhydratableCspError);
  assert.doesNotThrow(() => assertHydratableCsp('export const dynamic = "force-dynamic";'));
});

test("a wildcard frame-ancestors is refused in every spelling a config can render", () => {
  // The FastAPI half already refuses these. This is the OTHER emitter, and it is the one a
  // browser honours for the document, so closing only the service side left the console
  // framable by any origin while every check stayed green.
  for (const wildcard of ["*", "'*'", "null", "*.*"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: wildcard }),
      WildcardOriginError,
      `${JSON.stringify(wildcard)} must be refused, not passed through to the header`,
    );
  }
  assert.throws(
    () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example *" }),
    WildcardOriginError,
    "a wildcard standing beside named origins is still a wildcard",
  );
  assert.throws(
    () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "*,https://portal.client.example" }),
    WildcardOriginError,
    "a comma is not CSP list syntax, so a comma-joined wildcard must still be seen",
  );
  // A HOST-SOURCE wildcard is the spelling an exact-token set misses, and CSP honours it: every
  // subdomain may frame the console, including one an attacker takes over or registers on a
  // user-content domain. A real origin never contains an asterisk, so refusing the character
  // outright turns away nothing a deployment could correctly hold.
  for (const hostSource of [
    "https://*.client.example",
    "*.client.example",
    "https://*",
    "https://portal.client.example https://*.evil.example",
  ]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: hostSource }),
      WildcardOriginError,
      `${JSON.stringify(hostSource)} is a host-source wildcard and must be refused`,
    );
  }
});

test("the policy the proxy actually serves refuses a wildcard too", () => {
  // `contentSecurityPolicy` is what `proxy.ts` puts on the document response. Refusing inside
  // the resolver alone would be theatre if this path could still build a policy around it.
  for (const wildcard of ["*", "'*'", "null", "*.*", "https://*.client.example"]) {
    assert.throws(
      () => contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_FRAME_ANCESTORS: wildcard }, "n0nce"),
      WildcardOriginError,
      `the served document policy must not carry frame-ancestors ${wildcard}`,
    );
  }
});

test("a legitimate named allowlist is unaffected by the wildcard refusal", () => {
  // A refusal that also refuses valid input is an outage, not a control.
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example" }),
    "https://portal.client.example",
  );
  assert.equal(
    frameAncestors({
      NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example https://intranet.client.example",
    }),
    "https://portal.client.example https://intranet.client.example",
  );
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'self'" }), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.match(
    contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example" }, "n"),
    /frame-ancestors https:\/\/portal\.client\.example/,
  );
});

test("the unset and emptied states are exactly what they were before wildcards were refused", () => {
  // Pinned so a later edit cannot drift them. THIS repo maps an emptied value to 'none' rather
  // than refusing it, mirroring its own FastAPI half; the wildcard case is an addition to that
  // behaviour, never a replacement for it, and 'none' is the one answer a wildcard is not.
  assert.equal(frameAncestors({}), "'self'");
  for (const blank of ["", "   ", "\t", "\n", " \t\n "]) {
    assert.equal(
      frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: blank }),
      "'none'",
      `blank value ${JSON.stringify(blank)} must still resolve to the lockdown value`,
    );
  }
  assert.equal(frameOptions("'none'"), "DENY");
});

test("'unsafe-eval' and the HMR websocket exist on the dev server and NOWHERE else", () => {
  // RED before the dev branch existed: `next dev` was served the production policy, so React
  // reported that eval is unavailable, `__next_f` never filled, and the console rendered its
  // controls as dead markup while the header, the type-check, the build and every other test
  // stayed green. Both relaxations are keyed off NODE_ENV alone, so `next build` and `next start`
  // cannot emit either one, and `scripts/assert-hydratable.mjs` re-proves that on the artefact.
  const dev = directives(contentSecurityPolicy({ NODE_ENV: "development" }, "n0nce"));
  assert.match(dev.get("script-src"), /'unsafe-eval'/);
  assert.match(dev.get("connect-src"), /ws: wss:/);

  for (const nonce of [undefined, "n0nce"]) {
    const policy = contentSecurityPolicy(PROD, nonce);
    assert.doesNotMatch(policy, /unsafe-eval/, `unsafe-eval reached production (nonce: ${nonce})`);
    assert.doesNotMatch(policy, /ws:/, `a websocket source reached production (nonce: ${nonce})`);
  }

  // The relaxation widens the two directives it names and nothing else: `'unsafe-inline'` is the
  // token an XSS actually needs in `script-src`, and it is absent in both modes.
  assert.equal(dev.get("default-src"), "'self'");
  assert.equal(dev.get("object-src"), "'none'");
  assert.doesNotMatch(dev.get("script-src"), /unsafe-inline/);
});
