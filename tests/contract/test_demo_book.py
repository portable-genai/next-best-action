"""The demo book: one set of rows, served the same way by the laptop store and the managed one.

Pinned here:

* the shipped book is internally consistent, including the rule the managed adapter enforces
  and nothing else checked: every candidate offer has a propensity signal;
* the managed adapter reads only columns the Terraform declares, so a column selected and
  never provisioned fails here rather than on a deployment at the first request;
* the DuckDB store serves exactly the shipped rows and refuses a customer with no tenant;
* propensity is READ rather than computed, on both profiles, so the local profile can no
  longer rank an offer the deployment would refuse to score.

Every check was watched failing first: the propensity completeness rule against a book with
a signal removed, the schema check against a column deleted from the Terraform, and the
parity check against the old computing adapter.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from next_best_action import demo_book
from next_best_action.adapters.gcp import recommendation as managed
from next_best_action.adapters.local.recommendation import LocalRecommendationAdapter
from next_best_action.config import LocalSettings, Settings
from next_best_action.domain.errors import UnknownCustomerError
from next_best_action.domain.models import Market, Vertical

_REPO = Path(__file__).resolve().parents[2]
_TF = _REPO / "infra" / "terraform" / "bigquery.tf"


def _settings() -> Settings:
    base = Settings.load("config/settings.yaml")
    return dataclasses.replace(
        base,
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=":memory:"),
    )


@pytest.fixture
def store() -> LocalRecommendationAdapter:
    adapter = LocalRecommendationAdapter(_settings())
    yield adapter
    adapter.close()


# --------------------------------------------------------------------------- #
# The shipped rows
# --------------------------------------------------------------------------- #
def test_the_shipped_book_is_internally_consistent() -> None:
    demo_book.validate()
    assert len(demo_book.BOOK.rows("customers")) == 6
    assert len(demo_book.BOOK.rows("offers")) == 14
    assert demo_book.BOOK.manifest()["fictional"] is True


def test_a_candidate_offer_without_a_propensity_signal_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule the managed adapter enforces at request time, checked at rest.

    Without it a book can ship a customer whose recommendation works on the laptop and
    refuses on the deployment, and nothing offline would say so.
    """
    real = demo_book.BOOK.rows

    def short(table: str):  # type: ignore[no-untyped-def]
        rows = real(table)
        return rows[1:] if table == "propensity_signals" else rows

    monkeypatch.setattr(demo_book.BOOK, "rows", short)
    with pytest.raises(demo_book.BookError, match="no propensity signal"):
        demo_book.validate()


def test_a_signal_for_an_offer_that_does_not_exist_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = demo_book.BOOK.rows

    def bogus(table: str):  # type: ignore[no-untyped-def]
        rows = real(table)
        if table == "propensity_signals":
            return [*rows, dict(rows[0], offer_id="offer-that-never-existed")]
        return rows

    monkeypatch.setattr(demo_book.BOOK, "rows", bogus)
    with pytest.raises(demo_book.BookError, match="unknown offer"):
        demo_book.validate()


# --------------------------------------------------------------------------- #
# The managed schema
# --------------------------------------------------------------------------- #
def _terraform_tables() -> dict[str, set[str]]:
    text = _TF.read_text(encoding="utf-8")
    blocks = re.findall(
        r'resource\s+"google_bigquery_table"\s+"\w+"\s*\{(.*?)\n\}', text, flags=re.DOTALL
    )
    assert blocks, "no google_bigquery_table blocks found; the regex or the file moved"
    out: dict[str, set[str]] = {}
    for block in blocks:
        table_id = re.search(r'table_id\s*=\s*"(\w+)"', block)
        assert table_id is not None
        out[table_id.group(1)] = set(re.findall(r'name\s*=\s*"(\w+)"', block))
    return out


def test_the_managed_adapter_reads_only_columns_the_terraform_declares() -> None:
    declared = _terraform_tables()
    for table_key, columns in managed.SELECTED_COLUMNS.items():
        table_id = getattr(_settings().recommendation, table_key)
        assert table_id in declared, f"{table_key} -> {table_id!r} is not a Terraform table"
        undeclared = sorted(set(columns) - declared[table_id])
        assert not undeclared, f"{table_id} reads columns Terraform never declares: {undeclared}"


