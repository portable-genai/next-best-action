"""RecommendationService — the next-best-action orchestrator.

Owns the full recommendation pipeline and calls only ports plus deterministic engines. Candidate
filtering, eligibility and ranking stay pure and replayable here. Marketing consent is obtained
through marketing-compliance-gate's versioned decision contract, so this repo does not maintain a
second legal decision store. The LLM only explains "why recommended" over the already-fixed ranking.
Every consequential output is maker-checker gated: the recommendation set always requires human
review.

Pipeline (each step wrapped in ``tracer.span``; audited at the end):

    tracer.span("nba.recommend"):
      redact(input) -> guardrail.screen(INPUT)      [blocked -> audit BLOCKED + raise]
      -> recommendations.customer(customer_id)       (the customer / shopper profile)
      -> AUTHORIZE object access (fail-closed)        [cross-tenant -> AuthorizationError]
      -> recommendations.catalog(market, vertical)   (the offer catalog)
      -> candidate_filter.filter(customer, catalog)  [empty -> NoCandidatesError]
      -> eligibility.evaluate_all(customer, candidates, rules)   (suitability/availability)
      -> consent.decide(candidate channel) through marketing-compliance-gate          (marketing
      consent)
      -> recommendations.propensity(customer, candidates)        (Vertex propensity)
      -> ranking.rank(eligible & consented offers)               (deterministic score)
      -> llm.generate("why recommended") per top recommendation  (explanation only)
      -> assemble RecommendationSet (requires_human_review=True)
      -> redact(output) -> guardrail.screen(OUTPUT)  [blocked -> audit BLOCKED + raise]
      -> audit.record (already-redacted; customer key pseudonymized)

Two boundary guarantees layered on top (security-critical, fail-closed):

* **Object-level authorization** (C2): the caller is a verified :class:`Principal`, not a
  free-text actor. Immediately after the customer fetch, a customer whose ``tenant`` does
  not match the principal's tenant is DENIED (``AuthorizationError``) rather than served, so
  a demo-bank operator can never pull an other-bank customer (cross-tenant object leak).
* **Redact before everything** (C3, R1/P-04): customer PII is de-identified and the internal
  customer key is pseudonymized at the boundary before any model call and before any audit
  write, so PII is minimised to the model and never lands in the WORM audit sink.

Defensive throughout: a propensity / corpus call that degrades is tolerated, but a blocked
input and an empty candidate set are hard errors so a recommendation is never built on
screened-out or absent offers.

Pure domain code: no Google Cloud / Vertex AI / FastAPI imports.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from contextlib import nullcontext
from typing import Any

from consent_preference_kit import ConsentQuery

from .candidate_service import CandidateFilterService
from .eligibility_service import EligibilityService
from .errors import AuthorizationError, GuardrailBlockedError, NoCandidatesError
from .identity import Principal
from .models import (
    AuditEvent,
    Citation,
    ConsentChannel,
    ConsentDecision,
    Customer,
    Decision,
    Direction,
    EligibilityResult,
    GuardrailVerdict,
    LlmMessage,
    LlmRequest,
    Offer,
    PropensitySignal,
    RankedOffer,
    Ranking,
    Recommendation,
    RecommendationRequest,
    RecommendationSet,
    SourceType,
)
from .ranking_service import RankingService, merge_citations

_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["explanation"],
}


class RecommendationService:
    """Build a cited next-best-action result for a customer. Explicit ports in constructor."""

    def __init__(
        self,
        recommendations: Any,
        knowledge_base: Any,
        llm: Any,
        guardrail: Any,
        redaction: Any,
        tracer: Any,
        audit: Any,
        consent: Any,
        candidate_filter: CandidateFilterService | None = None,
        eligibility: EligibilityService | None = None,
        ranking: RankingService | None = None,
        review_router: Any = None,
    ) -> None:
        self._recs = recommendations
        self._knowledge_base = knowledge_base
        self._llm = llm
        self._guardrail = guardrail
        self._redaction = redaction
        self._tracer = tracer
        self._audit = audit
        self._candidate_filter = candidate_filter or CandidateFilterService()
        self._eligibility = eligibility or EligibilityService()
        self._consent = consent
        self._ranking = ranking or RankingService()
        # Rule R8: when the set requires human review it is routed to human-review-console (the
        # maker-checker
        # console), not left as a boolean. Optional so the CLI and unit tests can omit it; when
        # unset the escalation still audits ESCALATED, it just is not forwarded to a console.
        self._review_router = review_router

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def recommend(self, request: RecommendationRequest, principal: Principal) -> RecommendationSet:
        # The caller is a server-verified principal, never a client-asserted actor. Derive
        # the audit actor from it so the downstream helpers stay actor-typed.
        actor = principal.actor
        with self._span("nba.recommend", market=request.market.value):
            # Redact PII before the guardrail screens the input (R1 boundary order).
            self._guard(self._input_context(request), Direction.INPUT, request, principal)

            customer = self._recs.customer(request.customer_id, request.market, request.vertical)

            # Object-level authorization, fail-closed: a customer that belongs to a tenant
            # other than the verified principal's is DENIED (cross-tenant object leak). Deny
            # is the default: a set tenant that mismatches is refused before any offer is
            # built, ranked, explained or audited for this actor.
            if customer.tenant and customer.tenant != principal.tenant:
                raise AuthorizationError(
                    f"principal tenant {principal.tenant!r} is not authorized for a customer "
                    f"in tenant {customer.tenant!r}"
                )

            catalog = self._recs.catalog(request.market, request.vertical)
            candidates = self._candidate_filter.filter(customer, catalog)
            if not candidates.offers:
                raise NoCandidatesError(
                    "no candidate offers after filtering; a recommendation must be grounded"
                )

            rules = self._rules(request)
            elig = self._eligibility.evaluate_all(customer, candidates.offers, rules)
            elig_by_id = {e.offer_id: e for e in elig}

            consent_decisions = self._consent_decisions(candidates.offers, request, principal)
            consent_by_id = {c.offer_id: c for c in consent_decisions}

            propensity = self._propensity(customer, candidates.offers)
            ranking = self._ranking.rank(
                customer_id=customer.id,
                market=request.market,
                vertical=request.vertical,
                offers=candidates.offers,
                eligibility=elig_by_id,
                consent=consent_by_id,
                propensity=propensity,
            )

            recs = self._build_recommendations(ranking, elig_by_id, consent_by_id, request, actor)
            suppressed = tuple(e for e in elig if not e.eligible)
            consent_suppressed = tuple(
                c for c in consent_decisions if not c.allowed and elig_by_id[c.offer_id].eligible
            )
            summary = self._summarise(request, recs, suppressed, consent_suppressed)
            # Consent is consequential even when it suppresses every offer. Keep the exact
            # marketing-compliance-gate decision IDs in the aggregate evidence so the durable audit
            # can reconcile
            # a refusal/outage, rather than recording only successful recommendation evidence.
            citations = merge_citations(
                tuple(c for r in recs for c in r.citations)
                + tuple(
                    decision.citation
                    for decision in consent_decisions
                    if decision.citation is not None
                )
            )

            result = RecommendationSet(
                id=f"nba-{request.market.value}-{request.vertical.value}-{customer.id}",
                customer_id=customer.id,
                market=request.market,
                vertical=request.vertical,
                recommendations=recs,
                suppressed=suppressed,
                consent_suppressed=consent_suppressed,
                summary=summary,
                citations=citations,
                requires_human_review=True,
            )
            self._guard(summary, Direction.OUTPUT, request, principal)
            self._record(result, request, principal, customer)

            # Rule R8: route the escalation to human-review-console (the maker-checker console)
            # rather than
            # terminating it in a boolean. The verified principal's tenant is threaded through
            # (never a client-asserted one) so the routed review is partitioned to the tenant
            # that owns the set; the adapter redacts per-customer PII before the wire. Best-
            # effort: a console outage must not fail an already-assembled, already-audited set
            # (the audit ESCALATED record is the durable escalation of record).
            if self._review_router is not None and result.requires_human_review:
                with contextlib.suppress(Exception):
                    self._review_router.route(result, maker=actor, tenant=principal.tenant)
            return result

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _build_recommendations(
        self,
        ranking: Ranking,
        elig_by_id: dict[str, EligibilityResult],
        consent_by_id: dict[str, ConsentDecision],
        request: RecommendationRequest,
        actor: str,
    ) -> tuple[Recommendation, ...]:
        top = ranking.offers[: max(request.max_recommendations, 1)]
        out: list[Recommendation] = []
        for ranked in top:
            explanation = self._explain(request, ranked)
            out.append(
                Recommendation(
                    offer_id=ranked.offer_id,
                    name=ranked.name,
                    kind=ranked.kind,
                    rank=ranked.rank,
                    score=ranked.score,
                    propensity=ranked.propensity,
                    value_score=ranked.value_score,
                    channel=ranked.channel,
                    eligibility=elig_by_id[ranked.offer_id],
                    consent=consent_by_id[ranked.offer_id],
                    explanation=explanation,
                    citations=ranked.citations,
                )
            )
        return tuple(out)

    def _rules(self, request: RecommendationRequest) -> tuple[Any, ...]:
        try:
            return tuple(self._recs.eligibility_rules(request.market, request.vertical))
        except Exception:  # noqa: BLE001 - rules are best-effort; absence => no extra gating
            return ()

    def _consent_decisions(
        self,
        offers: tuple[Offer, ...],
        request: RecommendationRequest,
        principal: Principal,
    ) -> tuple[ConsentDecision, ...]:
        """Ask marketing-compliance-gate once per selected channel and map its wire answer into
        output evidence.

        Calls are cached by channel within one recommendation request. Any inability to obtain a
        decision is represented as a cited refusal, never as permission and never as a private
        fallback to BigQuery rows.
        """
        by_channel: dict[ConsentChannel, Any] = {}
        decisions: list[ConsentDecision] = []
        for offer in offers:
            channel = self._resolve_consent_channel(offer, request.channel)
            if channel is None:
                decisions.append(
                    ConsentDecision(
                        offer_id=offer.id,
                        allowed=False,
                        reason=(
                            "offer names an unknown required consent channel "
                            f"{offer.required_consent_channel!r}; suppressed (fail-closed)"
                        ),
                    )
                )
                continue
            if channel not in by_channel:
                query = ConsentQuery(
                    tenant=principal.tenant,
                    subject_id=request.customer_id,
                    purpose="marketing",
                    channel=self._wire_channel(channel),
                    market=request.market.value,
                    vertical=request.vertical.value,
                )
                try:
                    by_channel[channel] = self._consent.decide(query)
                except Exception as exc:  # noqa: BLE001 - no consent answer can become permission
                    by_channel[channel] = None, str(exc)

            answer = by_channel[channel]
            if isinstance(answer, tuple):
                citation = Citation(
                    source_id=f"consent-unavailable:{request.customer_id}:{channel.value}",
                    source_type=SourceType.CONSENT,
                    title="Consent decision unavailable",
                    snippet=answer[1],
                )
                decisions.append(
                    ConsentDecision(
                        offer_id=offer.id,
                        allowed=False,
                        channel=channel,
                        reason=f"consent unavailable on {channel.value}; suppressed (fail-closed)",
                        citation=citation,
                    )
                )
                continue

            expected = {
                "tenant": principal.tenant,
                "subject_id": request.customer_id,
                "purpose": "marketing",
                "channel": self._wire_channel(channel),
                "market": request.market.value,
                "vertical": request.vertical.value,
            }
            mismatches = tuple(
                key for key, value in expected.items() if getattr(answer, key, None) != value
            )
            permitted = answer.allowed and not answer.denying_reasons and not mismatches
            wire_citation = answer.citations[0] if answer.citations else None
            record_detail = (
                f"; underlying_record={wire_citation.source_id}" if wire_citation else ""
            )
            citation = (
                Citation(
                    source_id=answer.id,
                    source_type=SourceType.CONSENT,
                    title="marketing-compliance-gate consent and preference decision",
                    snippet=(
                        f"as_of={answer.as_of or 'server-now'}; outcome={answer.outcome}"
                        f"{record_detail}"
                    ),
                )
                if wire_citation
                else Citation(
                    source_id=answer.id,
                    source_type=SourceType.CONSENT,
                    title="Consent and preference decision",
                    snippet=answer.explanation,
                )
            )
            reasons = ", ".join(answer.reasons) or answer.outcome or "unknown"
            if mismatches:
                reasons = f"response_scope_mismatch:{','.join(mismatches)}; {reasons}"
            elif answer.denying_reasons:
                reasons = f"denying_reasons_present; {reasons}"
            decisions.append(
                ConsentDecision(
                    offer_id=offer.id,
                    allowed=permitted,
                    channel=channel,
                    reason=(
                        f"marketing-compliance-gate consent {answer.outcome or 'unknown'} on "
                        f"{channel.value}: {reasons}"
                    ),
                    citation=citation,
                    decision_id=answer.id,
                    as_of=answer.as_of,
                )
            )
        return tuple(decisions)

    @staticmethod
    def _resolve_consent_channel(
        offer: Offer, requested: ConsentChannel | None
    ) -> ConsentChannel | None:
        if offer.required_consent_channel:
            try:
                return ConsentChannel(offer.required_consent_channel)
            except ValueError:
                return None
        return requested or ConsentChannel.IN_APP

    @staticmethod
    def _wire_channel(channel: ConsentChannel) -> str:
        return {
            ConsentChannel.IN_APP: "chat",
            ConsentChannel.PHONE: "voice",
        }.get(channel, channel.value)

    def _propensity(
        self, customer: Customer, offers: tuple[Offer, ...]
    ) -> dict[str, PropensitySignal]:
        try:
            signals = self._recs.propensity(customer, offers)
            return {s.offer_id: s for s in signals}
        except Exception:  # noqa: BLE001 - degrade to value-only ranking if model unavailable
            return {}

    # ------------------------------------------------------------------ #
    # LLM explanation (explains "why recommended"; never decides the numbers)
    # ------------------------------------------------------------------ #
    def _explain(self, request: RecommendationRequest, ranked: RankedOffer) -> str:
        evidence = self._render_evidence(ranked)
        prompt = (
            f"Explain in one or two sentences why offer '{ranked.name}' is the next-best "
            f"action for this customer in market {request.market.value}, vertical "
            f"{request.vertical.value}. Use ONLY the evidence below; cite source ids you "
            f"used. Do not invent numbers.\n\nEVIDENCE:\n{evidence}"
        )
        response = self._llm.generate(
            LlmRequest(
                messages=(LlmMessage(role="user", content=prompt),),
                response_schema=_EXPLANATION_SCHEMA,
            )
        )
        return self._extract_explanation(response.text, ranked)

    @staticmethod
    def _render_evidence(ranked: RankedOffer) -> str:
        ids = " ".join(f"[{c.source_id} p.{c.page or 1}]" for c in ranked.citations)
        return (
            f"{ids} offer {ranked.name} ({ranked.kind.value}); {ranked.rationale}; "
            f"channel {ranked.channel.value if ranked.channel else 'n/a'}."
        )

    @staticmethod
    def _extract_explanation(text: str, ranked: RankedOffer) -> str:
        try:
            obj = json.loads(text)
            explanation = obj.get("explanation", "")
            if isinstance(explanation, str) and explanation:
                return explanation
        except (json.JSONDecodeError, AttributeError):
            pass
        return (
            f"{ranked.name} ranks #{ranked.rank} (score {ranked.score:.2f}) on propensity and "
            "business value, is eligible and consented. Human review required."
        )

    @staticmethod
    def _summarise(
        request: RecommendationRequest,
        recs: tuple[Recommendation, ...],
        suppressed: tuple[EligibilityResult, ...],
        consent_suppressed: tuple[ConsentDecision, ...],
    ) -> str:
        top = recs[0].name if recs else "(none)"
        return (
            f"{len(recs)} next-best-action recommendation(s) for customer "
            f"{request.customer_id} in {request.market.value}/{request.vertical.value}; "
            f"top: {top}. {len(suppressed)} offer(s) ineligible, "
            f"{len(consent_suppressed)} suppressed for consent. Human review required."
        )

    # ------------------------------------------------------------------ #
    # Cross-cutting: guardrail, tracing, audit
    # ------------------------------------------------------------------ #
    def _guard(
        self,
        raw_text: str,
        direction: Direction,
        request: RecommendationRequest,
        principal: Principal,
    ) -> None:
        """Redact PII, then guardrail-screen; on block, audit the redacted text and raise.

        The text screened by the guardrail is PII-redacted but keeps the raw request content
        (so an injection attempt is still detectable); the text written to the audit sink is
        additionally pseudonymized, so the internal customer key never lands in the WORM store.
        """
        verdict: GuardrailVerdict = self._guardrail.screen(self._redact(raw_text), direction)
        if not verdict.allowed:
            sanitized = self._for_audit(raw_text, request)
            self._write_audit(
                request,
                principal,
                Decision.BLOCKED,
                redacted_prompt=sanitized if direction is Direction.INPUT else "",
                redacted_response=sanitized if direction is Direction.OUTPUT else "",
                extra_metadata={"reason": verdict.reason, "direction": direction.value},
            )
            raise GuardrailBlockedError(verdict.reason or "guardrail blocked the request")

    def _span(self, name: str, **attrs: str) -> Any:
        try:
            return self._tracer.span(name, **attrs)
        except Exception:  # noqa: BLE001 - tracing must never break the pipeline
            return nullcontext()

    def _record(
        self,
        result: RecommendationSet,
        request: RecommendationRequest,
        principal: Principal,
        customer: Customer,
    ) -> None:
        """Audit the interaction with an already-redacted prompt/response (R1/P-04).

        Both the decision context (which snapshots the customer profile, so a national id in
        an attribute is masked) and the response summary are redacted, and the customer key
        is pseudonymized, before anything is written to the WORM sink.
        """
        self._write_audit(
            request,
            principal,
            Decision.ESCALATED if result.requires_human_review else Decision.ALLOWED,
            redacted_prompt=self._for_audit(self._decision_context(request, customer), request),
            redacted_response=self._for_audit(result.summary, request),
            # Consent citations embed the customer key in their source id / url, so sanitize
            # the citation provenance too: the raw key must not survive into the WORM record.
            citations=self._sanitized_citations(result.citations, request),
            extra_metadata={"n_recommendations": str(len(result.recommendations))},
        )

    def _sanitized_citations(
        self, citations: tuple[Citation, ...], request: RecommendationRequest
    ) -> tuple[Citation, ...]:
        """Pseudonymize the customer key and redact PII in each citation's text fields.

        Provenance (source id, url, title, snippet) can embed the internal customer key (the
        consent record citations do), so it is sanitized before the citations are audited.
        Only the audited copy is sanitized; the returned RecommendationSet keeps raw citations.
        """
        return tuple(
            Citation(
                source_id=self._for_audit(c.source_id, request),
                source_type=c.source_type,
                title=self._for_audit(c.title, request),
                url=self._for_audit(c.url, request),
                page=c.page,
                published_date=c.published_date,
                snippet=self._for_audit(c.snippet, request),
                score=c.score,
            )
            for c in citations
        )

    # ------------------------------------------------------------------ #
    # Redaction boundary helpers (R1/P-04): PII de-identification + key pseudonymization
    # ------------------------------------------------------------------ #
    def _redact(self, text: str) -> str:
        """De-identify PII in ``text`` via the redaction port (safe for model / screening)."""
        return str(self._redaction.redact(text).text)

    def _for_audit(self, text: str, request: RecommendationRequest) -> str:
        """Sanitize free-text for the audit sink: pseudonymize the customer key, then redact.

        The jurisdiction regex will not catch an internal key like ``cust-sg-bank-1``, so the
        customer id is pseudonymized to a stable, non-reversible token first; the redactor
        then masks any national identifier / email / phone. Neither the raw id nor raw PII
        survives into the WORM audit record.
        """
        pseudonymized = text.replace(request.customer_id, self._pseudonym(request.customer_id))
        return str(self._redaction.redact(pseudonymized).text)

    @staticmethod
    def _pseudonym(customer_id: str) -> str:
        """A stable, non-reversible pseudonym for the internal customer key (audit linkage)."""
        digest = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()[:12]
        return f"cust#{digest}"

    @staticmethod
    def _input_context(request: RecommendationRequest) -> str:
        """The inbound request rendered for redaction + INPUT screening (raw id retained)."""
        return (
            f"recommend customer={request.customer_id} market={request.market.value} "
            f"vertical={request.vertical.value}"
        )

    @staticmethod
    def _decision_context(request: RecommendationRequest, customer: Customer) -> str:
        """The decision inputs snapshotted for the audit prompt (redacted by the caller).

        Includes the customer profile so a national identifier held in an attribute is masked
        by the redactor before it can reach the audit sink.
        """
        ctx = (
            f"recommend customer={request.customer_id} market={request.market.value} "
            f"vertical={request.vertical.value}"
        )
        if customer.attributes:
            attrs = ", ".join(f"{k}={v}" for k, v in sorted(customer.attributes.items()))
            ctx = f"{ctx} profile[{attrs}]"
        return ctx

    def _write_audit(
        self,
        request: RecommendationRequest,
        principal: Principal,
        decision: Decision,
        *,
        redacted_prompt: str = "",
        redacted_response: str = "",
        citations: tuple[Any, ...] = (),
        extra_metadata: dict[str, str] | None = None,
    ) -> None:
        metadata: dict[str, str] = {
            "market": request.market.value,
            "vertical": request.vertical.value,
            # Pseudonymized linkage only: never the raw internal customer key.
            "customer": self._pseudonym(request.customer_id),
            "tenant": principal.tenant,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        self._audit.record(
            AuditEvent(
                action="recommend",
                actor=principal.actor,
                decision=decision,
                redacted_prompt=redacted_prompt,
                redacted_response=redacted_response,
                citations=citations,
                metadata=metadata,
            )
        )
