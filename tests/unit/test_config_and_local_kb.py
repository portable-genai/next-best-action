"""Tests for config loading, market profiles and the local SQLite FTS5 corpus."""

from __future__ import annotations

from next_best_action.config import Container, Settings
from next_best_action.domain.models import Market, RetrievalQuery, Vertical


def test_market_profiles_resolve_residency_regions():
    settings = Settings.load("config/settings.yaml")
    assert settings.market_profile(Market.JP).region == "asia-northeast1"
    assert settings.market_profile(Market.AU).region == "australia-southeast1"
    assert settings.market_profile(Market.SG).region == "asia-southeast1"


def test_jp_is_bilingual_au_sg_english():
    settings = Settings.load("config/settings.yaml")
    assert settings.market_profile(Market.JP).locales == ("ja", "en")
    assert settings.market_profile(Market.AU).locales == ("en",)
    assert settings.market_profile(Market.SG).locales == ("en",)


def test_active_vertical_and_market_accessors():
    settings = Settings.load("config/settings.yaml")
    assert settings.active_vertical in (Vertical.BANKING, Vertical.ONLINE_RETAIL)
    assert settings.active_market in (Market.JP, Market.AU, Market.SG)


def test_local_kb_returns_scoped_passages(local_container: Container):
    kb = local_container.knowledge_base
    results = kb.search(
        RetrievalQuery(text="offer", market=Market.SG, vertical=Vertical.BANKING, top_k=5)
    )
    assert results
    for p in results:
        assert "market:SG" in p.tags
        assert "vertical:banking" in p.tags
        assert p.citation.source_id


def test_local_kb_handles_punctuation_query(local_container: Container):
    kb = local_container.knowledge_base
    # Punctuation must not trip an FTS5 syntax error.
    results = kb.search(RetrievalQuery(text="savings & fees!!! ???", top_k=3))
    assert isinstance(results, list)


def test_container_binds_every_port(local_container: Container):
    assert local_container.recommendation is not None
    assert local_container.knowledge_base is not None
    assert local_container.llm is not None
    assert local_container.guardrail is not None
    assert local_container.audit is not None
    assert local_container.tracer is not None
    assert local_container.evaluation is not None
    assert local_container.agent_registry is not None
    assert local_container.tool_catalog is not None
