import { readFileSync } from "node:fs";

import { assertHydratableCsp } from "./lib/csp.mjs";

// Evaluated by BOTH `next build` and `next start`, so a console configured to mint a nonce it
// can never stamp refuses to build and refuses to boot, rather than serving dead markup that
// looks correct in a screenshot.
assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

/** @type {import('next').NextConfig} */
// NEXT_PUBLIC_BASE_PATH mounts the UI (and its assets) under a reverse-proxy sub-path
// (e.g. /agent) for same-origin embedding; blank keeps the standalone deployment unchanged.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  // `next dev` writes AGENTS.md and CLAUDE.md into this directory unless this is false; the
  // writer is node_modules/next/dist/server/lib/generate-agent-files.js. This repo's working
  // agreement is the AGENTS.md at its root and there is no tool-specific alias of it, so a
  // second one here is a second agreement to keep in step and CLAUDE.md is precisely the alias
  // the convention forbids. The generated prose also carries an em-dash, which the catalog's
  // house style forbids in shipped markdown. tests/unit/test_ui_agent_documents.py fails the
  // gate if this line goes away or if either file turns up on disk anyway.
  agentRules: false,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    // NO Content-Security-Policy here, deliberately. This table is static and a script nonce is
    // per-request, so the policy is built in `lib/csp.mjs` and emitted once from `proxy.ts`.
    // Emitting it here as well would hand the browser two policies to intersect, and the
    // stricter value wins per directive: the nonce-less copy would block the nonced bootstrap
    // and the console would render as dead markup again. Same reasoning for `X-Frame-Options`,
    // which must track `frame-ancestors` and is therefore set beside it.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
