"""EligibilityService — deterministic eligibility / suitability rule evaluation.

The second deterministic engine (see the ``deterministic-domain-service`` skill): pure,
stdlib-only, replayable. Given a customer, a candidate offer and the per-market, per-vertical
eligibility rules, it decides ELIGIBLE / INELIGIBLE and records exactly which rules fired
and why. This is consequential (an ineligible offer must never be recommended), so it is
code, not an LLM call. The LLM only narrates the result afterwards.

The same engine serves both verticals because the *rules* differ, not the code:

* Banking -> **suitability**: REQUIRE rules (KYC verified, risk tier, income band) and
  EXCLUDE rules (e.g. exclude a credit product if the customer is flagged) express whether
  the product is suitable for the customer.
* Online retail -> **availability + affinity**: REQUIRE_STOCK rules express availability;
  REQUIRE/EXCLUDE rules express segment / region gating.

Determinism: same inputs -> same output. No clock, no randomness, no network. Rules are
config + seed (per market/vertical), so adding a market or vertical is data, not code.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Citation,
    Customer,
    EligibilityOutcome,
    EligibilityResult,
    EligibilityRule,
    Offer,
    RuleEffect,
)


@dataclass(frozen=True, slots=True)
class EligibilityService:
    """Pure, deterministic eligibility evaluation against per-market/vertical rules."""

    def evaluate(
        self,
        customer: Customer,
        offer: Offer,
        rules: tuple[EligibilityRule, ...] | list[EligibilityRule],
    ) -> EligibilityResult:
        """Decide whether ``offer`` is eligible for ``customer`` under ``rules``."""
        reasons: list[str] = []
        failed: list[str] = []
        citations: list[Citation] = []

        # Offer-level required attributes (suitability constraints carried on the offer).
        for attr, expected in sorted(offer.required_attributes.items()):
            if customer.attributes.get(attr) != expected:
                failed.append(f"offer:{attr}")
                reasons.append(
                    f"offer requires {attr}={expected!r}; "
                    f"customer has {customer.attributes.get(attr)!r}"
                )

        # Per-market/vertical rules that apply to this offer.
        for rule in rules:
            if not self._rule_applies(rule, customer, offer):
                continue
            ok, reason = self._eval_rule(rule, customer, offer)
            if not ok:
                failed.append(rule.id)
                reasons.append(reason)
                if rule.citation is not None:
                    citations.append(rule.citation)

        outcome = EligibilityOutcome.ELIGIBLE if not failed else EligibilityOutcome.INELIGIBLE
        if outcome is EligibilityOutcome.ELIGIBLE and not reasons:
            reasons = ["all eligibility rules satisfied"]
        return EligibilityResult(
            offer_id=offer.id,
            outcome=outcome,
            reasons=tuple(reasons),
            failed_rule_ids=tuple(failed),
            citations=tuple(citations),
        )

    def evaluate_all(
        self,
        customer: Customer,
        offers: tuple[Offer, ...] | list[Offer],
        rules: tuple[EligibilityRule, ...] | list[EligibilityRule],
    ) -> tuple[EligibilityResult, ...]:
        """Evaluate every offer; returns results in the input order."""
        return tuple(self.evaluate(customer, o, rules) for o in offers)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _rule_applies(rule: EligibilityRule, customer: Customer, offer: Offer) -> bool:
        if rule.market is not customer.market or rule.vertical is not customer.vertical:
            return False
        if rule.applies_to_kind is not None and rule.applies_to_kind is not offer.kind:
            return False
        return not (rule.applies_to_category and rule.applies_to_category != offer.category)

    @staticmethod
    def _eval_rule(rule: EligibilityRule, customer: Customer, offer: Offer) -> tuple[bool, str]:
        if rule.effect is RuleEffect.REQUIRE_STOCK:
            ok = offer.stock is None or offer.stock > 0
            return ok, ("" if ok else f"rule {rule.id}: offer out of stock")
        actual = customer.attributes.get(rule.attribute)
        if rule.effect is RuleEffect.REQUIRE:
            ok = actual == rule.value
            return ok, (
                ""
                if ok
                else f"rule {rule.id}: requires {rule.attribute}={rule.value!r}, got {actual!r}"
            )
        # EXCLUDE: customer attribute equal to the value disqualifies the offer.
        ok = actual != rule.value
        return ok, (
            "" if ok else f"rule {rule.id}: excluded because {rule.attribute}={rule.value!r}"
        )
