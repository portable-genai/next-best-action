"""The shipped demo book: fictional customers, offers, eligibility rules and propensity.

The rows live as newline-delimited JSON under ``next_best_action/data/demo_book/``, one file
per BigQuery table and in that table's column order, so one set of files feeds the DuckDB
store the ``local`` profile reads, the loader that fills the managed dataset, and the tests.
The reading, the overwrite guard and the tenant rule come from
:mod:`hex_service_kit.demobook`; what is here is the part that is about THIS system.

Two things about this book that are decisions rather than data.

**Propensity is stored, not computed.** The local adapter used to derive a score at request
time from the customer's affinity and the offer's value, while the managed adapter has always
read rows and refused to recommend an offer with no signal. So the two profiles disagreed
about what a propensity IS: a function here, a feature table there. In production a model
writes those rows, which makes the managed shape the real one, so the book ships the scores
and both profiles read them. The formula that produced them is recorded in
``scripts/render_demo_book.py`` and the model version on every row says which one.

**Consent is not in this book.** It belongs to `marketing-compliance-gate` and is read from
that service over HTTP under the managed profile. Putting a copy here would give the ranking
engine a second, private answer to a question another system owns.

Everything is fictional. See ``data/demo_book/README.md``.
"""

from __future__ import annotations

import json
from typing import Any

from hex_service_kit.demobook import BookError, NdjsonBook, Table

from .domain.models import (
    Citation,
    Customer,
    EligibilityRule,
    Market,
    Offer,
    OfferKind,
    PropensitySignal,
    RuleEffect,
    SourceType,
    Vertical,
)

#: The tenant the shipped rows carry. The deployment loader rewrites it to whatever the
#: identity adapter resolves there; a row under any other value is invisible, because
#: object authorization is fail-closed.
SHIPPED_TENANT = "demo-bank"

#: The customer that belongs to a DIFFERENT tenant on purpose, if the book ever gains one.
#: Kept as an explicit map so a loader never silently folds a cross-tenant proof row into the
#: main tenant, which would delete the only evidence the isolation gate does anything.
CROSS_TENANT: dict[str, str] = {}

CUSTOMERS = Table(
    name="customers",
    columns=(
        "customer_id",
        "tenant",
        "market",
        "vertical",
        "attributes_json",
        "holdings",
        "affinities_json",
        "updated_at",
    ),
    types={
        "customer_id": "TEXT NOT NULL",
        "tenant": "TEXT NOT NULL",
        "market": "TEXT NOT NULL",
        "vertical": "TEXT NOT NULL",
        "attributes_json": "TEXT NOT NULL",
        "holdings": "TEXT[]",
        "affinities_json": "TEXT NOT NULL",
        "updated_at": "TIMESTAMP NOT NULL",
    },
    primary_key=("customer_id",),
)

OFFERS = Table(
    name="offers",
    columns=(
        "offer_id",
        "name",
        "kind",
        "market",
        "vertical",
        "category",
        "base_value",
        "required_consent_channel",
        "required_attributes_json",
        "excluded_if_held",
        "stock",
        "evidence_summary",
        "active",
    ),
    types={
        "offer_id": "TEXT NOT NULL",
        "name": "TEXT NOT NULL",
        "kind": "TEXT NOT NULL",
        "market": "TEXT NOT NULL",
        "vertical": "TEXT NOT NULL",
        "base_value": "DOUBLE NOT NULL",
        "required_attributes_json": "TEXT NOT NULL",
        "excluded_if_held": "TEXT[]",
        "stock": "BIGINT",
        "evidence_summary": "TEXT NOT NULL",
        "active": "BOOLEAN NOT NULL",
    },
    primary_key=("offer_id",),
)

ELIGIBILITY_RULES = Table(
    name="eligibility_rules",
    columns=(
        "rule_id",
        "market",
        "vertical",
        "effect",
        "attribute",
        "value",
        "applies_to_kind",
        "applies_to_category",
        "description",
        "citation_title",
        "active",
    ),
    types={
        "rule_id": "TEXT NOT NULL",
        "market": "TEXT NOT NULL",
        "vertical": "TEXT NOT NULL",
        "effect": "TEXT NOT NULL",
        "description": "TEXT NOT NULL",
        "citation_title": "TEXT NOT NULL",
        "active": "BOOLEAN NOT NULL",
    },
    primary_key=("rule_id",),
)

PROPENSITY_SIGNALS = Table(
    name="propensity_signals",
    columns=(
        "customer_id",
        "offer_id",
        "market",
        "vertical",
        "score",
        "model_version",
        "computed_at",
    ),
    types={
        "customer_id": "TEXT NOT NULL",
        "offer_id": "TEXT NOT NULL",
        "market": "TEXT NOT NULL",
        "vertical": "TEXT NOT NULL",
        "score": "DOUBLE NOT NULL",
        "computed_at": "TIMESTAMP",
    },
    primary_key=("customer_id", "offer_id"),
)

#: Load order: a referenced table before the rows that reference it.
TABLES = (CUSTOMERS, OFFERS, ELIGIBILITY_RULES, PROPENSITY_SIGNALS)

BOOK = NdjsonBook("next_best_action.data.demo_book", TABLES)


