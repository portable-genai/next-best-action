"""BigQuery and Vertex AI implementation of the raw recommendation-input port.

The adapter retrieves facts and model signals only. Eligibility and ranking stay in the
deterministic domain services; consent comes from the separate marketing-compliance-gate-backed
port. The result is replayable outside GCP with local adapters. SDK imports remain lazy for SDK-free
profiles.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from ...config import Settings
from ...domain.errors import UnknownCustomerError
from ...domain.models import (
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
from ._region import resolve_region

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _mapping(value: object) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise ValueError("managed recommendation JSON field must contain an object")
    return {str(key): item for key, item in parsed.items()}


def _strings(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Sequence) or isinstance(parsed, (str, bytes)):
        raise ValueError("managed recommendation list field must contain an array")
    return tuple(str(item) for item in parsed)


class VertexRecommendationAdapter:
    """Read governed inputs from BigQuery and optional online propensity from Vertex AI."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reco = settings.recommendation
        self._bq: Any | None = None

    def _table(self, name: str) -> str:
        project = self._settings.project_id
        dataset = self._reco.bigquery_dataset
        if not _PROJECT_ID.fullmatch(project) or not _IDENTIFIER.fullmatch(dataset):
            raise ValueError("project_id and recommendation.bigquery_dataset must be valid IDs")
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"invalid BigQuery table id {name!r}")
        return f"`{project}.{dataset}.{name}`"

    def _get_bq(self) -> Any:
        region = resolve_region(self._settings)
        if self._bq is None:
            from google.cloud import bigquery  # noqa: PLC0415

            self._bq = bigquery.Client(project=self._settings.project_id, location=region)
        return self._bq

    def _query(
        self, sql: str, parameters: Sequence[tuple[str, str, object]]
    ) -> list[dict[str, Any]]:
        from google.cloud import bigquery  # noqa: PLC0415

        # Annotated, because mypy otherwise infers the element type from the FIRST append and
        # then refuses the second: a scalar parameter could never join a list of array ones.
        # The scalar value is narrowed for the same reason the signature takes object --
        # the caller supplies whatever the SQL needs, and BigQuery accepts exactly these.
        query_parameters: list[Any] = []
        for name, kind, value in parameters:
            if kind == "ARRAY<STRING>":
                query_parameters.append(bigquery.ArrayQueryParameter(name, "STRING", value))
            else:
                if (
                    not isinstance(value, (str, int, float, bool, date, datetime))
                    and value is not None
                ):
                    raise TypeError(
                        f"query parameter {name!r} of kind {kind} is not a BigQuery scalar: "
                        f"{type(value).__name__}"
                    )
                query_parameters.append(bigquery.ScalarQueryParameter(name, kind, value))
        job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
        rows = (
            self._get_bq()
            .query(sql, job_config=job_config, location=resolve_region(self._settings))
            .result()
        )
        return [dict(row.items()) for row in rows]

    @staticmethod
    def _scope(market: Market, vertical: Vertical) -> list[tuple[str, str, object]]:
        return [("market", "STRING", market.value), ("vertical", "STRING", vertical.value)]

    def customer(self, customer_id: str, market: Market, vertical: Vertical) -> Customer:
        rows = self._query(
            "SELECT * FROM "
            + self._table(self._reco.customers_table)
            + " WHERE customer_id=@customer_id AND market=@market AND vertical=@vertical LIMIT 2",
            [("customer_id", "STRING", customer_id), *self._scope(market, vertical)],
        )
        if len(rows) != 1:
            raise UnknownCustomerError(
                f"expected one managed customer row for {customer_id!r}, found {len(rows)}"
            )
        row = rows[0]
        tenant = str(row.get("tenant") or "").strip()
        if not tenant:
            raise ValueError("managed customer row has no tenant partition")
        return Customer(
            id=customer_id,
            market=market,
            vertical=vertical,
            attributes={str(k): str(v) for k, v in _mapping(row.get("attributes_json")).items()},
            holdings=_strings(row.get("holdings")),
            affinities={str(k): float(v) for k, v in _mapping(row.get("affinities_json")).items()},
            tenant=tenant,
        )

    def catalog(self, market: Market, vertical: Vertical) -> tuple[Offer, ...]:
        rows = self._query(
            "SELECT * FROM "
            + self._table(self._reco.offers_table)
            + " WHERE market=@market AND vertical=@vertical AND active=TRUE "
            + "ORDER BY offer_id LIMIT @limit",
            [*self._scope(market, vertical), ("limit", "INT64", self._reco.max_candidates)],
        )
        return tuple(
            Offer(
                id=str(row["offer_id"]),
                name=str(row["name"]),
                kind=OfferKind(str(row["kind"])),
                market=market,
                vertical=vertical,
                category=str(row.get("category") or ""),
                base_value=float(row.get("base_value") or 0.0),
                required_consent_channel=str(row.get("required_consent_channel") or ""),
                required_attributes={
                    str(k): str(v) for k, v in _mapping(row.get("required_attributes_json")).items()
                },
                excluded_if_held=_strings(row.get("excluded_if_held")),
                stock=None if row.get("stock") is None else int(row["stock"]),
                citations=(
                    Citation(
                        source_id=str(row["offer_id"]),
                        source_type=SourceType.OFFER_CATALOG,
                        title=str(row["name"]),
                        snippet=str(row.get("evidence_summary") or "managed offer catalog"),
                    ),
                ),
            )
            for row in rows
        )

    def eligibility_rules(self, market: Market, vertical: Vertical) -> tuple[EligibilityRule, ...]:
        rows = self._query(
            "SELECT * FROM "
            + self._table(self._reco.eligibility_rules_table)
            + " WHERE market=@market AND vertical=@vertical AND active=TRUE ORDER BY rule_id",
            self._scope(market, vertical),
        )
        return tuple(
            EligibilityRule(
                id=str(row["rule_id"]),
                market=market,
                vertical=vertical,
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
                    snippet=str(row.get("description") or "managed eligibility rule"),
                ),
            )
            for row in rows
        )

    def _vertex_propensity(self, customer: Customer, offers: tuple[Offer, ...]) -> dict[str, float]:
        from google.cloud import aiplatform_v1  # noqa: PLC0415

        region = resolve_region(self._settings)
        client = aiplatform_v1.PredictionServiceClient(
            client_options={"api_endpoint": f"{region}-aiplatform.googleapis.com"}
        )
        response = client.predict(
            endpoint=self._reco.propensity_endpoint,
            instances=[{"customer_id": customer.id, "offer_ids": [offer.id for offer in offers]}],
        )
        if not response.predictions:
            raise RuntimeError("Vertex propensity endpoint returned no prediction")
        prediction = dict(response.predictions[0])
        raw = prediction.get("scores")
        if not isinstance(raw, Mapping):
            raise RuntimeError("Vertex prediction must contain an offer_id to score map")
        return {str(key): float(value) for key, value in raw.items()}

    def propensity(
        self, customer: Customer, offers: tuple[Offer, ...]
    ) -> tuple[PropensitySignal, ...]:
        if not offers:
            return ()
        if self._reco.propensity_endpoint:
            scores = self._vertex_propensity(customer, offers)
            source = self._reco.propensity_endpoint
        else:
            rows = self._query(
                "SELECT offer_id, score, model_version FROM "
                + self._table(self._reco.propensity_table)
                + " WHERE customer_id=@customer_id AND market=@market AND vertical=@vertical "
                + "AND offer_id IN UNNEST(@offer_ids)",
                [
                    ("customer_id", "STRING", customer.id),
                    *self._scope(customer.market, customer.vertical),
                    ("offer_ids", "ARRAY<STRING>", [offer.id for offer in offers]),
                ],
            )
            scores = {str(row["offer_id"]): float(row["score"]) for row in rows}
            source = "BigQuery propensity feature table"
        missing = [offer.id for offer in offers if offer.id not in scores]
        if missing:
            raise RuntimeError(f"managed propensity has no signal for offers: {missing}")
        return tuple(
            PropensitySignal(
                offer_id=offer.id,
                score=max(0.0, min(1.0, scores[offer.id])),
                citation=Citation(
                    source_id=f"propensity-{customer.id}-{offer.id}",
                    source_type=SourceType.PROPENSITY,
                    title="Managed propensity signal",
                    snippet=source,
                    score=max(0.0, min(1.0, scores[offer.id])),
                ),
            )
            for offer in offers
        )
