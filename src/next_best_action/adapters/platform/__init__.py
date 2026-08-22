"""Remote-platform adapters — thin HTTP clients to the shared A1-A5 platform services.

Used by the ``platform`` profile to reuse the shared Guardrail (A1), Knowledge Base (A2),
Agent Registry (A3), Quality gate (A4) and Observability/Audit (A5) services instead of the
standalone managed adapters. Each constructs cleanly with no Google Cloud SDK; the HTTP
bodies are wired in the platform phase.
"""
