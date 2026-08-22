"""``mkt-nba`` — the Typer CLI for the D5 Next-Best-Action system.

A thin presentation layer over the domain services. It owns no business logic: every
command builds the wiring from :func:`next_best_action.api.deps.make_recommendation_service`,
invokes one domain service, and pretty-prints the cited result.

Design constraints honoured here:

* **Import-safe.** Importing this module (the ``[project.scripts]`` entry point, or
  ``--help``) must never pull in FastAPI, uvicorn or the Google Cloud SDKs. They are
  imported lazily inside command bodies, so the on-prem / local / test profile (which
  installs no Google Cloud SDK) can still load the CLI.
* **Profile-aware.** ``MKT_NBA_PROFILE`` selects the adapter stack. The ``onprem`` profile
  binds placeholder adapters that raise ``NotImplementedError``; the CLI then fails clearly
  (exit code 2) naming the migration target.
* **Citations are first-class.** Every recommendation prints with source-and-page provenance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..domain.models import Citation, RecommendationSet

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "D5 Next-Best-Action: Recommendations and Cross-Sell — cited next-best-action "
        "recommendations from deterministic eligibility, consent and ranking, generic "
        "across banking and online retail and the JP/AU/SG markets."
    ),
)

_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1
_CLI_ACTOR = "cli:operator"


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors."""
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(f"'{action}' has no adapter wired for profile '{profile}': {exc}", code=_PROFILE_EXIT)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _fmt_citation(c: Citation) -> str:
    page = f" p.{c.page}" if c.page is not None else ""
    st = c.source_type.value if hasattr(c.source_type, "value") else str(c.source_type)
    url = f" — {c.url}" if c.url else ""
    return f"[{c.source_id}, {st}{page}]{url}"


def _echo_citations(citations: tuple[Citation, ...], indent: str = "  ") -> None:
    if not citations:
        typer.secho(f"{indent}(no citations)", fg=typer.colors.YELLOW)
        return
    typer.secho(f"{indent}Citations:", bold=True)
    for c in citations:
        typer.echo(f"{indent}  - {_fmt_citation(c)}")


def _echo_review_banner(requires_review: bool) -> None:
    if requires_review:
        typer.secho(
            "  [HUMAN REVIEW REQUIRED] maker-checker gate — do not surface these offers to "
            "the customer until a qualified operator signs off.",
            fg=typer.colors.YELLOW,
            bold=True,
        )


def _echo_result(result: RecommendationSet) -> None:
    typer.secho(f"\nNEXT-BEST-ACTION: customer {result.customer_id}", bold=True)
    typer.echo(f"  id        : {result.id}")
    typer.echo(f"  market    : {result.market.value}")
    typer.echo(f"  vertical  : {result.vertical.value}")
    _echo_review_banner(result.requires_human_review)

    typer.secho("\n  Summary:", bold=True)
    typer.echo(f"    {result.summary}")

    typer.secho("\n  Recommendations (ranked):", bold=True)
    if not result.recommendations:
        typer.secho(
            "    (none — all candidates ineligible or consent-suppressed)",
            fg=typer.colors.YELLOW,
        )
    for r in result.recommendations:
        channel = r.channel.value if r.channel else "n/a"
        typer.echo(
            f"    {r.rank}. {r.name} [{r.kind.value}] — score {r.score:.2f} "
            f"(propensity {r.propensity:.2f}, value {r.value_score:.2f}, channel {channel})"
        )
        typer.echo(f"        why: {r.explanation}")
        _echo_citations(r.citations, indent="        ")

    if result.suppressed:
        typer.secho("\n  Suppressed (ineligible):", bold=True)
        for e in result.suppressed:
            reason = "; ".join(e.reasons) or "ineligible"
            typer.echo(f"    - {e.offer_id}: {reason}")

    if result.consent_suppressed:
        typer.secho("\n  Suppressed (consent):", bold=True)
        for c in result.consent_suppressed:
            typer.echo(f"    - {c.offer_id}: {c.reason}")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def recommend(
    customer_id: str = typer.Argument(..., help="The customer / shopper id, e.g. cust-sg-bank-1."),
    market: str = typer.Option("SG", "--market", "-m", help="Market: JP | AU | SG."),
    vertical: str = typer.Option(
        "banking", "--vertical", "-v", help="Vertical: banking | online_retail."
    ),
    max_recommendations: int = typer.Option(
        5, "--max", "-n", help="Maximum recommendations to return."
    ),
    channel: str = typer.Option(
        None, "--channel", help="Restrict to one channel: email|sms|push|in_app|phone."
    ),
) -> None:
    """Produce ranked, cited next-best-action recommendations for a customer."""
    from ..api.deps import make_recommendation_service
    from ..domain.identity import Principal
    from ..domain.models import ConsentChannel, Market, RecommendationRequest, Vertical

    # The CLI runs as a local operator principal in the demo-bank tenant (the seed's tenant),
    # so object-level authorization is exercised the same way the API path is: the recommend
    # call takes a verified Principal, never a free-text actor string.
    principal = Principal(subject=_CLI_ACTOR, tenant="demo-bank", source="cli")

    def go() -> RecommendationSet:
        request = RecommendationRequest(
            customer_id=customer_id,
            market=Market(market),
            vertical=Vertical(vertical),
            max_recommendations=max_recommendations,
            channel=ConsentChannel(channel) if channel else None,
        )
        return make_recommendation_service().recommend(request, principal)

    result = _run("recommend", go)
    _echo_result(result)


@app.command("eligibility")
def eligibility(
    customer_id: str = typer.Argument(..., help="The customer / shopper id."),
    market: str = typer.Option("SG", "--market", "-m", help="Market: JP | AU | SG."),
    vertical: str = typer.Option(
        "banking", "--vertical", "-v", help="Vertical: banking | online_retail."
    ),
) -> None:
    """Show the deterministic eligibility outcome for every candidate offer."""
    from ..api.deps import get_container
    from ..domain.eligibility_service import EligibilityService
    from ..domain.models import Market, Vertical

    def go() -> Any:
        container = get_container()
        m, v = Market(market), Vertical(vertical)
        customer = container.recommendation.customer(customer_id, m, v)
        catalog = container.recommendation.catalog(m, v)
        rules = container.recommendation.eligibility_rules(m, v)
        return EligibilityService().evaluate_all(customer, catalog, rules)

    results = _run("eligibility", go)
    typer.secho(f"\nELIGIBILITY: {customer_id} ({market}/{vertical})", bold=True)
    for e in results:
        mark = "ELIGIBLE" if e.eligible else "INELIGIBLE"
        color = typer.colors.GREEN if e.eligible else typer.colors.RED
        typer.secho(f"  {e.offer_id}: {mark}", fg=color)
        for reason in e.reasons:
            typer.echo(f"      - {reason}")


if __name__ == "__main__":  # pragma: no cover
    app()
