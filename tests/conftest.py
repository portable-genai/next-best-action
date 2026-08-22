"""Shared test fixtures.

The unit tests for the deterministic engines are pure (they construct domain objects
directly). The orchestrator / pipeline tests use the local SDK-free adapters wired through
an in-memory container so the whole suite runs offline with no Google Cloud SDK.
"""

from __future__ import annotations

import pytest

from next_best_action.config import Container, LocalSettings, Settings

CONFIG_PATH = "config/settings.yaml"

#: A loopback peer for every API test. The app-object exposure guard refuses the
#: unauthenticated local posture to any other peer, and ``TestClient``'s default peer is the
#: literal host ``"testclient"``, which is not loopback. See
#: ``tests/unit/test_serving_path_exposure.py``.
LOOPBACK_PEER = ("127.0.0.1", 50000)


def _settings(profile: str = "local") -> Settings:
    base = Settings.load(CONFIG_PATH)
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile=profile,
        vertical=base.vertical,
        market=base.market,
        models=base.models,
        recommendation=base.recommendation,
        knowledge_base=base.knowledge_base,
        model_armor=base.model_armor,
        logging=base.logging,
        agent_engine=base.agent_engine,
        ranking=base.ranking,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        markets=base.markets,
        adapters=base.adapters,
    )


@pytest.fixture
def local_settings() -> Settings:
    return _settings("local")


@pytest.fixture
def local_container(local_settings: Settings) -> Container:
    return Container(local_settings)
