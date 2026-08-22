"""Contract tests: the ``onprem`` and ``local`` adapters are structural parity of the ports.

For every port the catalog declares, this iterates the adapter map and, for both the
``onprem`` and ``local`` profiles, imports + constructs the bound class (which must build
cleanly with **no Google Cloud SDK** installed), then asserts:

  1. the constructed instance satisfies its runtime_checkable Protocol (isinstance), and
  2. every method/property the Protocol declares actually exists on the instance.

It additionally proves the two profiles' distinct contracts:

* ``onprem`` is the fail-fast migration target: every method raises ``NotImplementedError``
  (proven on a representative port), and
* ``local`` is a WORKING offline stack: the same ports construct and answer in-process.

This is the proof of the ports-and-adapters / no-lock-in promise: the on-prem migration
target and the offline local stack implement the exact same interface as the managed GCP
stack.
"""

from __future__ import annotations

import importlib
from typing import Protocol, get_type_hints

import pytest

from next_best_action import config, ports
from next_best_action.config import LocalSettings, Settings, instantiate

CONFIG_PATH = "config/settings.yaml"

PORT_PROTOCOLS: dict[str, type] = {
    "consent": ports.ConsentPort,
    "recommendation": ports.RecommendationPort,
    "knowledge_base": ports.KnowledgeBasePort,
    "llm": ports.LlmPort,
    "guardrail": ports.GuardrailPort,
    "redaction": ports.PIIRedactionPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "agent_registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
    "identity": ports.IdentityPort,
    "review_router": ports.ReviewRouterPort,
}

# Profiles whose adapters must construct + satisfy the Protocols with no GCP SDK.
SDK_FREE_PROFILES = ("onprem", "local")


def _settings(profile: str) -> Settings:
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


def _protocol_members(protocol: type) -> set[str]:
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    if not members:
        members |= set(get_type_hints(protocol).keys())
        for name in dir(protocol):
            if name.startswith("_"):
                continue
            members.add(name)
    return {m for m in members if not m.startswith("_")}


def test_port_protocols_matches_settings_adapters():
    """The hand-maintained PORT_PROTOCOLS map must equal the ports bound in settings.

    Without this, a fork that adds a port Protocol and binds it in config/settings.yaml but
    forgets the PORT_PROTOCOLS entry gets ZERO parity/constructor/onprem-binding enforcement
    with a green CI (silent drift). Set-equality here fails loudly on BOTH drift directions:
    a port bound in settings but missing from the map (so untested), and a port in the map
    with no settings binding (so unbindable).
    """
    settings = Settings.load(CONFIG_PATH)
    bound = set(settings.adapters)
    declared = set(PORT_PROTOCOLS)
    missing_from_map = bound - declared
    missing_from_settings = declared - bound
    assert not missing_from_map, (
        f"ports bound in settings.adapters but absent from PORT_PROTOCOLS "
        f"(so untested): {sorted(missing_from_map)}. Add them to the parity map."
    )
    assert not missing_from_settings, (
        f"ports in PORT_PROTOCOLS with no settings.adapters binding: "
        f"{sorted(missing_from_settings)}."
    )


def test_every_port_has_an_explicit_binding_for_every_profile():
    settings = Settings.load(CONFIG_PATH)
    for port_name in PORT_PROTOCOLS:
        binding = settings.adapters.get(port_name, {})
        missing = set(config.RUNTIME_PROFILES) - set(binding)
        assert not missing, f"port '{port_name}' has no explicit bindings for {sorted(missing)}"


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_satisfies_protocol(profile: str, port_name: str):
    settings = _settings(profile)
    protocol = PORT_PROTOCOLS[port_name]
    dotted = settings.adapters[port_name][profile]

    adapter = instantiate(dotted, settings)

    assert isinstance(adapter, protocol), (
        f"{dotted} does not structurally satisfy {protocol.__name__}"
    )

    members = _protocol_members(protocol)
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in members:
        assert member in declared, (
            f"{dotted} is missing port method/attr '{member}' of {protocol.__name__}"
        )


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_constructs_with_single_settings_arg(profile: str, port_name: str):
    """The build contract: every adapter is ``Adapter(settings: Settings)``."""
    settings = _settings(profile)
    dotted = settings.adapters[port_name][profile]
    module_path, _, class_name = dotted.partition(":")

    cls = getattr(importlib.import_module(module_path), class_name)
    instance = cls(settings)
    assert instance is not None


def test_onprem_recommendation_fails_fast():
    """The on-prem stubs are fail-fast: a representative port raises NotImplementedError."""
    from next_best_action.domain.models import Market, Vertical

    settings = _settings("onprem")
    adapter = instantiate(settings.adapters["recommendation"]["onprem"], settings)
    with pytest.raises(NotImplementedError):
        adapter.catalog(Market.SG, Vertical.BANKING)


def test_local_recommendation_returns_real_catalog():
    """The local stack is WORKING: the catalog returns real, cited offers offline."""
    from next_best_action.domain.models import Market, Vertical

    settings = _settings("local")
    adapter = instantiate(settings.adapters["recommendation"]["local"], settings)
    catalog = adapter.catalog(Market.SG, Vertical.BANKING)
    assert catalog, "local recommendation returned no offers for the seeded catalog"
    assert all(o.name for o in catalog)


def test_all_protocols_are_runtime_checkable():
    for protocol in PORT_PROTOCOLS.values():
        assert issubclass(protocol, Protocol)  # type: ignore[arg-type]
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{protocol.__name__} must be @runtime_checkable"
        )


def test_shared_types_are_the_commons_objects_not_local_look_alikes():
    """Object IDENTITY, which is the only assertion a hand-copied duplicate cannot satisfy.

    ``isinstance`` against a ``runtime_checkable`` Protocol passes for a copy: structural typing
    is exactly what a re-declared Protocol still satisfies, and that is how sixteen repositories
    drifted apart while every parity test stayed green. ``is`` does not pass for a copy. If
    anyone re-declares one of these locally, this test fails and says which.
    """
    import agent_eval_kit
    import hex_service_kit.observability as commons_observability

    from next_best_action.domain import models

    assert ports.ObservabilityTracerPort is commons_observability.ObservabilityTracerPort
    assert ports.TokenUsage is commons_observability.TokenUsage
    assert ports.EvaluationGatePort is agent_eval_kit.EvaluationGatePort
    assert models.TokenUsage is commons_observability.TokenUsage
    assert models.EvalReport is agent_eval_kit.EvalReport
    assert models.EvalMetricResult is agent_eval_kit.EvalMetricResult


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
