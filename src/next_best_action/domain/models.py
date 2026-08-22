"""Domain models for the Next-Best-Action: Recommendations and Cross-Sell system (D5).

This module is the heart of the hexagon. It has **no dependency on Google Cloud,
Vertex AI, FastAPI, or any framework** (only the Python standard library). Every adapter
(GCP, remote-platform, or on-prem placeholder) speaks in terms of these types, which is
what lets the managed-service stack be swapped for an on-premise one without touching
domain logic (no vendor lock-in, ports and adapters).

D5 is deliberately **generic next-best-action**, not a bank-specific tool:

* ``Vertical`` is a configurable enum (banking, online retail), so the same engines reason
  over a deposit-account cross-sell and an e-commerce product recommendation. Eligibility
  is suitability for banking (KYC / risk / product-holding) and availability + affinity for
  online retail (stock + behaviour), driven by per-vertical rules in the seed, not branches.
* ``Market`` is a configurable enum (JP | AU | SG) carrying its residency region and
  locales, so JP, AU and SG are first-class config and seed, never hard-coded.

The deterministic engines are the heart of the system: candidate filtering, eligibility
(rule evaluation), ranking/scoring (propensity x value x eligibility), and consent check.
The LLM only explains "why recommended"; every recommendation that leaves the system
carries a :class:`Citation` and the recommendation set sets ``requires_human_review``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_eval_kit.report import EvalMetricResult as EvalMetricResult
from agent_eval_kit.report import EvalReport as EvalReport
from hex_service_kit import StrEnum
from hex_service_kit.observability import TokenUsage as TokenUsage

from .kernel import ThinkingLevel

# Re-exported, not redeclared. These three are shared value types that had simply never been
# shared: every repo in the catalog had grown its own copy, and copies drift. The redundant
# `as` alias is the explicit re-export form, so ruff does not read them as unused imports.
#
# `agent_eval_kit.report` is imported as a SUBMODULE rather than through the package root on
# purpose: the root pulls in `gate_client`, which needs httpx, and this module promises to be
# stdlib-only so the domain never depends on a transport.


def utcnow() -> datetime:
    """Timezone-aware UTC now (the single clock the domain uses)."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Vertical and Market — the two configurable axes (generic, multi-vertical, APAC)
# --------------------------------------------------------------------------- #
class Vertical(StrEnum):
    """The business vertical the recommendation is scoped to.

    D5 is generic: banking is ONE vertical and online retail is another. The deterministic
    eligibility/ranking engines and the LLM prompts switch taxonomy/rules by vertical via
    the seed; no bank-only logic is baked into the domain.
    """

    BANKING = "banking"
    ONLINE_RETAIL = "online_retail"


class Market(StrEnum):
    """A supported market (Japan, Australia, Singapore).

    The residency region, locales and per-market rule sets are config + seed (see
    :data:`MARKET_PROFILES` and ``config/settings.yaml``), never hard-coded into a branch.
    Adding a market is a config + seed change, not a code change.
    """

    JP = "JP"
    AU = "AU"
    SG = "SG"


@dataclass(frozen=True, slots=True)
class MarketProfile:
    """Static, fictional-data-friendly metadata for a market.

    The residency ``region`` is a GCP regional id selectable at deploy and validated;
    ``locales`` drives bilingual (ja + en) output. These defaults can be overridden in
    ``config/settings.yaml`` so the catalog stays config-driven.
    """

    market: Market
    region: str  # GCP residency region, e.g. "asia-northeast1" (Tokyo)
    display_name: str
    locales: tuple[str, ...]  # e.g. ("ja", "en") or ("en",)
    currency: str = ""


# Built-in defaults. Region/locale are config + seed: settings.yaml may override these.
MARKET_PROFILES: dict[Market, MarketProfile] = {
    Market.JP: MarketProfile(
        market=Market.JP,
        region="asia-northeast1",
        display_name="Japan",
        locales=("ja", "en"),
        currency="JPY",
    ),
    Market.AU: MarketProfile(
        market=Market.AU,
        region="australia-southeast1",
        display_name="Australia",
        locales=("en",),
        currency="AUD",
    ),
    Market.SG: MarketProfile(
        market=Market.SG,
        region="asia-southeast1",
        display_name="Singapore",
        locales=("en",),
        currency="SGD",
    ),
}


