"""Built-in, OBVIOUSLY-FICTIONAL synthetic seed for the ``local`` profile.

This is the offline dataset that makes a local run work end to end with no Google Cloud:
customers (shoppers), an offer catalog, per-market/vertical eligibility rules, marketing-
consent records and propensity signals, spanning BOTH verticals (banking AND online retail)
across ALL THREE markets (JP, AU, SG). Every company / product name is invented and nothing
here is real customer data: customer ids are like ``cust-sg-bank-1`` and offers / segments
are fictional.

The data is keyed by (market, vertical) so the local RecommendationPort serves vertical-
and market-specific offers and rules, proving D5 is generic and APAC without any hard-coded
branch in the engines.
"""

from __future__ import annotations

from ...domain.models import (
    Citation,
    ConsentChannel,
    ConsentRecord,
    ConsentStatus,
    Customer,
    EligibilityRule,
    Market,
    Offer,
    OfferKind,
    RetrievedPassage,
    RuleEffect,
    SourceType,
    Vertical,
)

_Key = tuple[Market, Vertical]


def _rule_cit(rid: str, title: str) -> Citation:
    return Citation(
        source_id=rid,
        source_type=SourceType.ELIGIBILITY_RULE,
        title=title,
        url=f"https://policy.example.test/{rid}",
        snippet=f"{title} (FICTIONAL per-market rule).",
        score=1.0,
    )


def _consent_cit(cid: str, title: str) -> Citation:
    return Citation(
        source_id=cid,
        source_type=SourceType.CONSENT,
        title=title,
        url=f"https://consent.example.test/{cid}",
        snippet=f"{title} (FICTIONAL consent record).",
        score=1.0,
    )


