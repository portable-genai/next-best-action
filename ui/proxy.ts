// The one place the per-request CSP nonce is minted and attached.
//
// Next 16 calls this file `proxy.ts` (it was `middleware.ts` up to Next 15); the export name
// follows. It runs before every response this console serves, which is the only layer that can
// express a value that differs per request.
//
// The CSP is set TWICE and both are load-bearing, in opposite directions:
//
//   * on the REQUEST headers, because that is where Next looks for the nonce it stamps onto
//     every `<script>` tag it renders. Without this the nonce in the response header names
//     nothing in the document, and `'strict-dynamic'` blocks every script.
//   * on the RESPONSE headers, because that is the policy the browser actually enforces.
//     Without this the nonce is stamped into the markup and never advertised.
//
// The request header name must be exactly `Content-Security-Policy`; Next matches on it.

import { type NextRequest, NextResponse } from "next/server";

import { contentSecurityPolicy, frameAncestors, frameOptions, generateNonce } from "./lib/csp.mjs";

export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const csp = contentSecurityPolicy(process.env, nonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);

  // The pre-CSP equivalent, only for the two policies it can express (see `frameOptions`).
  const legacy = frameOptions(frameAncestors(process.env));
  if (legacy) response.headers.set("X-Frame-Options", legacy);

  return response;
}

export const config = { matcher: "/:path*" };