# --------------------------------------------------------------------------- #
# Provenance / citation
# --------------------------------------------------------------------------- #
class SourceType(StrEnum):
    """Every citation names which kind of evidence it points to."""

    OFFER_CATALOG = "offer_catalog"  # the offer / product catalog entry
    ELIGIBILITY_RULE = "eligibility_rule"  # a per-market/vertical eligibility rule
    PROPENSITY = "propensity"  # a propensity / recommendation model signal
    CONSENT = "consent"  # the customer consent / preference record
    POLICY = "policy"  # an internal policy / suitability note (File Search)
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to every recommendation and decision in the result.

    A reviewer must be able to trace every recommendation, score and eligibility outcome
    back to its exact source: an auditable next-best-action is the whole point of D5.
    """

    source_id: str
    source_type: SourceType
    title: str
    url: str = ""
    page: int | None = None
    published_date: str | None = None  # ISO date as published, if known
    snippet: str = ""
    score: float | None = None


# --------------------------------------------------------------------------- #
# Customer / Shopper
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Customer:
    """The customer (banking) / shopper (online retail) the recommendation is for.

    ``attributes`` holds vertical-specific facts the eligibility rules read (e.g.
    ``{"kyc": "verified", "risk_tier": "low"}`` for banking, ``{"segment": "vip"}`` for
    retail). ``holdings`` is what the customer already has (accounts / past purchases), used
    to suppress already-held offers. The engine never branches on a hard-coded attribute
    name: rules name the attributes they read, so D5 stays generic across verticals.
    """

    id: str
    market: Market
    vertical: Vertical
    attributes: dict[str, str] = field(default_factory=dict)
    holdings: tuple[str, ...] = ()  # offer_ids already held / purchased
    affinities: dict[str, float] = field(default_factory=dict)  # category -> 0..1 affinity
    # Tenant / issuer partition this customer belongs to (multi-tenant isolation). The
    # orchestrator enforces object-level authorization against the verified principal's
    # tenant fail-closed: a set tenant that does not match the caller is DENIED. Kept
    # defaulted so existing constructions compile; the seed tags every customer explicitly.
    tenant: str = ""


# --------------------------------------------------------------------------- #
# Offer / CandidateSet
# --------------------------------------------------------------------------- #
class OfferKind(StrEnum):
    """A category of offer (generic across verticals).

    Banking and online retail share these abstract kinds; per-vertical taxonomy detail
    lives in the seed data, not in the enum, so the engine stays generic.
    """

    PRODUCT = "product"  # a product to cross-sell (account, SKU)
    UPGRADE = "upgrade"  # an upgrade / tier move
    PROMOTION = "promotion"  # a time-bound promotion / discount
    BUNDLE = "bundle"  # a bundle / cross-sell pairing
    SERVICE = "service"  # an add-on service
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Offer:
    """One offer in the catalog that could be recommended.

    ``base_value`` is the deterministic business value of the offer to the firm (normalised
    later); ``category`` ties an offer to a customer affinity; ``required_consent_channel``
    names the consent channel needed to surface it (config + seed, never hard-coded). For
    online retail ``stock`` gates availability; for banking ``required_attributes`` express
    suitability constraints the eligibility engine evaluates.
    """

    id: str
    name: str
    kind: OfferKind
    market: Market
    vertical: Vertical
    category: str = ""
    base_value: float = 0.0  # business value (firm side); normalised in ranking
    required_consent_channel: str = ""  # "" => no specific channel required
    required_attributes: dict[str, str] = field(default_factory=dict)
    excluded_if_held: tuple[str, ...] = ()  # offer_ids that conflict with this one
    stock: int | None = None  # retail availability; None => not stock-gated
    citations: tuple[Citation, ...] = ()

    def to_citation(self) -> Citation:
        return Citation(
            source_id=self.id,
            source_type=SourceType.OFFER_CATALOG,
            title=self.name,
            snippet=f"{self.kind.value} offer in {self.category or 'general'}",
        )


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """The candidate offers for a customer before eligibility/ranking.

    Produced by the candidate-filter engine (catalog scoped to market+vertical, minus
    already-held / out-of-stock), optionally seeded by a propensity recall list.
    """

    customer_id: str
    market: Market
    vertical: Vertical
    offers: tuple[Offer, ...] = ()


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
class RuleEffect(StrEnum):
    """What an eligibility rule does when it matches."""

    REQUIRE = "require"  # customer attribute must equal the rule value (suitability)
    EXCLUDE = "exclude"  # customer attribute equal to the value disqualifies the offer
    REQUIRE_STOCK = "require_stock"  # retail: offer must have stock > 0 (availability)


@dataclass(frozen=True, slots=True)
class EligibilityRule:
    """One per-market, per-vertical eligibility rule (config + seed, never hard-coded).

    A rule names the customer ``attribute`` it reads and the ``value`` it checks under an
    ``effect``. Banking rules express suitability (KYC verified, risk tier); retail rules
    express availability + segment gating. Rules carry a citation so an outcome is auditable.
    """

    id: str
    market: Market
    vertical: Vertical
    effect: RuleEffect
    attribute: str = ""  # the customer attribute the rule reads ("" for REQUIRE_STOCK)
    value: str = ""
    applies_to_kind: OfferKind | None = None  # None => all kinds
    applies_to_category: str = ""  # "" => all categories
    description: str = ""
    citation: Citation | None = None


class EligibilityOutcome(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """The deterministic eligibility decision for one (customer, offer) pair."""

    offer_id: str
    outcome: EligibilityOutcome
    reasons: tuple[str, ...] = ()  # human-readable reasons (which rules fired)
    failed_rule_ids: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.outcome is EligibilityOutcome.ELIGIBLE


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #
class ConsentChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"
    PHONE = "phone"


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    """A customer's marketing-consent state for one channel (per market/vertical).

    Local fixtures mirror jurisdiction-sensitive consent data for the offline Mkt6 stand-in.
    Production decisions come from Mkt6 through ``ConsentPort``; an offer without an explicit
    allow on its channel is suppressed before it can be recommended.
    """

    customer_id: str
    channel: ConsentChannel
    status: ConsentStatus
    market: Market
    updated_date: str = ""
    citation: Citation | None = None


@dataclass(frozen=True, slots=True)
class ConsentDecision:
    """The Mkt6 consent decision mapped onto one offer without losing replay identity."""

    offer_id: str
    allowed: bool
    channel: ConsentChannel | None = None
    reason: str = ""
    citation: Citation | None = None
    decision_id: str = ""
    as_of: str = ""


# --------------------------------------------------------------------------- #
# Ranking / scoring
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PropensitySignal:
    """A propensity / recommendation-model score for one (customer, offer) pair.

    The GCP adapter sources these from Vertex AI recommendations + propensity models; the
    local adapter derives them deterministically from customer affinity + offer value. The
    LLM never produces these numbers.
    """

    offer_id: str
    score: float  # 0..1 propensity to take the offer
    citation: Citation | None = None


@dataclass(frozen=True, slots=True)
class RankedOffer:
    """One scored, ranked offer with the deterministic score breakdown.

    The ``score`` is the deterministic combination of propensity, normalised business value
    and eligibility; nothing here is an LLM guess. ``rank`` is 1-based.
    """

    offer_id: str
    name: str
    kind: OfferKind
    rank: int
    score: float  # 0..1 combined, deterministic
    propensity: float
    value_score: float  # normalised 0..1 business value
    channel: ConsentChannel | None = None
    rationale: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Ranking:
    """The deterministic ranking of eligible, consented offers for a customer."""

    customer_id: str
    market: Market
    vertical: Vertical
    offers: tuple[RankedOffer, ...] = ()

    @property
    def top(self) -> RankedOffer | None:
        return self.offers[0] if self.offers else None


# --------------------------------------------------------------------------- #
# Generation (LLM) — the LLM only explains "why recommended"; never decides numbers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class WebCitation:
    """Provenance for a grounded fact returned by the model."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    system_instruction: str | None = None
    model: str | None = None  # None => adapter default from config
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM
    temperature: float = 0.2
    max_output_tokens: int = 4096
    response_schema: dict | None = None  # JSON schema for structured output


