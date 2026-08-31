import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ProvenanceBanner } from "./ProvenanceBanner";
import "./globals.css";

// Required by the nonce CSP, not a performance preference. `proxy.ts` mints a per-request script
// nonce, and Next can only stamp it onto the script tags of a DYNAMICALLY rendered route. A
// statically prerendered page is built before the nonce exists, so it emits bare script tags
// while the header advertises one, and `'strict-dynamic'` has already switched off the `'self'`
// fallback that was loading them: the page would hydrate LESS than before the CSP was fixed.
// `next.config.mjs` refuses to build or boot without this line.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Next-Best-Action",
  description:
    "Cited next-best-action recommendations from deterministic eligibility, consent and ranking, generic across banking and online retail and the JP/AU/SG markets.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // EMBED mode: the host page owns the chrome, so drop our app header/branding wrapper and
  // let the host size the frame. Standalone keeps the full-height app shell.
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  return (
    <html lang="en">
      <body className={embed ? undefined : "min-h-screen"}>
        <ProvenanceBanner />
        {embed ? (
          children
        ) : (
          <>
            <header className="border-b border-ink-200 bg-white">
              <div className="mx-auto max-w-6xl px-6 py-4">
                <h1 className="text-lg font-semibold text-ink-900">
                  Next-Best-Action: Recommendations and Cross-Sell
                </h1>
                <p className="text-sm text-ink-500">
                  Cited next-best-action recommendations · JP / AU / SG · synthetic data is
                  fictional
                </p>
              </div>
            </header>
            {children}
          </>
        )}
      </body>
    </html>
  );
}