# --------------------------------------------------------------------------- #
# Offer catalog, per (market, vertical) — OBVIOUSLY FICTIONAL
# --------------------------------------------------------------------------- #
OFFER_CATALOG: dict[_Key, tuple[Offer, ...]] = {
    (Market.SG, Vertical.BANKING): (
        Offer(
            id="sg-bank-savings-plus",
            name="SavingsPlus High-Yield Account (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.SG,
            vertical=Vertical.BANKING,
            category="deposits",
            base_value=120.0,
            required_consent_channel="email",
            required_attributes={"kyc": "verified"},
        ),
        Offer(
            id="sg-bank-credit-card",
            name="Merlion Rewards Credit Card (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.SG,
            vertical=Vertical.BANKING,
            category="cards",
            base_value=240.0,
            required_consent_channel="email",
            required_attributes={"kyc": "verified"},
            excluded_if_held=("sg-bank-credit-card",),
        ),
        Offer(
            id="sg-bank-wealth-upgrade",
            name="Priority Wealth Upgrade (FICTIONAL)",
            kind=OfferKind.UPGRADE,
            market=Market.SG,
            vertical=Vertical.BANKING,
            category="wealth",
            base_value=400.0,
            required_consent_channel="phone",
            required_attributes={"kyc": "verified"},
        ),
    ),
    (Market.JP, Vertical.BANKING): (
        Offer(
            id="jp-bank-fx-wallet",
            name="Yen Multi-Currency Wallet (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.JP,
            vertical=Vertical.BANKING,
            category="fx",
            base_value=180.0,
            required_consent_channel="in_app",
            required_attributes={"kyc": "verified"},
        ),
        Offer(
            id="jp-bank-time-deposit",
            name="Sakura Time Deposit (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.JP,
            vertical=Vertical.BANKING,
            category="deposits",
            base_value=90.0,
            required_consent_channel="email",
            required_attributes={"kyc": "verified"},
        ),
    ),
    (Market.AU, Vertical.BANKING): (
        Offer(
            id="au-bank-home-loan",
            name="Outback Variable Home Loan (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.AU,
            vertical=Vertical.BANKING,
            category="lending",
            base_value=520.0,
            required_consent_channel="phone",
            required_attributes={"kyc": "verified", "risk_tier": "low"},
        ),
        Offer(
            id="au-bank-offset",
            name="Smart Offset Account (FICTIONAL)",
            kind=OfferKind.BUNDLE,
            market=Market.AU,
            vertical=Vertical.BANKING,
            category="deposits",
            base_value=140.0,
            required_consent_channel="email",
            required_attributes={"kyc": "verified"},
        ),
    ),
    (Market.SG, Vertical.ONLINE_RETAIL): (
        Offer(
            id="sg-retail-prime-delivery",
            name="ShopMerlion Prime Delivery (FICTIONAL)",
            kind=OfferKind.SERVICE,
            market=Market.SG,
            vertical=Vertical.ONLINE_RETAIL,
            category="membership",
            base_value=60.0,
            required_consent_channel="push",
            stock=None,
        ),
        Offer(
            id="sg-retail-coffee-bundle",
            name="Artisan Coffee Bundle (FICTIONAL)",
            kind=OfferKind.BUNDLE,
            market=Market.SG,
            vertical=Vertical.ONLINE_RETAIL,
            category="grocery",
            base_value=35.0,
            required_consent_channel="email",
            stock=120,
        ),
        Offer(
            id="sg-retail-headphones",
            name="NoiseOff Wireless Headphones (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.SG,
            vertical=Vertical.ONLINE_RETAIL,
            category="electronics",
            base_value=90.0,
            required_consent_channel="push",
            stock=0,  # out of stock => filtered by the candidate engine
        ),
    ),
    (Market.JP, Vertical.ONLINE_RETAIL): (
        Offer(
            id="jp-retail-loyalty-gold",
            name="MidoriMart Gold Loyalty (FICTIONAL)",
            kind=OfferKind.UPGRADE,
            market=Market.JP,
            vertical=Vertical.ONLINE_RETAIL,
            category="membership",
            base_value=70.0,
            required_consent_channel="in_app",
            stock=None,
        ),
        Offer(
            id="jp-retail-bento-box",
            name="Premium Bento Subscription (FICTIONAL)",
            kind=OfferKind.PROMOTION,
            market=Market.JP,
            vertical=Vertical.ONLINE_RETAIL,
            category="grocery",
            base_value=45.0,
            required_consent_channel="email",
            stock=200,
        ),
    ),
    (Market.AU, Vertical.ONLINE_RETAIL): (
        Offer(
            id="au-retail-bnpl",
            name="BoomerangBuy Pay-in-4 (FICTIONAL)",
            kind=OfferKind.SERVICE,
            market=Market.AU,
            vertical=Vertical.ONLINE_RETAIL,
            category="payments",
            base_value=80.0,
            required_consent_channel="sms",
            stock=None,
        ),
        Offer(
            id="au-retail-outdoor-kit",
            name="Trailblazer Outdoor Kit (FICTIONAL)",
            kind=OfferKind.PRODUCT,
            market=Market.AU,
            vertical=Vertical.ONLINE_RETAIL,
            category="outdoor",
            base_value=110.0,
            required_consent_channel="email",
            stock=50,
        ),
    ),
}


# --------------------------------------------------------------------------- #
# Per-market, per-vertical eligibility rules (config + seed, NEVER hard-coded)
# --------------------------------------------------------------------------- #
def _banking_rules(market: Market) -> tuple[EligibilityRule, ...]:
    """Banking = suitability: KYC verified required; high-value lending needs low risk."""
    return (
        EligibilityRule(
            id=f"{market.value.lower()}-bank-kyc",
            market=market,
            vertical=Vertical.BANKING,
            effect=RuleEffect.REQUIRE,
            attribute="kyc",
            value="verified",
            description="Customer KYC must be verified to be offered a banking product.",
            citation=_rule_cit(f"{market.value.lower()}-bank-kyc", "KYC verification rule"),
        ),
        EligibilityRule(
            id=f"{market.value.lower()}-bank-no-lending-if-flagged",
            market=market,
            vertical=Vertical.BANKING,
            effect=RuleEffect.EXCLUDE,
            attribute="credit_flag",
            value="adverse",
            applies_to_category="lending",
            description="Exclude lending offers for customers with an adverse credit flag.",
            citation=_rule_cit(
                f"{market.value.lower()}-bank-no-lending-if-flagged",
                "Adverse-credit lending exclusion",
            ),
        ),
    )


