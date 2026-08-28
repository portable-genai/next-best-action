"""Serve the governed tool catalog Mkt5 already declares, over MCP 2026-07-28.

The catalog declared three governed tools and served none of them: there was no MCP server
process anywhere in the fleet. This supplies the callables that answer the existing catalog and
declares nothing new. `hex_service_kit.mcpserve.bind` refuses a mismatch in either direction at
start-up.

**The identity here decides what a caller may be told about a customer, so it is explicit.**
`recommend` takes a `Principal`, and MCP stdio verifies no end user. The principal constructed
below is a SERVICE caller carrying NO entitlement principals and no tenant, so every downstream
consent and eligibility check sees an empty scope and fails closed. That is a real limitation
and the correct one: filling those fields to make a recommendation come back would be
manufacturing an authorization decision the transport cannot support.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit import mcpserve
from hex_service_kit.identity import Principal

from ..config import build_container
from ..domain.models import Market, RecommendationRequest, RetrievalQuery, Vertical

#: The tools this module answers, as data, so a test can hold it against the catalog.
HANDLER_NAMES: tuple[str, ...] = ("list_offers", "search_policy_corpus", "recommend")


def _market_vertical(arguments: dict[str, Any]) -> tuple[Market, Vertical]:
    return Market(str(arguments.get("market", ""))), Vertical(str(arguments.get("vertical", "")))


def build_handlers(actor: str) -> dict[str, mcpserve.Handler]:
    """Bind each declared tool to the service or port that already performs it."""
    principal = Principal(subject=actor, principals=(), tenant="", source="mcp")

    def list_offers(**arguments: Any) -> Any:
        market, vertical = _market_vertical(arguments)
        return build_container().recommendation.catalog(market, vertical)

    def search_policy_corpus(**arguments: Any) -> Any:
        market, vertical = _market_vertical(arguments)
        return build_container().knowledge_base.search(
            RetrievalQuery(
                text=str(arguments.get("query", "") or ""),
                top_k=int(arguments.get("top_k") or 5),
                market=market,
                vertical=vertical,
            )
        )

    def recommend(**arguments: Any) -> Any:
        from ..api.app import make_recommendation_service

        market, vertical = _market_vertical(arguments)
        request = RecommendationRequest(
            customer_id=str(arguments.get("customer_id", "") or ""),
            market=market,
            vertical=vertical,
            max_recommendations=int(arguments.get("max_recommendations") or 3),
        )
        return make_recommendation_service().recommend(request, principal)

    return {
        "list_offers": list_offers,
        "search_policy_corpus": search_policy_corpus,
        "recommend": recommend,
    }


def build_server(actor: str, *, with_audit_tools: bool = True) -> Any:
    """Build the MCP server for Mkt5's catalog, refusing on any catalog/handler mismatch."""
    container = build_container()
    return mcpserve.build_server(
        name="next-best-action",
        version=str(getattr(container.settings, "version", "") or "0.0.1"),
        catalog=container.tool_catalog,
        handlers=build_handlers(actor),
        audit_store=getattr(container, "audit", None) if with_audit_tools else None,
    )
