"""Local deployment profile adapters — a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed Google
Cloud services) and ``onprem`` (fail-fast migration placeholders). Unlike ``onprem``, every
adapter here is a *real, deterministic* implementation that runs the whole next-best-action
pipeline end to end with **no Google Cloud, no API key, and no running emulators**:

* Recommendations + propensity (Vertex AI + BigQuery) -> a deterministic store over the
  seeded fictional data (customers, offer catalog, eligibility rules, consent, propensity),
  spanning banking AND online retail across JP / AU / SG.
* Offer / policy corpus / File Search (A2) -> a ``sqlite3`` **FTS5** index over the seeded
  passages (BM25 rank), market/vertical scoped.
* LLM (Gemini) -> a deterministic, schema-driven explainer (no model, no network).
* Guardrail (Model Armor) -> a heuristic that blocks prompt-injection / jailbreak text.
* Audit (Cloud Logging WORM) -> an append-only local store, read-back supported.
* Tracer (Cloud Trace) -> no-op spans.
* Agent registry (A3) / tool catalog (MCP) -> in-process stores.
* Evaluation (Gen AI eval / A4) -> delegates to the in-repo offline eval gate.

Everything is seedable so the test suite stays deterministic, and the default code path
imports **no google-cloud package at module top level**.
"""