def _retail_rules(market: Market) -> tuple[EligibilityRule, ...]:
    """Online retail = availability + affinity: stock required; opt-out segment excluded."""
    return (
        EligibilityRule(
            id=f"{market.value.lower()}-retail-stock",
            market=market,
            vertical=Vertical.ONLINE_RETAIL,
            effect=RuleEffect.REQUIRE_STOCK,
            description="Stock-gated retail offers must have stock available.",
            citation=_rule_cit(f"{market.value.lower()}-retail-stock", "Availability rule"),
        ),
        EligibilityRule(
            id=f"{market.value.lower()}-retail-no-marketing-optout",
            market=market,
            vertical=Vertical.ONLINE_RETAIL,
            effect=RuleEffect.EXCLUDE,
            attribute="marketing_segment",
            value="opt_out",
            description="Exclude shoppers who opted out of the marketing segment.",
            citation=_rule_cit(
                f"{market.value.lower()}-retail-no-marketing-optout",
                "Marketing opt-out exclusion",
            ),
        ),
    )


ELIGIBILITY_RULES: dict[_Key, tuple[EligibilityRule, ...]] = {}
for _m in (Market.JP, Market.AU, Market.SG):
    ELIGIBILITY_RULES[(_m, Vertical.BANKING)] = _banking_rules(_m)
    ELIGIBILITY_RULES[(_m, Vertical.ONLINE_RETAIL)] = _retail_rules(_m)


# --------------------------------------------------------------------------- #
# Customers / shoppers, keyed by id
# --------------------------------------------------------------------------- #
# Every seeded customer belongs to the OBVIOUSLY-FICTIONAL ``demo-bank`` tenant. The
# ``other-bank`` persona (see adapters/local/identity.py) deliberately owns NO customers, so
# it is the cross-tenant denial-test target: object-level authorization must refuse it access
# to any demo-bank customer. A couple of banking personas also carry a synthetic national
# identifier in ``national_id`` (an SG NRIC / a JP My Number, both fake) so the redact-before-
# audit boundary and the eval's ``pii_safety`` gate are actually exercised end to end.
_TENANT = "demo-bank"

CUSTOMERS: dict[str, Customer] = {
    "cust-sg-bank-1": Customer(
        id="cust-sg-bank-1",
        market=Market.SG,
        vertical=Vertical.BANKING,
        # national_id is a FICTIONAL SG NRIC; it is inert for eligibility (no rule reads it)
        # and exists to prove the redactor masks it before any audit write.
        attributes={
            "kyc": "verified",
            "risk_tier": "low",
            "credit_flag": "clear",
            "national_id": "S1234567A",
        },
        holdings=("sg-bank-savings-plus",),  # already holds savings => suppressed
        affinities={"cards": 0.8, "wealth": 0.6, "deposits": 0.3},
        tenant=_TENANT,
    ),
    "cust-jp-bank-1": Customer(
        id="cust-jp-bank-1",
        market=Market.JP,
        vertical=Vertical.BANKING,
        # national_id is a FICTIONAL but checksum-valid JP My Number (12 digits), to prove
        # the JP redaction pack masks it before any audit write.
        attributes={
            "kyc": "verified",
            "risk_tier": "medium",
            "credit_flag": "clear",
            "national_id": "123456789018",
        },
        holdings=(),
        affinities={"fx": 0.9, "deposits": 0.4},
        tenant=_TENANT,
    ),
    "cust-au-bank-1": Customer(
        id="cust-au-bank-1",
        market=Market.AU,
        vertical=Vertical.BANKING,
        # adverse credit flag => the lending exclusion fires; offset stays eligible.
        # national_id is a FICTIONAL but checksum-valid AU TFN (9 digits); it is inert for
        # eligibility (no rule reads it) and exists so the AU redaction pack is exercised
        # end to end before any audit write, proving pii_safety per market (SG/JP/AU).
        attributes={
            "kyc": "verified",
            "risk_tier": "low",
            "credit_flag": "adverse",
            "national_id": "123456782",
        },
        holdings=(),
        affinities={"lending": 0.7, "deposits": 0.5},
        tenant=_TENANT,
    ),
    "cust-sg-retail-1": Customer(
        id="cust-sg-retail-1",
        market=Market.SG,
        vertical=Vertical.ONLINE_RETAIL,
        attributes={"marketing_segment": "active", "tier": "gold"},
        holdings=(),
        affinities={"electronics": 0.9, "membership": 0.7, "grocery": 0.4},
        tenant=_TENANT,
    ),
    "cust-jp-retail-1": Customer(
        id="cust-jp-retail-1",
        market=Market.JP,
        vertical=Vertical.ONLINE_RETAIL,
        attributes={"marketing_segment": "active", "tier": "silver"},
        holdings=(),
        affinities={"membership": 0.8, "grocery": 0.6},
        tenant=_TENANT,
    ),
    "cust-au-retail-1": Customer(
        id="cust-au-retail-1",
        market=Market.AU,
        vertical=Vertical.ONLINE_RETAIL,
        attributes={"marketing_segment": "active", "tier": "gold"},
        holdings=(),
        affinities={"payments": 0.85, "outdoor": 0.65},
        tenant=_TENANT,
    ),
}


