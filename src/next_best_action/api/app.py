"""FastAPI app — thin HTTP boundary over the domain services.

Owns no business logic: it translates a request into a domain call and serialises the cited
result with ``to_jsonable``. Heavy / cloud imports stay lazy so importing this module under
the local profile needs no Google Cloud SDK.

Identity is server-verified. Every route depends on :data:`CurrentPrincipal`, so the audit
actor comes from the active :class:`IdentityPort` adapter (local persona, IAP assertion, or
on-prem IdP), never from the request body. The embedding-surface controls (env-driven CORS
allowlist + CSP ``frame-ancestors``) let the UI drop into a client's existing web app.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from hex_service_kit import cors_allowlist
from hex_service_kit.web import add_loopback_exposure_guard

from ..config import Settings, end_user_auth_kind
from ..domain.errors import (
    AuthorizationError,
    GuardrailBlockedError,
    NoCandidatesError,
    UnknownCustomerError,
)
from ..domain.identity import IdentityError
from ..domain.models import ConsentChannel, Market, RecommendationRequest, Vertical
from ..domain.serialization import to_jsonable
from ..envread import read_env_setting
from ..ports.identity import VERIFIED
from . import deps
from .deps import make_recommendation_service
from .schemas import AgentCardModel, HealthModel, RecommendRequestModel
from .security import CurrentPrincipal

_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Embedding-surface controls. In secure/embedded mode the app is served same-origin via the
# parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone dev case,
# MKT_NBA_CORS_ORIGINS is an explicit per-tenant allowlist (never "*"). MKT_NBA_FRAME_ANCESTORS
# is the CSP frame-ancestors allowlist of parent origins permitted to iframe the UI.
_FRAME_ANCESTORS_ENV = "MKT_NBA_FRAME_ANCESTORS"
_CORS_ORIGINS_ENV = "MKT_NBA_CORS_ORIGINS"

_LOGGER = logging.getLogger(__name__)


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a SANDBOXED iframe presents the origin
#: ``null``, so allowing it hands framing and credentialed cross-origin rights to any page able
#: to open one. ``'*'`` is what a quoted Terraform variable or a YAML string renders, and ``*.*``
#: is a host pattern matching every name with a dot in it. The same set is refused on the
#: document half, in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(values: Sequence[str], env_name: str) -> None:
    """Refuse a resolved origin policy that names a wildcard, at boot rather than per request.

    Both allowlists were resolved carefully in three states and then handed on verbatim, with
    the "never ``*``" rule living only in the comment above and in the runbook. A comment does
    not fail a build: ``frame-ancestors *`` lets ANY page frame the console, and ``*`` in the
    CORS allowlist grants every origin on the internet the trust the allowlist exists to
    restrict, on responses that carry credentials.

    Any token CONTAINING ``*`` is refused, not only a bare one. ``https://*.client.example``
    is a real CSP host-source wildcard covering every subdomain, including whichever one an
    attacker manages to register, and an allowlist is only worth having when each entry names
    an origin somebody decided to trust.

    The character test is necessary and not sufficient, so :data:`_WILDCARD_TOKENS` covers the
    spellings that carry no asterisk and behave as one anyway. A real origin never contains the
    character and is never one of those tokens, so this refuses nothing a deployment could
    correctly hold.
    """
    offending = [value for value in values if "*" in value or value in _WILDCARD_TOKENS]
    if offending:
        raise ValueError(
            f"{env_name} resolved to {offending}: the origin policy must never contain a "
            "wildcard. Name the exact parent origins that may frame or call this service, or "
            f"unset {env_name} to keep the restrictive default."
        )


def _frame_ancestors(raw: str | None) -> str:
    """Three-state read of ``MKT_NBA_FRAME_ANCESTORS``; an emptied value REFUSES all framing.

    Unset keeps the shipped ``'self'``. A value naming no origin would emit the header
    ``Content-Security-Policy: frame-ancestors`` with an EMPTY directive, which is a CSP parse
    error, so browsers dropped the directive; and the ``== "'self'"`` branch below was skipped
    too, so no ``X-Frame-Options`` went out either and the clickjacking control disappeared
    entirely. An operator who empties the allowlist means "nobody may frame this", which is
    spelled ``'none'``, so that is what the emptied state now produces: the most restrictive
    value, logged, rather than a silently absent header.

    A value that DOES name something is used as given, once :func:`_refuse_wildcard` has
    established that it names origins rather than everybody.
    """
    if raw is None:
        return "'self'"
    normalised = " ".join(raw.split())
    if not normalised:
        _LOGGER.warning(
            "%s is set to an empty value, which names no permitted parent origin: emitting "
            "frame-ancestors 'none' (no framing at all). Unset it to take the 'self' default.",
            _FRAME_ANCESTORS_ENV,
        )
        return "'none'"
    _refuse_wildcard(normalised.split(), _FRAME_ANCESTORS_ENV)
    return normalised


# ``.raw`` and not ``.value``: this is one of the few reads that needs the UNSTRIPPED string,
# because :func:`_frame_ancestors` distinguishes all three states itself and ``None`` is what
# tells it "nobody configured an allowlist". Sourcing it from the commons reader keeps the
# shape out of the scanner's sights without pretending the three states are two.
_FRAME_ANCESTORS = _frame_ancestors(read_env_setting(_FRAME_ANCESTORS_ENV).raw)

# The two frame-ancestors policies the pre-CSP header can also express.
_LEGACY_FRAME_OPTIONS = {"'self'": "SAMEORIGIN", "'none'": "DENY"}


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*"; the localhost dev fallback applies ONLY under a
    DELIBERATELY chosen local profile (shared hex-service-kit rule).

    Keyed on ``exposure_profile``, not ``profile``: granting dev origins is a relaxation, so a
    run that never named a profile must not look like ``local`` here (see
    ``config.ProfileChoice``).

    The commons resolver used to document that it never returns ``*`` and then return what the
    variable said, so :func:`_refuse_wildcard` is what turned that documented rule into a
    refusal. It now refuses the same union itself, which is why the local rule runs FIRST, on
    the raw configured value, rather than on what the resolver hands back: on the old order the
    commons raised its own ``InsecureCorsError`` before this module's rule was reached, and the
    policy changed owner without anybody editing it. Refusing on the way in keeps
    :func:`_refuse_wildcard` the one authority over both allowlists, with one exception type
    and one message naming the variable to fix, and leaves the commons check as an unreachable
    backstop.
    """
    configured = read_env_setting(_CORS_ORIGINS_ENV).value
    _refuse_wildcard(
        [origin.strip() for origin in configured.split(",") if origin.strip()], _CORS_ORIGINS_ENV
    )
    return cors_allowlist(
        deps.get_container().settings.exposure_profile,
        origins_env=_CORS_ORIGINS_ENV,
        dev_origins=tuple(_DEV_ORIGINS),
    )


