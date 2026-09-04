"""Local ConsentPort: deterministic synthetic stand-in for marketing-compliance-gate.

It uses the same ``consent-preference-kit`` query and decision types as the managed service.
The fictional fixture rows remain local demo data, but the recommendation domain no longer
owns a second consent engine or a second wire contract.
"""

from __future__ import annotations

import hashlib

from consent_preference_kit import (
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    Citation,
    ConsentDecision,
    ConsentQuery,
)

from ...config import Settings
from ...domain.models import ConsentChannel, ConsentStatus
from ._seed import CONSENT_RECORDS, CUSTOMERS

_WIRE_TO_LOCAL = {
    "email": ConsentChannel.EMAIL,
    "sms": ConsentChannel.SMS,
    "push": ConsentChannel.PUSH,
    "chat": ConsentChannel.IN_APP,
    "voice": ConsentChannel.PHONE,
}


def _decision_id(query: ConsentQuery, outcome: str, reasons: tuple[str, ...]) -> str:
    material = "|".join(
        (
            query.tenant,
            query.subject_id,
            query.purpose,
            query.channel,
            query.market,
            query.vertical,
            query.as_of,
            outcome,
            ",".join(reasons),
        )
    )
    return "cd-" + hashlib.sha256(material.encode()).hexdigest()[:20]


class LocalConsentAdapter:
    """Answer from fictional rows and deny every missing, mismatched, or unknown state."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        customer = CUSTOMERS.get(query.subject_id)
        channel = _WIRE_TO_LOCAL.get(query.channel)
        record = next(
            (row for row in CONSENT_RECORDS.get(query.subject_id, ()) if row.channel is channel),
            None,
        )
        reasons: tuple[str, ...]
        if customer is None or not query.tenant or customer.tenant != query.tenant:
            outcome, reasons = OUTCOME_DENIED, ("tenant_unresolved",)
        elif (
            query.purpose != "marketing"
            or query.market != customer.market.value
            or query.vertical != customer.vertical.value
            or (record is not None and record.market.value != query.market)
        ):
            outcome, reasons = OUTCOME_DENIED, ("market_consent_rule_unsatisfied",)
        elif channel is None or record is None or record.status is ConsentStatus.UNKNOWN:
            outcome, reasons = OUTCOME_DENIED, ("consent_unknown",)
        elif record.status is ConsentStatus.GRANTED:
            outcome, reasons = OUTCOME_ALLOWED, ("consent_granted", "channel_opted_in")
        else:
            outcome, reasons = OUTCOME_DENIED, ("channel_opted_out",)

        citation = Citation(
            source_id=(
                record.citation.source_id if record and record.citation else "consent-unknown"
            ),
            title=(record.citation.title if record and record.citation else "Consent unavailable"),
            snippet=(
                record.citation.snippet
                if record and record.citation
                else "No matching fictional consent record."
            ),
        )
        return ConsentDecision(
            id=_decision_id(query, outcome, reasons),
            tenant=query.tenant,
            subject_id=query.subject_id,
            purpose=query.purpose,
            channel=query.channel,
            outcome=outcome,
            reasons=reasons,
            market=query.market,
            vertical=query.vertical,
            as_of=query.as_of,
            explanation="; ".join(reasons),
            citations=(citation,),
        )
