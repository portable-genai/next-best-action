"""Domain layer — pure, framework-free models, errors and deterministic engines.

The heart of the hexagon. No Google Cloud / Vertex AI / FastAPI imports anywhere in this package:
candidate filtering, eligibility, and ranking are deterministic; consent is obtained through
marketing-compliance-gate's versioned decision contract. The orchestrator decides everything
consequential, and the LLM only explains.
"""