app = FastAPI(
    title="D5 Next-Best-Action: Recommendations and Cross-Sell",
    version="0.1.0",
    description=(
        "Cited next-best-action recommendations from deterministic eligibility, consent and "
        "ranking, generic across banking and online retail and the JP/AU/SG markets."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Any:
    """Emit embedding-surface headers: CSP frame-ancestors (who may iframe the UI).

    ``X-Frame-Options`` is the pre-CSP equivalent, so it accompanies the two policies it can
    express: ``'self'`` maps to ``SAMEORIGIN`` and ``'none'`` to ``DENY``. A named allowlist has
    no ``X-Frame-Options`` spelling, so none is sent there rather than one that contradicts the
    CSP.
    """
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if deps.get_container().settings.exposure_profile in {"gcp", "platform", "onprem"}:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    legacy = _LEGACY_FRAME_OPTIONS.get(_FRAME_ANCESTORS)
    if legacy is not None:
        response.headers["X-Frame-Options"] = legacy
    return response


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme, the seeded
#      persona adapter refuses to construct, and every end-user route answers 401; but
#      /healthz, /v1/personas and the agent card would still answer a stranger, and a
#      deployment in that state has no business being reachable at all. It is also the one
#      case where a settings file that bound a verifying adapter must NOT buy the relaxation:
#      unset is not consent, whatever the binding says;
#   2. the identity adapter the ACTIVE binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on the X-Dev-Persona header the caller wrote (client-asserted)
#      and the on-premises placeholder resolves nobody at all (unimplemented); neither
#      authenticates anyone, so neither may switch this off. Read from the binding rather than
#      from the profile string, so a client that rebinds ``onprem`` to its own verifying IdP
#      adapter is answered about the adapter it actually runs.
#: Read the same way ``healthz`` reads it, so the posture the guard is built with is the one
#: the service reports, and a re-import under a different profile rebuilds both together.
_SETTINGS = Settings.load()
_END_USER_AUTHENTICATED = _SETTINGS.profile_explicit and end_user_auth_kind(_SETTINGS) == VERIFIED

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline above and before any route or dependency runs. Bound to the
# APP OBJECT, because there is no entry point to put it in: the Dockerfile CMD is
# `exec uvicorn next_best_action.api.app:app --host 0.0.0.0 --port ${PORT}` and the Makefile
# `run-api` target serves the same object, so nothing in this repo ever reached a start-up
# bind guard. GET /v1/personas served the full seeded-persona list (subjects, tenants and
# entitlement groups) to any LAN peer. Do not delete this: without it the container's own CMD
# re-opens that hole.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    # The explicit opt-in an operator sets to accept the exposure, named for this repo the way
    # the rest of its variables are (MKT_NBA_*).
    insecure_demo_env="MKT_NBA_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=_SETTINGS.exposure_profile,
)


@app.get("/healthz", response_model=HealthModel)
def healthz() -> HealthModel:
    settings = Settings.load()
    return HealthModel(
        status="ok",
        # The EXPOSURE profile, so a run that never named one reports "unconfigured" rather
        # than the "local" that would switch the UI's persona picker on.
        profile=settings.exposure_profile,
        market=settings.market,
        vertical=settings.vertical,
    )


@app.get(
    "/.well-known/agent-card.json",
    response_model=AgentCardModel,
    tags=["governance"],
)
def agent_card() -> AgentCardModel:
    """Serve the A2A AgentCard for this agent (Hrz3 discovery, rule R4).

    Pure and identity-agnostic: the card advertises the agent's governed skills so a peer
    agent or the registry sees one capability surface. Built from ``agent.agent_card`` with no
    ADK import.
    """
    from ..agent.agent_card import build_agent_card

    return AgentCardModel.from_domain(build_agent_card(deps.get_container().settings))


@app.get("/v1/personas")
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity
    (and thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure
    profiles resolve identity from the IAP assertion, so this returns an empty list, and so
    does a run that never named a profile: the persona adapter refuses to construct there.
    """
    try:
        identity = deps.get_container().identity
    except IdentityError:
        return []
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


def _to_request(body: RecommendRequestModel) -> RecommendationRequest:
    channel = ConsentChannel(body.channel) if body.channel else None
    return RecommendationRequest(
        customer_id=body.customer_id,
        market=Market(body.market),
        vertical=Vertical(body.vertical),
        max_recommendations=body.max_recommendations,
        channel=channel,
    )


@app.post("/v1/recommend")
def recommend(body: RecommendRequestModel, principal: CurrentPrincipal) -> dict:
    try:
        request = _to_request(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        result = make_recommendation_service().recommend(request, principal)
    except AuthorizationError as exc:
        # Fail-closed object authorization: the verified principal's tenant is not entitled
        # to this customer (cross-tenant object reference). Never a 404 (which would confirm
        # existence) or a 200; deny with 403.
        raise HTTPException(status_code=403, detail="not authorized for this resource") from exc
    except GuardrailBlockedError as exc:
        raise HTTPException(status_code=400, detail=f"guardrail blocked: {exc}") from exc
    except UnknownCustomerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoCandidatesError as exc:
        raise HTTPException(status_code=404, detail=f"no candidate offers: {exc}") from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return to_jsonable(result)