# `TokenUsage` is NOT declared here. It is re-exported from `hex_service_kit.observability` at the
# top of this module: sixteen repositories had each hand-copied the same three int fields, and a
# value type copied into N repositories is N types that only look alike until one of them changes.


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    web_citations: tuple[WebCitation, ...] = ()
    raw: dict | None = None


# --------------------------------------------------------------------------- #
# Safety (guardrail) — A1 Guardrail Gateway concern
# --------------------------------------------------------------------------- #
class GuardrailCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_DATA = "sensitive_data"
    MALICIOUS_URL = "malicious_url"
    OTHER = "other"


class Direction(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class GuardrailFinding:
    category: GuardrailCategory
    confidence: str  # "low" | "medium" | "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    allowed: bool
    direction: Direction
    findings: tuple[GuardrailFinding, ...] = ()
    sanitized_text: str | None = None
    reason: str = ""


# --------------------------------------------------------------------------- #
# PII redaction (DLP de-identification) — the redact-before-everything boundary (R1)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RedactionFinding:
    """One de-identified info type and how many times it was masked."""

    info_type: str  # e.g. "EMAIL_ADDRESS", "SG_NRIC_FIN", "JP_MY_NUMBER", "AU_TFN"
    count: int = 1


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """De-identified text plus per-info-type finding counts.

    ``text`` is safe to send to a model, a trace span or the audit sink: customer PII has
    been masked at the boundary (P-04). ``redacted`` is True when anything was masked.
    """

    text: str
    findings: tuple[RedactionFinding, ...] = ()

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


# --------------------------------------------------------------------------- #
# Audit and observability — A5 Observability, Audit and FinOps concern
# --------------------------------------------------------------------------- #
class Decision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"  # routed to a human (maker-checker)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, WORM-stored record of one next-best-action interaction.

    Prompt and response are stored **already redacted** (P-04, R1): customer PII is masked
    and the internal customer key is pseudonymized at the boundary before anything is ever
    written to the audit sink or a trace span. The field names make that guarantee legible.
    """

    action: str  # "recommend" | "eligibility" | "consent"
    actor: str  # authenticated operator / service identity
    decision: Decision
    redacted_prompt: str = ""
    redacted_response: str = ""
    citations: tuple[Citation, ...] = ()
    resource: str = "next-best-action"
    trace_id: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Evaluation gate — A4 AI Quality and Model-Risk concern
# --------------------------------------------------------------------------- #
# `EvalMetricResult` and `EvalReport` are NOT declared here either. They are re-exported from
# `agent_eval_kit.report` at the top of this module.
#
# The fail-closed `passed` rule this repo wrote by hand is the rule the commons type carries, to
# the character: `n_examples > 0 and bool(results) and all(...)`. The naive `all(...)` is a
# fail-open, because `all(())` is vacuously True, so a report that scored nothing reported PASSED
# and `eval/run_eval.py` exits 0 on that property. Re-exporting is therefore safe here, and it
# would NOT be if the local rule had been the stricter of the two: a re-export silently adopts
# the commons behaviour, so a local guard the commons lacks must be pushed upstream instead.
#
# The commons report additionally carries the durable evidence a promotion needs (run_id,
# dataset_version, dataset_digest, evaluator, schema_version, trace_id, correlation_id,
# artifact_refs, attested). Every one of them is defaulted, so the constructor calls in this repo
# are unchanged, and the remote adapter now returns the attested report instead of a thin copy.


# --------------------------------------------------------------------------- #
# Governance — A3 Agent Registry and the MCP tool catalog
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Minimal A2A-style agent card published at /.well-known/agent-card.json."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...] = ()
    provider: str = "next-best-action"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A governed, least-privilege tool exposed to the agent (typically via MCP)."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Retrieval (offer-catalog / policy corpus, File Search)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RetrievedPassage:
    """A passage retrieved from the offer / policy corpus (KnowledgeBasePort)."""

    text: str
    citation: Citation
    score: float = 0.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    top_k: int = 10
    market: Market | None = None
    vertical: Vertical | None = None
    filters: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Shared severity scale
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --------------------------------------------------------------------------- #
# Request and the top-level aggregates (always require human review)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RecommendationRequest:
    """The inbound request for next-best-action recommendations for a customer."""

    customer_id: str
    market: Market
    vertical: Vertical
    max_recommendations: int = 5
    channel: ConsentChannel | None = None  # restrict to one channel, optional


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One cited next-best-action recommendation for a customer.

    Bundles the ranked offer, its eligibility outcome, its consent decision and the LLM's
    "why recommended" explanation. Everything consequential (eligibility, consent, score)
    is deterministic; the LLM only narrates ``explanation``.
    """

    offer_id: str
    name: str
    kind: OfferKind
    rank: int
    score: float
    propensity: float
    value_score: float
    channel: ConsentChannel | None
    eligibility: EligibilityResult
    consent: ConsentDecision
    explanation: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationSet:
    """A cited next-best-action result for a customer (the top-level D5 artifact).

    The consequential output of D5: a ranked set of recommendations with full provenance.
    It is acted upon (an offer is presented to a customer), so it **always** requires human
    review (maker-checker): a maker (the agent) proposes and a checker (a qualified operator)
    disposes before anyone surfaces it to the customer. ``suppressed`` records offers that
    were filtered for ineligibility or missing consent, with the reason, for the audit trail.
    """

    id: str
    customer_id: str
    market: Market
    vertical: Vertical
    recommendations: tuple[Recommendation, ...] = ()
    suppressed: tuple[EligibilityResult, ...] = ()
    consent_suppressed: tuple[ConsentDecision, ...] = ()
    summary: str = ""
    citations: tuple[Citation, ...] = ()
    requires_human_review: bool = True
    generated_at: datetime = field(default_factory=utcnow)

    @property
    def top(self) -> Recommendation | None:
        return self.recommendations[0] if self.recommendations else None
