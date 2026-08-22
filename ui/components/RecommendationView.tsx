import type { RecommendationSet } from "@/lib/types";
import { CitationList } from "./CitationList";

const MARKET_LABEL: Record<string, string> = {
  JP: "Japan",
  AU: "Australia",
  SG: "Singapore",
};
const VERTICAL_LABEL: Record<string, string> = {
  banking: "Banking",
  online_retail: "Online retail",
};

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-xl border border-ink-200 bg-white shadow-panel">
      <h2 className="border-b border-ink-100 px-4 py-2.5 text-[13px] font-semibold text-ink-800">
        {title}
      </h2>
      <div className="p-4">{children}</div>
    </section>
  );
}

function Bar({ value }: { value: number }) {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-28 overflow-hidden rounded-md border border-ink-200 bg-ink-100">
        <div
          className="h-full bg-gradient-to-r from-brand-500 to-brand-600"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-ink-500">{pct}%</span>
    </div>
  );
}

export function RecommendationView({ result }: { result: RecommendationSet }) {
  return (
    <div>
      <h1 className="text-lg font-semibold">Next-best-action — {result.customer_id}</h1>
      <p className="mb-4 text-[13px] text-ink-500">
        <span className="mr-1.5 inline-block rounded-full border border-brand-100 bg-brand-50 px-2.5 py-0.5 text-[11px] font-semibold text-brand-700">
          {MARKET_LABEL[result.market] ?? result.market}
        </span>
        <span className="mr-1.5 inline-block rounded-full border border-brand-100 bg-brand-50 px-2.5 py-0.5 text-[11px] font-semibold text-brand-700">
          {VERTICAL_LABEL[result.vertical] ?? result.vertical}
        </span>
        id <b className="text-ink-800">{result.id}</b>
      </p>

      {result.requires_human_review ? (
        <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
          HUMAN REVIEW REQUIRED — maker-checker gate. Do not surface these offers to the
          customer until a qualified operator signs off.
        </div>
      ) : null}

      <Panel title="Summary">
        <p className="leading-relaxed">{result.summary}</p>
      </Panel>

      <Panel title="Recommendations (ranked, deterministic)">
        {result.recommendations.length === 0 ? (
          <div className="text-xs text-ink-400">
            none — all candidates ineligible or consent-suppressed
          </div>
        ) : (
          result.recommendations.map((r, i) => (
            <div key={i} className="border-b border-ink-100 py-3 last:border-0">
              <div className="flex items-center gap-3">
                <span className="rounded bg-brand-600 px-1.5 text-[11px] font-bold text-white">
                  #{r.rank}
                </span>
                <div className="flex-1">
                  <b>{r.name}</b>{" "}
                  <span className="text-xs text-ink-400">
                    [{r.kind}] · channel {r.channel ?? "n/a"} · propensity{" "}
                    {r.propensity.toFixed(2)} · value {r.value_score.toFixed(2)}
                  </span>
                </div>
                <Bar value={r.score} />
              </div>
              {r.explanation ? (
                <p className="mt-1 text-[13px] text-ink-600">{r.explanation}</p>
              ) : null}
              <CitationList citations={r.citations} />
            </div>
          ))
        )}
      </Panel>

      {result.suppressed.length > 0 ? (
        <Panel title="Suppressed (ineligible)">
          {result.suppressed.map((e, i) => (
            <div key={i} className="border-b border-ink-100 py-2 last:border-0">
              <b>{e.offer_id}</b>
              <ul className="ml-4 list-disc text-xs text-ink-500">
                {e.reasons.map((reason, j) => (
                  <li key={j}>{reason}</li>
                ))}
              </ul>
            </div>
          ))}
        </Panel>
      ) : null}

      {result.consent_suppressed.length > 0 ? (
        <Panel title="Suppressed (consent)">
          {result.consent_suppressed.map((c, i) => (
            <div key={i} className="border-b border-ink-100 py-2 last:border-0">
              <b>{c.offer_id}</b>{" "}
              <span className="text-xs text-ink-500">{c.reason}</span>
            </div>
          ))}
        </Panel>
      ) : null}
    </div>
  );
}