def test_the_book_and_the_terraform_declare_the_same_columns() -> None:
    """One book, one schema. A column in one and not the other is a load that fails.

    The set checked is ``load_order()`` rather than ``TABLES``, so it includes the manifest.
    The loader writes the manifest like any other table and refuses to write anything at all
    when a target table is missing (``scripts/load_demo_book.py`` ``_existing``), so a
    manifest absent from the Terraform is a load that fails before its first row, and
    iterating the repository's own tables cannot see it.
    """
    declared = _terraform_tables()
    for table in demo_book.BOOK.load_order():
        assert table.name in declared, f"the book ships {table.name} and Terraform does not"
        book_columns, tf_columns = sorted(table.columns), sorted(declared[table.name])
        assert book_columns == tf_columns, (
            f"{table.name}: book {book_columns} vs terraform {tf_columns}"
        )


# --------------------------------------------------------------------------- #
# The DuckDB store
# --------------------------------------------------------------------------- #
def test_the_store_serves_the_shipped_customers(store: LocalRecommendationAdapter) -> None:
    for row in demo_book.BOOK.rows("customers"):
        customer = store.customer(
            row["customer_id"], Market(row["market"]), Vertical(row["vertical"])
        )
        assert customer.id == row["customer_id"]
        assert customer.tenant == row["tenant"]
        assert customer.attributes == {
            k: str(v) for k, v in json.loads(row["attributes_json"]).items()
        }


def test_an_unknown_customer_is_refused_by_name(store: LocalRecommendationAdapter) -> None:
    with pytest.raises(UnknownCustomerError, match="unknown customer"):
        store.customer("cust-does-not-exist", Market.SG, Vertical.BANKING)


def test_a_customer_is_scoped_to_its_own_market_and_vertical(
    store: LocalRecommendationAdapter,
) -> None:
    """A customer id is not a capability: the wrong scope is a miss, not a silent hit."""
    with pytest.raises(UnknownCustomerError):
        store.customer("cust-sg-bank-1", Market.JP, Vertical.BANKING)


def test_propensity_is_read_from_the_store_and_matches_the_book(
    store: LocalRecommendationAdapter,
) -> None:
    customer = store.customer("cust-sg-bank-1", Market.SG, Vertical.BANKING)
    offers = store.catalog(Market.SG, Vertical.BANKING)
    assert offers, "the SG banking catalog is empty"
    signals = store.propensity(customer, offers)
    shipped = {
        (row["customer_id"], row["offer_id"]): row["score"]
        for row in demo_book.BOOK.rows("propensity_signals")
    }
    assert {s.offer_id: s.score for s in signals} == {
        offer.id: shipped[(customer.id, offer.id)] for offer in offers
    }


def test_an_offer_with_no_stored_signal_is_refused_rather_than_defaulted(
    store: LocalRecommendationAdapter,
) -> None:
    """Parity with the managed adapter, and the reason propensity stopped being computed.

    The old local adapter derived a score for ANY offer, so the local profile happily ranked
    an offer the deployment refuses to score. Ranking on a default puts a number in front of
    a customer that no model produced.
    """
    customer = store.customer("cust-sg-bank-1", Market.SG, Vertical.BANKING)
    unscored = store.catalog(Market.JP, Vertical.BANKING)
    assert unscored, "the JP catalog is empty, so this proves nothing"
    with pytest.raises(RuntimeError, match="no signal for offers"):
        store.propensity(customer, unscored)


def test_the_store_keeps_the_book_across_a_reopen(tmp_path: Path) -> None:
    base = Settings.load("config/settings.yaml")
    path = str(tmp_path / "book.duckdb")

    def settings() -> Settings:
        return dataclasses.replace(
            base,
            profile="local",
            local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=path),
        )

    first = LocalRecommendationAdapter(settings())
    before = len(first.catalog(Market.SG, Vertical.BANKING))
    first.close()
    second = LocalRecommendationAdapter(settings())
    assert len(second.catalog(Market.SG, Vertical.BANKING)) == before
    second.close()
