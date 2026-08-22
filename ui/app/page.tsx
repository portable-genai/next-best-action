"use client";

import { useEffect, useState } from "react";
import { RecommendationView } from "@/components/RecommendationView";
import { api, API_BASE, ApiError, setDevPersona } from "@/lib/api";
import type { Health, Market, Persona, RecommendationSet, Vertical } from "@/lib/types";

const MARKETS: { value: Market; label: string }[] = [
  { value: "JP", label: "Japan (asia-northeast1)" },
  { value: "AU", label: "Australia (australia-southeast1)" },
  { value: "SG", label: "Singapore (asia-southeast1)" },
];
const VERTICALS: { value: Vertical; label: string }[] = [
  { value: "banking", label: "Banking" },
  { value: "online_retail", label: "Online retail" },
];

export default function Page() {
  const [customerId, setCustomerId] = useState("cust-sg-bank-1");
  const [market, setMarket] = useState<Market>("SG");
  const [vertical, setVertical] = useState<Vertical>("banking");
  const [result, setResult] = useState<RecommendationSet | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [persona, setPersona] = useState("");

  useEffect(() => {
    api.healthz().then(setHealth);
  }, []);

  // Demo identity: only the local profile runs with seeded dev personas (no IdP). Load
  // them and default-select the first, wiring it into the X-Dev-Persona header so the
  // backend resolves a verified Principal from the pick.
  useEffect(() => {
    if (health?.profile !== "local") return;
    api.listPersonas().then((list) => {
      setPersonas(list);
      if (list.length > 0) {
        setPersona(list[0].id);
        setDevPersona(list[0].id);
      }
    });
  }, [health?.profile]);

  function onPersonaChange(id: string) {
    setPersona(id);
    setDevPersona(id);
  }

  async function onRun() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.recommend({ customer_id: customerId, market, vertical });
      setResult(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-6xl gap-6 p-6">
      <aside className="w-80 shrink-0">
        <h1 className="text-base font-semibold">D5 Next-Best-Action</h1>
        <p className="mb-4 text-xs text-ink-500">
          Cited next-best-action recommendations from deterministic eligibility, consent and
          ranking, generic across banking and online retail and the JP/AU/SG markets.
        </p>

        <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
          <label className="mb-1 block text-xs font-semibold text-ink-600">Customer / shopper id</label>
          <input
            className="mb-3 w-full rounded-md border border-ink-200 px-2.5 py-1.5 text-sm"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
          />

          <label className="mb-1 block text-xs font-semibold text-ink-600">Market</label>
          <select
            className="mb-3 w-full rounded-md border border-ink-200 px-2.5 py-1.5 text-sm"
            value={market}
            onChange={(e) => setMarket(e.target.value as Market)}
          >
            {MARKETS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>

          <label className="mb-1 block text-xs font-semibold text-ink-600">Vertical</label>
          <select
            className="mb-3 w-full rounded-md border border-ink-200 px-2.5 py-1.5 text-sm"
            value={vertical}
            onChange={(e) => setVertical(e.target.value as Vertical)}
          >
            {VERTICALS.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>

          <button
            onClick={onRun}
            disabled={loading || !customerId.trim()}
            className="w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
          >
            {loading ? "Ranking…" : "Recommend next-best-action"}
          </button>

          <p className="mt-3 text-[11px] text-ink-400">
            Seed ids: cust-sg-bank-1, cust-jp-bank-1, cust-au-bank-1, cust-sg-retail-1,
            cust-jp-retail-1, cust-au-retail-1.
          </p>
        </div>

        {health?.profile === "local" && personas.length > 0 ? (
          <div className="mt-3 rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
            <label className="mb-1 block text-xs font-semibold text-ink-600">
              Demo identity
            </label>
            <select
              className="w-full rounded-md border border-ink-200 px-2.5 py-1.5 text-sm"
              value={persona}
              onChange={(e) => onPersonaChange(e.target.value)}
            >
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.id} — {p.subject} ({p.tenant})
                </option>
              ))}
            </select>
            <p className="mt-2 text-[11px] text-ink-400">
              Local profile only: no IdP. The chosen persona is sent as X-Dev-Persona and the
              backend resolves a verified identity from it (the client never asserts an actor).
            </p>
          </div>
        ) : null}

        <div className="mt-3 rounded-xl border border-ink-200 bg-white p-3 text-xs text-ink-500 shadow-panel">
          <div>
            API <span className="font-mono">{API_BASE}</span>
          </div>
          {health ? (
            <div className="mt-1">
              profile <b className="text-ink-700">{health.profile}</b> · status{" "}
              <b className="text-ink-700">{health.status}</b>
            </div>
          ) : (
            <div className="mt-1 text-amber-700">backend not reachable (start the API)</div>
          )}
        </div>
      </aside>

      <section className="min-w-0 flex-1">
        {error ? (
          <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {!result && !error ? (
          <div className="rounded-xl border border-dashed border-ink-200 bg-white p-10 text-center text-sm text-ink-400">
            Pick a customer, market and vertical, then rank the next-best-action.
          </div>
        ) : null}
        {result ? <RecommendationView result={result} /> : null}
      </section>
    </main>
  );
}