def validate() -> None:
    """The book's own invariants, on top of the shape the kit checks.

    Every rule here is one a hand edit can break and nothing else would notice until a demo:
    a propensity signal for an offer that does not exist, a customer holding an offer that is
    not in the catalog, or an offer with no signal for a customer in its own market, which is
    the case the managed adapter refuses outright.
    """
    BOOK.validate()
    offers = {row["offer_id"]: row for row in BOOK.rows("offers")}
    customers = {row["customer_id"]: row for row in BOOK.rows("customers")}
    if not offers or not customers:
        raise BookError("the book ships no offers or no customers")

    for row in BOOK.rows("propensity_signals"):
        if row["offer_id"] not in offers:
            raise BookError(f"propensity names unknown offer {row['offer_id']!r}")
        if row["customer_id"] not in customers:
            raise BookError(f"propensity names unknown customer {row['customer_id']!r}")
        if not 0.0 <= float(row["score"]) <= 1.0:
            raise BookError(f"propensity score {row['score']} is outside 0..1")

    for row in customers.values():
        for held in row.get("holdings") or []:
            if held not in offers:
                raise BookError(f"{row['customer_id']} holds unknown offer {held!r}")
        if not str(row.get("tenant") or "").strip():
            raise BookError(f"{row['customer_id']} has no tenant; it would fail closed")

    # The managed adapter raises when ANY candidate offer has no signal, so a book that is
    # short one row produces a briefing that works locally and refuses on the deployment.
    scored = {(row["customer_id"], row["offer_id"]) for row in BOOK.rows("propensity_signals")}
    for customer in customers.values():
        scope = (customer["market"], customer["vertical"])
        for offer in offers.values():
            if (offer["market"], offer["vertical"]) != scope or not offer["active"]:
                continue
            if (customer["customer_id"], offer["offer_id"]) not in scored:
                raise BookError(
                    f"no propensity signal for {customer['customer_id']} x {offer['offer_id']}; "
                    "the managed adapter refuses to recommend an offer with no signal"
                )


# --------------------------------------------------------------------------- #
# Row to domain
# --------------------------------------------------------------------------- #
def _mapping(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return {str(k): v for k, v in dict(parsed).items()}


def to_customer(row: dict[str, Any]) -> Customer:
    return Customer(
        id=str(row["customer_id"]),
        market=Market(str(row["market"])),
        vertical=Vertical(str(row["vertical"])),
        attributes={k: str(v) for k, v in _mapping(row.get("attributes_json")).items()},
        holdings=tuple(str(h) for h in row.get("holdings") or ()),
        affinities={k: float(v) for k, v in _mapping(row.get("affinities_json")).items()},
        tenant=str(row.get("tenant") or ""),
    )


def to_offer(row: dict[str, Any]) -> Offer:
    return Offer(
        id=str(row["offer_id"]),
        name=str(row["name"]),
        kind=OfferKind(str(row["kind"])),
        market=Market(str(row["market"])),
        vertical=Vertical(str(row["vertical"])),
        category=str(row.get("category") or ""),
        base_value=float(row.get("base_value") or 0.0),
        required_consent_channel=str(row.get("required_consent_channel") or ""),
        required_attributes={
            k: str(v) for k, v in _mapping(row.get("required_attributes_json")).items()
        },
        excluded_if_held=tuple(str(x) for x in row.get("excluded_if_held") or ()),
        stock=None if row.get("stock") is None else int(row["stock"]),
        citations=(
            Citation(
                source_id=str(row["offer_id"]),
                source_type=SourceType.OFFER_CATALOG,
                title=str(row["name"]),
                snippet=str(row.get("evidence_summary") or "seeded offer catalog"),
            ),
        ),
    )


def to_rule(row: dict[str, Any]) -> EligibilityRule:
    return EligibilityRule(
        id=str(row["rule_id"]),
        market=Market(str(row["market"])),
        vertical=Vertical(str(row["vertical"])),
        effect=RuleEffect(str(row["effect"])),
        attribute=str(row.get("attribute") or ""),
        value=str(row.get("value") or ""),
        applies_to_kind=(
            OfferKind(str(row["applies_to_kind"])) if row.get("applies_to_kind") else None
        ),
        applies_to_category=str(row.get("applies_to_category") or ""),
        description=str(row.get("description") or ""),
        citation=Citation(
            source_id=str(row["rule_id"]),
            source_type=SourceType.ELIGIBILITY_RULE,
            title=str(row.get("citation_title") or row["rule_id"]),
            snippet=str(row.get("description") or "seeded eligibility rule"),
        ),
    )


def to_signal(row: dict[str, Any], offer_name: str, source: str) -> PropensitySignal:
    score = max(0.0, min(1.0, float(row["score"])))
    return PropensitySignal(
        offer_id=str(row["offer_id"]),
        score=score,
        citation=Citation(
            source_id=f"propensity-{row['customer_id']}-{row['offer_id']}",
            source_type=SourceType.PROPENSITY,
            title=f"Propensity signal for {offer_name}",
            snippet=f"{source}, model {row.get('model_version') or 'unversioned'}.",
            score=score,
        ),
    )