# --------------------------------------------------------------------------- #
# Marketing-consent records, keyed by customer id
# --------------------------------------------------------------------------- #
def _consent(
    customer_id: str, channel: ConsentChannel, status: ConsentStatus, market: Market
) -> ConsentRecord:
    return ConsentRecord(
        customer_id=customer_id,
        channel=channel,
        status=status,
        market=market,
        updated_date="2026-06-01",
        citation=_consent_cit(
            f"consent-{customer_id}-{channel.value}",
            f"Consent {status.value} for {channel.value}",
        ),
    )


CONSENT_RECORDS: dict[str, tuple[ConsentRecord, ...]] = {
    "cust-sg-bank-1": (
        _consent("cust-sg-bank-1", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.SG),
        # phone consent DENIED => the wealth upgrade (requires phone) is consent-suppressed
        _consent("cust-sg-bank-1", ConsentChannel.PHONE, ConsentStatus.DENIED, Market.SG),
    ),
    "cust-jp-bank-1": (
        _consent("cust-jp-bank-1", ConsentChannel.IN_APP, ConsentStatus.GRANTED, Market.JP),
        _consent("cust-jp-bank-1", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.JP),
    ),
    "cust-au-bank-1": (
        _consent("cust-au-bank-1", ConsentChannel.PHONE, ConsentStatus.GRANTED, Market.AU),
        _consent("cust-au-bank-1", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.AU),
    ),
    "cust-sg-retail-1": (
        _consent("cust-sg-retail-1", ConsentChannel.PUSH, ConsentStatus.GRANTED, Market.SG),
        _consent("cust-sg-retail-1", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.SG),
    ),
    "cust-jp-retail-1": (
        _consent("cust-jp-retail-1", ConsentChannel.IN_APP, ConsentStatus.GRANTED, Market.JP),
        _consent("cust-jp-retail-1", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.JP),
    ),
    "cust-au-retail-1": (
        _consent("cust-au-retail-1", ConsentChannel.SMS, ConsentStatus.GRANTED, Market.AU),
        _consent("cust-au-retail-1", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.AU),
    ),
}


# --------------------------------------------------------------------------- #
# Offer / policy corpus passages (the File Search store, A2)
# --------------------------------------------------------------------------- #
def _corpus_passages() -> tuple[RetrievedPassage, ...]:
    passages: list[RetrievedPassage] = []
    for (market, vertical), offers in OFFER_CATALOG.items():
        for offer in offers:
            tag_m, tag_v = market.value, vertical.value
            passages.append(
                RetrievedPassage(
                    text=(
                        f"Offer note ({tag_m}/{tag_v}, FICTIONAL): {offer.name} is a "
                        f"{offer.kind.value} in {offer.category or 'general'}. Suitable for "
                        "customers matching the per-market eligibility rules."
                    ),
                    citation=Citation(
                        source_id=f"policy-{offer.id}",
                        source_type=SourceType.POLICY,
                        title=f"Policy note on {offer.name}",
                        url=f"https://corpus.example.test/policy-{offer.id}",
                        page=1,
                        snippet=offer.name,
                        score=0.8,
                    ),
                    score=0.8,
                    tags=(f"market:{tag_m}", f"vertical:{tag_v}"),
                )
            )
    return tuple(passages)


CORPUS_PASSAGES: tuple[RetrievedPassage, ...] = _corpus_passages()
