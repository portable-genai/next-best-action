"""The GCP adapter family must IMPORT and CONSTRUCT with no google-cloud-* installed.

The lazy-import contract: importing a gcp adapter module and constructing the adapter must
not pull in any Google Cloud SDK at module top level (the SDKs live behind method-body
imports). This is what lets the local / on-prem / test profile install with `[dev]` only and
still satisfy the contract test over the gcp bindings' structural shape.
"""

from __future__ import annotations

import importlib

import pytest

from next_best_action.config import Settings

GCP_ADAPTERS = [
    ("next_best_action.adapters.gcp.recommendation", "VertexRecommendationAdapter"),
    ("next_best_action.adapters.gcp.gemini_llm", "GeminiLLMAdapter"),
    ("next_best_action.adapters.gcp.file_search_kb", "FileSearchKnowledgeBaseAdapter"),
    ("next_best_action.adapters.gcp.model_armor_guardrail", "ModelArmorGuardrailAdapter"),
    ("next_best_action.adapters.gcp.cloud_logging_audit", "CloudLoggingAuditAdapter"),
    ("next_best_action.adapters.gcp.cloud_trace_tracer", "CloudTraceTracerAdapter"),
    ("next_best_action.adapters.gcp.genai_eval", "GenAiEvalAdapter"),
    ("next_best_action.adapters.gcp.a2a_registry", "A2ARegistryAdapter"),
    ("next_best_action.adapters.gcp.mcp_tool_catalog", "McpToolCatalogAdapter"),
]


@pytest.fixture
def settings() -> Settings:
    return Settings.load("config/settings.yaml")


@pytest.mark.parametrize(("module_path", "class_name"), GCP_ADAPTERS)
def test_gcp_adapter_imports_and_constructs(module_path: str, class_name: str, settings: Settings):
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls(settings)
    assert instance is not None


def test_region_validation_rejects_unconfigured_region(settings: Settings):
    from next_best_action.adapters.gcp._region import resolve_region
    from next_best_action.domain.errors import UnsupportedMarketError

    bad = Settings(
        project_id=settings.project_id,
        region="europe-west1",  # not in the JP/AU/SG allow-list
        profile="gcp",
        markets=settings.markets,
        adapters=settings.adapters,
    )
    with pytest.raises(UnsupportedMarketError):
        resolve_region(bad)


def test_region_validation_accepts_configured_region(settings: Settings):
    from next_best_action.adapters.gcp._region import resolve_region

    assert resolve_region(settings) in {
        "asia-northeast1",
        "australia-southeast1",
        "asia-southeast1",
    }
