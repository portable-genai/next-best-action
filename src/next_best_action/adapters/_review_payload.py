"""Shared conversion from an escalated recommendation set to an ``review-kit`` Review payload.

Lives in the adapter layer (not the pure domain) because it depends on the kit. This is the
redact-before-wire boundary for rule R8 (R1 / P-04): the customer descriptor, summary and citation
provenance are scrubbed before they leave the process, so no raw customer identifier reaches
human-review-console. D5 is the only per-customer marketing vertical, so redact-before-wire is
load-bearing here, not defensive: the internal customer key is pseudonymized to a stable,
non-reversible token (the same scheme the audit sink uses, so a checker can still correlate) and
every jurisdiction's national id plus universal email/phone is masked with the shared ``pii-kit``
rows (the same pack the redaction adapter uses). human-review-console redacts again before its own
audit write (defense in depth).

The maker (the agent/operator that originated the set) and the ``tenant`` are asserted here and
trusted by human-review-console because this is an authenticated S2S caller; the ``tenant`` is the
server-verified tenant threaded from the caller's :class:`Principal`, never a client-asserted one.
"""

from __future__ import annotations

import hashlib
import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import RecommendationSet, Severity

# Cap the citations carried on the wire: enough to let a reviewer trace the set without copying
# the entire evidence set into the review console.
_MAX_CITATIONS = 8

# The review console is a shared sink: a set for an SG customer may still quote an HK id, so the
# payload is scrubbed against every jurisdiction's national ids plus universal email/phone,
# regardless of which market configured this producer.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

# The top recommendation's combined (propensity x business-value x eligibility) score is the
# deterministic priority of the customer-facing action: a stronger, more likely-to-be-actioned
# recommendation is the more consequential one to get the human sign-off right. Bands are ordered
# weakest -> strongest and mapped by ascending threshold on that 0..1 score.
_SEVERITY_THRESHOLDS: tuple[tuple[float, Severity], ...] = (
    (0.85, Severity.CRITICAL),
    (0.70, Severity.HIGH),
    (0.45, Severity.MEDIUM),
)
# Dual control (four-eyes) for the strongest customer-facing pushes.
_DUAL_CONTROL_BANDS = (Severity.HIGH, Severity.CRITICAL)


def _pseudonym(customer_id: str) -> str:
    """A stable, non-reversible pseudonym for the internal customer key (audit/console linkage).

    Mirrors ``RecommendationService._pseudonym`` so a checker can correlate a routed review with
    the WORM audit record without either side ever carrying the raw key.
    """
    digest = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()[:12]
    return f"cust#{digest}"


def _scrub(text: str, customer_id: str) -> str:
    """Pseudonymize the internal customer key, then mask national ids / email / phone.

    The jurisdiction regexes will not catch an internal key like ``cust-sg-bank-1`` (the consent
    citations embed it in their source id / url), so it is pseudonymized first; ``pii-kit`` then
    masks any genuine identifier. Neither the raw key nor raw PII survives onto the wire.
    """
    pseudonymized = text.replace(customer_id, _pseudonym(customer_id)) if customer_id else text
    return re.sub(r"\s+", " ", pii_redact(pseudonymized, _ALL_PATTERNS)).strip()


def _top_score(result: RecommendationSet) -> float:
    top = result.top
    return top.score if top is not None else 0.0


def _severity(result: RecommendationSet) -> Severity:
    """Map the top recommendation's deterministic score to a review severity band."""
    score = _top_score(result)
    for threshold, band in _SEVERITY_THRESHOLDS:
        if score >= threshold:
            return band
    return Severity.LOW


def _kit_citations(result: RecommendationSet) -> tuple[KitCitation, ...]:
    customer_id = result.customer_id
    seen: set[str] = set()
    out: list[KitCitation] = []
    for c in result.citations:
        source_id = _scrub(c.source_id, customer_id)
        if source_id in seen:
            continue
        seen.add(source_id)
        out.append(
            KitCitation(
                source_id=source_id,
                title=_scrub(c.title, customer_id),
                snippet=_scrub(c.snippet, customer_id),
            )
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def recommendation_set_to_review(
    result: RecommendationSet, *, maker: str, tenant: str = ""
) -> Review:
    """Build the review a producer submits to human-review-console when a recommendation set
    escalates.
    """
    customer_id = result.customer_id
    pseudonym = _pseudonym(customer_id)
    descriptor = (
        f"Next-best-action recommendations for customer {pseudonym} in "
        f"{result.market.value}/{result.vertical.value}"
    )
    top = result.top
    summary = (
        f"recommendations={len(result.recommendations)}; "
        f"suppressed={len(result.suppressed)}; "
        f"consent_suppressed={len(result.consent_suppressed)}; "
        f"top={top.name if top is not None else '(none)'}"
    )
    severity = _severity(result)
    dual = severity in _DUAL_CONTROL_BANDS
    return Review(
        action=f"nba_recommendation:{result.vertical.value}",
        # The descriptor is built from the pseudonym, never the raw key; scrub again for defense.
        subject=_scrub(descriptor, customer_id),
        maker=maker,
        tenant=tenant,
        summary=_scrub(summary, customer_id),
        severity=severity.value,
        required_approvals=2 if dual else 1,
        sod_group="nba-maker-checker",
        # A pseudonymized case ref: the raw customer key (which the set id embeds) never reaches
        # the console.
        case_ref=pseudonym,
        citations=_kit_citations(result),
    )
