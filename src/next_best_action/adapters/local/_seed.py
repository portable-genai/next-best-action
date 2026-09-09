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

from ... import demo_book
from ...domain.models import (
    Citation,
    ConsentChannel,
    ConsentRecord,
    ConsentStatus,
    Customer,
    EligibilityRule,
    Market,
    Offer,
    RetrievedPassage,
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
# The catalog, the rules and the customers are DERIVED from the shipped book rather than
# restated here. They used to be three literals in this file and four tables in BigQuery,
# with nothing connecting them: a change here moved what the demo showed and left what the
# deployment would serve exactly as it was. The book is now the one source, and these names
# stay so the consent stand-in and the eval gate keep reading what they always read.
def _catalog_from_book() -> dict[_Key, tuple[Offer, ...]]:
    out: dict[_Key, list[Offer]] = {}
    for row in demo_book.BOOK.rows("offers"):
        if not row.get("active", True):
            continue
        offer = demo_book.to_offer(row)
        out.setdefault((offer.market, offer.vertical), []).append(offer)
    return {key: tuple(sorted(offers, key=lambda o: o.id)) for key, offers in out.items()}


def _rules_from_book() -> dict[_Key, tuple[EligibilityRule, ...]]:
    out: dict[_Key, list[EligibilityRule]] = {}
    for row in demo_book.BOOK.rows("eligibility_rules"):
        if not row.get("active", True):
            continue
        rule = demo_book.to_rule(row)
        out.setdefault((rule.market, rule.vertical), []).append(rule)
    return {key: tuple(sorted(rules, key=lambda r: r.id)) for key, rules in out.items()}


def _customers_from_book() -> dict[str, Customer]:
    return {
        row["customer_id"]: demo_book.to_customer(row) for row in demo_book.BOOK.rows("customers")
    }


OFFER_CATALOG: dict[_Key, tuple[Offer, ...]] = _catalog_from_book()
ELIGIBILITY_RULES: dict[_Key, tuple[EligibilityRule, ...]] = _rules_from_book()

_TENANT = "demo-bank"

CUSTOMERS: dict[str, Customer] = _customers_from_book()


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
    # Both channels granted and nothing held, so every offer in scope reaches the ranking.
    # The first SG persona denies phone and holds an offer, which makes it a good consent
    # case and a useless ordering case: a list of one asserts no order.
    "cust-sg-bank-2": (
        _consent("cust-sg-bank-2", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.SG),
        _consent("cust-sg-bank-2", ConsentChannel.PHONE, ConsentStatus.GRANTED, Market.SG),
    ),
    "cust-au-retail-2": (
        _consent("cust-au-retail-2", ConsentChannel.SMS, ConsentStatus.GRANTED, Market.AU),
        _consent("cust-au-retail-2", ConsentChannel.EMAIL, ConsentStatus.GRANTED, Market.AU),
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
