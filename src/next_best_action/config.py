"""Configuration and the adapter factory (dependency injection for the hexagon).

The factory reads ``config/settings.yaml`` (with ``${ENV_VAR}`` interpolation) and binds
each port to a concrete adapter by dotted path. Switching the whole system from the GCP
managed stack to an on-prem stack is a one-line change of ``profile`` (the ports-and-
adapters / no-lock-in principle). Every adapter follows one construction convention:
``Adapter(settings: Settings)``.

D5 is generic and APAC: the active ``vertical`` (banking | online retail) and ``market``
(JP | AU | SG) are settings, and each market's residency ``region`` and locales come from
the per-market profiles (config + seed), never a hard-coded branch.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from hex_service_kit.netdefaults import ConfiguredEmptyError, EnvSetting, read_env_setting
from pii_kit.patterns import NATIONAL_ID_PATTERNS

from .domain.models import MARKET_PROFILES, Market, MarketProfile, Vertical
from .envread import setting_or_default
from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")

_PROFILE_ENV = "MKT_NBA_PROFILE"
RUNTIME_PROFILES = frozenset({"local", "gcp", "platform", "onprem"})

#: The profile string handed to every INTERNET-FACING relaxation when the profile was never
#: chosen. Deliberately NOT a member of :data:`RUNTIME_PROFILES` and never reaches an adapter
#: binding: it exists so "no choice was made" is a distinct input to the security layers rather
#: than being indistinguishable from a deliberate ``local``.
UNCONSENTED_PROFILE = "unconfigured"

_JURISDICTIONS_ENV = "MKT_NBA_PII_JURISDICTIONS"
#: The jurisdiction codes the shared ``pii-kit`` actually carries national-identifier rows for.
#: Validating against this is the point: the pack SKIPS an unknown code rather than raising, so
#: an unvalidated typo silently removes a whole country's identifiers from the redaction set.
SUPPORTED_JURISDICTIONS = frozenset(NATIONAL_ID_PATTERNS)


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    The comparison is exact and case-sensitive on purpose: every posture decision downstream
    matches the profile string exactly, so ``Local`` selects none of the relaxations but also
    none of the restrictions. Normalising the case here would turn a typo into a silent choice;
    refusing it turns the typo into a boot failure.
    """
    if profile not in RUNTIME_PROFILES:
        expected = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {expected}")
    return profile


#: Profiles that mean "running on managed cloud infrastructure", for the banner's runtime half.
_MANAGED_PROFILES: frozenset[str] = frozenset({"gcp"})

#: The port whose ACTIVE binding decides what the provenance banner's model half says.
#: Named once here so rebinding it for a profile changes the banner in the same edit.
_GENERATOR_PORT: str = "llm"

#: Constant names a managed adapter may declare its model id under. Several spellings because
#: the fleet uses several, and a resolver that knew only one would report a bound model as
#: unnamed.
_MODEL_CONSTANTS: tuple[str, ...] = ("_MODEL", "_DEFAULT_MODEL")


