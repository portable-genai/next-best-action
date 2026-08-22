"""Integration smoke tests (require live Google Cloud credentials; deselected by default).

Run with ``pytest -m integration`` in an environment that has the ``[gcp]`` extra installed
and Application Default Credentials configured for a project with Vertex AI, BigQuery,
File Search, Model Armor, Cloud Logging and the Gen AI evaluation service provisioned. CI
runs ``pytest -m 'not integration'`` so these never block the offline gate.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from next_best_action.adapters.gcp.recommendation import VertexRecommendationAdapter
from next_best_action.config import Settings
from next_best_action.domain.models import Market, Vertical

pytestmark = pytest.mark.integration


def test_gcp_container_builds() -> None:
    from next_best_action.config import Settings, build_container

    container = build_container(Settings.load("config/settings.yaml"))
    # Constructing the gcp container must not require credentials (lazy clients).
    assert container is not None


@pytest.mark.skipif(
    not os.environ.get("MKT_NBA_SMOKE_CUSTOMER"),
    reason="MKT_NBA_SMOKE_CUSTOMER is not set",
)
def test_managed_recommendation_inputs_map_from_bigquery_and_vertex() -> None:
    """Read one fictional smoke customer through the real managed adapter family."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        pytest.skip("GOOGLE_CLOUD_PROJECT is not set")
    settings = replace(
        Settings.load("config/settings.yaml"),
        project_id=project,
        profile="gcp",
        profile_explicit=True,
        market="SG",
        vertical="banking",
    )
    adapter = VertexRecommendationAdapter(settings)
    customer = adapter.customer(os.environ["MKT_NBA_SMOKE_CUSTOMER"], Market.SG, Vertical.BANKING)
    offers = adapter.catalog(Market.SG, Vertical.BANKING)
    rules = adapter.eligibility_rules(Market.SG, Vertical.BANKING)
    signals = adapter.propensity(customer, offers)

    assert customer.tenant and offers and rules
    assert len(signals) == len(offers)
    assert all(offer.citations for offer in offers)
    assert all(signal.citation for signal in signals)