def _declared_model(binding: str) -> str:
    """The model id the bound managed adapter declares, or an honest statement that it names none.

    Resolved from the BINDING rather than from a settings string, which is the point: a settings
    field would be a claim ABOUT the binding, and the two drift the first time somebody rebinds a
    profile without remembering the second field. Importing the adapter module here is safe with
    no cloud SDK installed -- every cloud import in these adapters lives inside the method that
    needs it, which is the portability property the parity suite already asserts.

    Returns ``managed-model-unnamed`` when the adapter pins no model id anywhere. That is not a
    placeholder for a nicer answer: it truthfully says a managed generator is bound and this
    repository does not name which model it calls, which is a fact a reviewer should be able to
    see rather than one a banner should paper over with an invented id.
    """
    from importlib import import_module

    module_path, _, class_name = binding.partition(":")
    try:
        module = import_module(module_path)
    except ImportError:  # pragma: no cover - the bound module is importable offline
        return "managed-model-unavailable"
    for holder in (module, getattr(module, class_name, None)):
        for name in _MODEL_CONSTANTS:
            value = getattr(holder, name, None)
            if value:
                return str(value)
    return "managed-model-unnamed"


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """The ONE resolution of ``MKT_NBA_PROFILE``, and what each consumer must key off.

    No module may re-derive the profile with its own ``os.environ.get(_PROFILE_ENV, "local")``:
    that fallback reads an UNSET variable as consent to the no-auth posture, which is the
    fail-open this type exists to remove (``tests/unit/test_profile_single_source.py`` fails the
    build if one reappears, in Python or in the shipped settings file).

    The two derived profile strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" string would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent consent this is still ``local`` (the SDK-free
    #: adapters), because the alternative would import cloud SDKs that are not installed; the
    #: local IDENTITY adapter refuses to construct when :attr:`explicit` is False, so an
    #: unconsented run has data adapters but no end-user identity.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (``MKT_NBA_PROFILE`` set, or a profile written into
    #: the reviewed settings file), rather than inherited from a fallback?
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every *relaxation* keys off: CORS origins, the dev-persona picker.

        These grant something extra to ``local``, so an unconsented run must NOT look like
        ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's allowlist and no
        persona picker.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay on loopback.
        """
        return self.profile if self.explicit else "local"


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    """The profile variable in three states, from the real environment or an injected mapping.

    The injected form builds the SAME :class:`~hex_service_kit.netdefaults.EnvSetting` the commons
    would, so a test drives the identical three states rather than a second, kinder implementation.
    """
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(
    environ: Mapping[str, str] | None = None, *, configured: str = ""
) -> ProfileChoice:
    """Resolve the profile in three states: unset, set-and-empty, set-and-valid.

    An ABSENT variable is NO CHOICE: it is not a member of the valid set, it selects the
    SDK-free adapters so the process can still boot, and every relaxation sees
    :data:`UNCONSENTED_PROFILE` instead. A variable an operator deliberately EMPTIED expressed an
    intent that names nothing, so it refuses rather than inheriting the absent case; folding the
    two together is exactly the collapse this resolver exists to remove. SET-AND-INVALID raises
    here rather than later, so a typo is a boot failure instead of an app that has already chosen
    its CORS, persona and bind postures from a string nothing binds. SET-AND-VALID is carried
    through unchanged.

    ``configured`` is the profile written into the reviewed settings file, used only when the
    environment names none: an adopter who commits ``profile: gcp`` has made a deliberate
    choice, whereas the shipped file names no profile at all.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value, which is not a profile. Unset it to leave "
            f"the choice to settings.yaml, or set it to one of "
            f"{', '.join(sorted(RUNTIME_PROFILES))}."
        )
    raw = setting.value or (configured or "").strip()
    if raw:
        _validate_profile(raw)
    return ProfileChoice(profile=raw or "local", explicit=bool(raw))


def resolve_pii_jurisdictions(
    environ: Mapping[str, str] | None = None, *, configured: Iterable[str] | None = None
) -> tuple[str, ...]:
    """Resolve the redaction pattern set, where an EMPTY set refuses instead of redacting less.

    Three states again, and the direction is the opposite of a relaxation. UNSET means "no
    override", so the reviewed set from ``config/settings.yaml`` (or the :class:`PiiSettings`
    default) applies: a missing variable must never shrink the redaction boundary. SET-AND-EMPTY
    refuses: ``MKT_NBA_PII_JURISDICTIONS=""`` or ``","`` used to survive the comma split as an
    empty tuple and silently strip every national identifier out of the redactor, the DLP
    custom info types and the eval gate's leak check at once, leaving only the universal
    email / phone rows. SET-AND-VALID is validated code by code against
    :data:`SUPPORTED_JURISDICTIONS`, because the shared pack SKIPS an unknown code rather than
    raising, so an unvalidated ``SGP`` would be indistinguishable from an empty set.

    The refusal is pure stdlib and happens at configuration load, before any adapter is built
    and before the DLP client's lazy SDK import, so it does not depend on an SDK being present.
    """
    env = os.environ if environ is None else environ
    raw = env.get(_JURISDICTIONS_ENV)
    if raw is None or not raw.strip():
        if raw is not None:
            raise ValueError(
                f"{_JURISDICTIONS_ENV} is set but names no jurisdiction; an empty redaction "
                "pattern set would strip every national identifier out of the redactor, the "
                "DLP custom info types and the eval leak check at once. Unset the variable to "
                f"keep the reviewed set, or name codes from: {_supported()}"
            )
        codes = tuple(str(c).strip().upper() for c in (configured or ()) if str(c).strip())
        source = "config/settings.yaml"
    else:
        codes = tuple(c.strip().upper() for c in raw.split(",") if c.strip())
        source = _JURISDICTIONS_ENV
    if not codes:
        raise ValueError(
            f"{source} names no PII jurisdiction; refusing to run with an empty redaction "
            f"pattern set. Name codes from: {_supported()}"
        )
    unknown = sorted(set(codes) - SUPPORTED_JURISDICTIONS)
    if unknown:
        raise ValueError(
            f"{source} names unsupported PII jurisdictions {unknown}; the shared pii-kit "
            "contributes no rows for them, so they would silently redact nothing. Supported: "
            f"{_supported()}"
        )
    return codes


def _supported() -> str:
    return ", ".join(sorted(SUPPORTED_JURISDICTIONS))


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` tokens recursively, in THREE states not two.

    The settings loader's own expansion is a resolver, and ``os.environ.get(name, default)``
    reintroduces the two-state collapse one layer down, in the loader, where no scan of adapter
    call sites would find it: a variable an operator deliberately emptied would take the default
    written in ``settings.yaml``. UNSET takes the written default, SET-AND-EMPTY REFUSES with
    ``ConfiguredEmptyError``, SET-AND-VALID wins.

    ``${VAR:-default}`` is ``setting_or_default(name, default)`` one layer down, so it delegates
    to that helper: one implementation of the rule, not two. ``${VAR}`` with no ``:-`` carries the
    empty string as its written default, so unset yields empty and emptied still refuses.
    """
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return setting_or_default(m.group(1), m.group(2) or "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


@dataclass(frozen=True)
class ModelSettings:
    #: The Vertex location the model client calls, NOT the compute region. Gemini 3
    #: serves the `us` and `eu` multi-regions only; `global` carries no residency
    #: guarantee. See models.location in config/settings.yaml.
    location: str = "us"
    reasoning: str = "gemini-3.5-flash"
    triage: str = "gemini-3.5-flash"
    hard_reasoning: str = "gemini-3.5-flash"  # Preview — feature-flagged off by default
    use_hard_reasoning: bool = False


@dataclass(frozen=True)
class RecommendationSettings:
    """Vertex AI recommendations + propensity knobs (used by the GCP adapter only)."""

    recommender_id: str = "mkt-nba-recommender"
    propensity_endpoint: str = ""  # Vertex endpoint resource id, set after deploy
    bigquery_dataset: str = "mkt_nba"
    customers_table: str = "customers"
    offers_table: str = "offers"
    eligibility_rules_table: str = "eligibility_rules"
    propensity_table: str = "propensity_signals"
    max_candidates: int = 50


@dataclass(frozen=True)
class KnowledgeBaseSettings:
    """The offer / policy corpus (File Search / A2)."""

    base_url_env: str = "KNOWLEDGE_BASE_URL"
    data_store_id: str = "mkt-nba-corpus"  # only used by the standalone GCP adapter
    location: str = "asia-southeast1"
    top_k: int = 10


@dataclass(frozen=True)
class ModelArmorSettings:
    template_id: str = "mkt-nba-guardrail"
    host: str = "modelarmor.asia-southeast1.rep.googleapis.com"


@dataclass(frozen=True)
class LoggingSettings:
    log_name: str = "next-best-action-audit"
    bucket: str = "next-best-action-worm"
    retention_days: int = 2557  # ~7 years


@dataclass(frozen=True)
class AgentEngineSettings:
    resource_name: str = ""  # reasoningEngine resource id, set after deploy
    display_name: str = "next-best-action"


@dataclass(frozen=True)
class RankingSettings:
    """Tunables for the deterministic ranking engine (config, not magic numbers)."""

    propensity_weight: float = 0.6
    value_weight: float = 0.4
    min_score: float = 0.0


@dataclass(frozen=True)
class LocalSettings:
    """Paths for the SDK-free ``local`` profile stores (SQLite FTS5 + append-only audit).

    Empty strings select the per-package default under ``~/.next_best_action/``; tests pass
    ``:memory:`` for ephemeral, deterministic stores. No Google Cloud here.
    """

    db_path: str = ""  # SQLite FTS5 offer/policy corpus index
    audit_path: str = ""  # append-only audit store
    seed_path: str = ""  # catalog/customer seed JSON ("" => bundled fictional seed)


@dataclass(frozen=True)
class PiiSettings:
    """Which jurisdictions' national-identifier patterns the redaction boundary applies.

    Drives the local regex redactor and the GCP DLP adapter (and, via
    ``MKT_NBA_PII_JURISDICTIONS``, the eval gate) so a deployment detects its own
    identifiers by config, not a code change. Default is D5's home markets (JP / AU / SG);
    the supported packs live in the shared ``pii-kit`` package (``pii_kit.patterns``).
    """

    jurisdictions: tuple[str, ...] = ("SG", "JP", "AU")


# Per-market residency region overrides (region/locale are config + seed, not hard-coded).
@dataclass(frozen=True)
class MarketOverride:
    region: str = ""
    locales: tuple[str, ...] = ()
    currency: str = ""


@dataclass(frozen=True)
class Settings:
    project_id: str = "your-gcp-project"
    region: str = "asia-southeast1"  # default residency region; per-market profile overrides
    profile: str = "local"  # local | gcp | platform | onprem; see resolve_profile for "unset"
    vertical: str = "banking"  # banking | online_retail (the active vertical)
    market: str = "SG"  # JP | AU | SG (the active market)
    consent_url: str = ""  # Mkt6 consent and preference store; required on managed profiles
    consent_audience: str = ""  # Mkt6 custom OIDC audience; required for gcp Workload Identity
    models: ModelSettings = field(default_factory=ModelSettings)
    recommendation: RecommendationSettings = field(default_factory=RecommendationSettings)
    knowledge_base: KnowledgeBaseSettings = field(default_factory=KnowledgeBaseSettings)
    model_armor: ModelArmorSettings = field(default_factory=ModelArmorSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    agent_engine: AgentEngineSettings = field(default_factory=AgentEngineSettings)
    ranking: RankingSettings = field(default_factory=RankingSettings)
    local: LocalSettings = field(default_factory=LocalSettings)
    pii: PiiSettings = field(default_factory=PiiSettings)
    # Per-market residency overrides keyed by market code, e.g. {"JP": {"region": "..."}}.
    markets: dict[str, MarketOverride] = field(default_factory=dict)
    # port_name -> { profile -> "module.path:ClassName" }
    adapters: dict[str, dict[str, str]] = field(default_factory=dict)
    # Was the profile chosen DELIBERATELY, or merely inherited from the fallback? ``load`` sets
    # this False when nothing named a profile. Direct construction is deliberate by definition
    # (a caller named the profile in code), so the default is True. The seeded-persona identity
    # adapter refuses to serve when this is False: a no-auth demo identity must never be handed
    # out because an env var went missing.
    profile_explicit: bool = True

    # ------------------------------------------------------------------ #
    # Convenience accessors (validated, config-driven; never hard-coded)
    # ------------------------------------------------------------------ #
    @property
    def profile_choice(self) -> ProfileChoice:
        """The resolved profile plus whether it was deliberate: one fact, one home."""
        return ProfileChoice(profile=self.profile, explicit=self.profile_explicit)

    @property
    def exposure_profile(self) -> str:
        """The profile every RELAXATION keys off (CORS, the dev-persona picker)."""
        return self.profile_choice.exposure_profile

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case."""
        return self.profile_choice.bind_profile

    @property
    def active_vertical(self) -> Vertical:
        return Vertical(self.vertical)

    @property
    def active_market(self) -> Market:
        return Market(self.market)

    def market_profile(self, market: Market | None = None) -> MarketProfile:
        """Resolve a market's residency region / locales, applying any settings override."""
        market = market or self.active_market
        base = MARKET_PROFILES[market]
        override = self.markets.get(market.value)
        if override is None:
            return base
        return MarketProfile(
            market=base.market,
            region=override.region or base.region,
            display_name=base.display_name,
            locales=override.locales or base.locales,
            currency=override.currency or base.currency,
        )

    @staticmethod
    def load(path: str | os.PathLike[str] | None = None) -> Settings:
        path = Path(path or setting_or_default("MKT_SETTINGS", "config/settings.yaml"))
        raw = _interpolate(yaml.safe_load(path.read_text())) if path.exists() else {}
        raw = raw or {}
        markets_raw = raw.pop("markets", {}) or {}
        markets = {
            str(code): MarketOverride(
                region=str(spec.get("region", "")),
                locales=tuple(spec.get("locales", []) or ()),
                currency=str(spec.get("currency", "")),
            )
            for code, spec in markets_raw.items()
            if isinstance(spec, dict)
        }
        pii_raw = dict(raw.pop("pii", {}) or {})
        # An empty or unsupported jurisdiction set REFUSES here rather than quietly redacting
        # less; see :func:`resolve_pii_jurisdictions` for the three states.
        pii_raw["jurisdictions"] = resolve_pii_jurisdictions(
            configured=pii_raw.get("jurisdictions") or PiiSettings().jurisdictions
        )
        nested: dict[str, Any] = {
            "models": ModelSettings(**(raw.pop("models", {}) or {})),
            "recommendation": RecommendationSettings(**(raw.pop("recommendation", {}) or {})),
            "knowledge_base": KnowledgeBaseSettings(**(raw.pop("knowledge_base", {}) or {})),
            "model_armor": ModelArmorSettings(**(raw.pop("model_armor", {}) or {})),
            "logging": LoggingSettings(**(raw.pop("logging", {}) or {})),
            "agent_engine": AgentEngineSettings(**(raw.pop("agent_engine", {}) or {})),
            "ranking": RankingSettings(**(raw.pop("ranking", {}) or {})),
            "local": LocalSettings(**(raw.pop("local", {}) or {})),
            "pii": PiiSettings(**pii_raw),
            "markets": markets,
        }
        # The profile is resolved in ONE place, and an unset variable is no choice at all.
        # Reading it here with a ``"local"`` fallback is exactly the fail-open being closed:
        # see :func:`resolve_profile` and ``tests/unit/test_profile_single_source.py``.
        choice = resolve_profile(configured=str(raw.pop("profile", "") or ""))
        vertical = setting_or_default("MKT_VERTICAL", str(raw.pop("vertical", "banking")))
        market = setting_or_default("MKT_MARKET", str(raw.pop("market", "SG")))
        # ``profile_explicit`` is derived, never read from the settings file: a file that could
        # assert "the profile was chosen" would reopen the fail-open from the other side.
        known = {f for f in Settings.__dataclass_fields__ if f not in nested} - {"profile_explicit"}
        flat: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        return Settings(
            profile=choice.profile,
            profile_explicit=choice.explicit,
            vertical=vertical,
            market=market,
            **flat,
            **nested,
        )

    @property
    def runtime(self) -> str:
        """WHERE this process runs, as the UI banner states it: ``gcp`` or ``local``.

        Derived from the profile, never sniffed from the environment. A console that read its
        runtime from ``window.location`` would be right until the day the deployment served
        through a proxy and wrong silently after that, so the service is the party asked.

        ``onprem`` reads ``local`` because that is its entire point, and a managed model call
        does not make a process cloud-hosted: this states where the PROCESS runs, and
        :attr:`generator_model` states whose model answers.
        """
        return "gcp" if self.profile in _MANAGED_PROFILES else "local"

    @property
    def generator_model(self) -> str:
        """WHICH model answers, as the UI banner states it (org decision, 2026-08-30).

        These systems are demonstrated on a laptop and on a deployment, sometimes in the same
        hour, and a screenshot of one is indistinguishable from the other. A viewer who cannot
        tell which they are looking at cannot tell whether a figure came from a managed model or
        a deterministic offline stub, which is exactly the confusion an audit-first pitch cannot
        afford. So the page states it, always, rather than the presenter stating it sometimes.

        ``no-model`` is deliberately NOT ``deterministic-offline-stub``. The stub string claims a
        model-shaped port bound to a stub; ``no-model`` says there is no such port at all, and a
        reviewer approving an escalation is entitled to know which of the two they are reading.
        """
        if not _GENERATOR_PORT:
            return "no-model"
        table = self.adapters.get(_GENERATOR_PORT) or {}
        binding = str(table.get(self.profile, "") or "")
        if not binding:
            return "no-model"
        if self.profile not in _MANAGED_PROFILES:
            # The on-prem adapters are fail-fast migration placeholders: they raise rather than
            # generating, so naming a model would advertise one that never answers.
            if self.profile == "onprem":
                return "onprem-not-implemented"
            return "deterministic-offline-stub"
        return _declared_model(binding)


def instantiate(dotted: str, settings: Settings) -> Any:
    """Import ``module.path:ClassName`` and construct it with ``settings``."""
    module_path, _, class_name = dotted.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(settings)


class Container:
    """Lazily-built registry of port -> adapter instances.

    Adapters are imported only on first access so that, e.g., a unit test using the on-prem
    or local profile never needs the Google Cloud SDKs installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port_name: str) -> Any:
        binding = self.settings.adapters.get(port_name, {})
        dotted = binding.get(self.settings.profile)
        if not dotted:
            raise KeyError(
                f"No adapter configured for port '{port_name}' "
                f"under profile '{self.settings.profile}'."
            )
        return instantiate(dotted, self.settings)

    # One cached_property per port keeps wiring declarative and type-greppable.
    @cached_property
    def recommendation(self) -> Any:
        return self._bind("recommendation")

    @cached_property
    def knowledge_base(self) -> Any:
        return self._bind("knowledge_base")

    @cached_property
    def llm(self) -> Any:
        return self._bind("llm")

    @cached_property
    def guardrail(self) -> Any:
        return self._bind("guardrail")

    @cached_property
    def redaction(self) -> Any:
        return self._bind("redaction")

    @cached_property
    def audit(self) -> Any:
        return self._bind("audit")

    @cached_property
    def tracer(self) -> Any:
        return self._bind("tracer")

    @cached_property
    def evaluation(self) -> Any:
        return self._bind("evaluation")

    @cached_property
    def agent_registry(self) -> Any:
        return self._bind("agent_registry")

    @cached_property
    def tool_catalog(self) -> Any:
        return self._bind("tool_catalog")

    @cached_property
    def identity(self) -> Any:
        return self._bind("identity")

    @cached_property
    def review_router(self) -> Any:
        return self._bind("review_router")

    @cached_property
    def consent(self) -> Any:
        return self._bind("consent")


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the same ``adapters:`` table the container binds from, so a deployment that rebound
    the identity port in ``config/settings.yaml`` (the documented on-premises path: swap the
    placeholder for the client's own IdP adapter) is answered about the adapter it ACTUALLY
    runs, not about the one the profile name suggests.

    Constructing is deliberately avoided: the seeded-persona adapter refuses to construct under
    an inherited profile, so a posture computed from an instance would be unobtainable in one
    of the exact cases it has to describe.
    """
    target = settings.adapters["identity"][settings.profile]
    module_path, _, class_name = target.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {target!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See ``ports/identity.py``: the profile string cannot answer it, because ``onprem`` names a
    placeholder today and a real IdP once a client rebinds it.

    Any failure to establish the answer resolves to ``CLIENT_ASSERTED``. A guard that switches
    OFF because a lookup raised is a guard that fails open, and nothing is lost by failing
    closed here: the same failure surfaces loudly at the first request, when the container
    resolves the identical binding for real.
    """
    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:
        return CLIENT_ASSERTED
