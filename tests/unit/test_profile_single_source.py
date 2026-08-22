"""The profile has ONE source of truth, and it fails closed on an unset variable.

``MKT_NBA_PROFILE`` must never be read with a ``"local"`` fallback in two places at once: the
Python loader and the shipped ``config/settings.yaml`` interpolation token. Hardening either
alone leaves the other re-deriving the same decision, which is how an unset variable becomes
readable as consent to the no-auth posture. A drift guard is therefore part of the rule: any
module (or the settings file) that re-derives the profile with its own permissive default can
reintroduce the whole class, so only ``config.resolve_profile`` may decide it.

The same guard covers the PII jurisdiction set, which is the other environment-derived
allowlist in this repo: it must be resolved once too, because an empty one silently strips
every national identifier out of the redactor, the DLP custom info types and the eval gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hex_service_kit.netdefaults import ConfiguredEmptyError

from next_best_action.config import (
    RUNTIME_PROFILES,
    SUPPORTED_JURISDICTIONS,
    UNCONSENTED_PROFILE,
    PiiSettings,
    Settings,
    resolve_pii_jurisdictions,
    resolve_profile,
)

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "next_best_action"
_CONFIG = _SRC / "config.py"
_SETTINGS_FILE = _ROOT / "config" / "settings.yaml"
_PROFILE_TOKEN = re.compile(r"\$\{MKT_NBA_PROFILE(?::-(.*?))?\}")


def _python_sources() -> list[Path]:
    return sorted(p for p in _SRC.rglob("*.py") if p != _CONFIG)


def test_only_the_resolver_reads_the_profile_variable_from_the_environment() -> None:
    offenders = []
    for path in _python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"(os\.environ|os\.getenv)[^\n]*PROFILE", line):
                offenders.append(f"{path.relative_to(_SRC)}:{number}: {line.strip()}")
    assert not offenders, (
        "these modules re-derive the profile instead of calling config.resolve_profile, "
        "so an unset MKT_NBA_PROFILE can again be read as consent:\n" + "\n".join(offenders)
    )


def test_only_the_resolver_reads_the_jurisdiction_allowlist() -> None:
    """Including the eval gate: a second reader can narrow the detector the gate trusts."""
    sources = [*_python_sources(), _ROOT / "eval" / "run_eval.py"]
    offenders = []
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"(os\.environ|os\.getenv)[^\n]*JURISDICTIONS", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "these modules re-derive the PII jurisdiction set instead of calling "
        "config.resolve_pii_jurisdictions, so an empty one can again pass silently:\n"
        + "\n".join(offenders)
    )


def test_the_shipped_settings_file_supplies_no_permissive_profile_default() -> None:
    """The yaml interpolation is the SECOND place the fallback lived; it must stay empty."""
    text = _SETTINGS_FILE.read_text(encoding="utf-8")
    defaults = [m.group(1) for m in _PROFILE_TOKEN.finditer(text) if (m.group(1) or "").strip()]
    assert not defaults, (
        "config/settings.yaml gives MKT_NBA_PROFILE a fallback of "
        f"{defaults!r}, which reinstates 'unset means local' below the Python resolver"
    )


def test_the_resolver_treats_an_ABSENT_variable_as_no_choice() -> None:
    assert resolve_profile({}).explicit is False


def test_an_EMPTIED_variable_refuses_rather_than_inheriting_the_unset_default() -> None:
    """Asserting absent and blank are the same state, and neither a choice, is the defect.

    That is the defect stated as a claim, and stating it is why the suite could not see it. An
    operator who deliberately emptied the variable expressed an intent that names no profile,
    which is not the same as never having chosen one, so it refuses instead of inheriting.
    """
    for environ in ({"MKT_NBA_PROFILE": ""}, {"MKT_NBA_PROFILE": "   "}):
        with pytest.raises(ConfiguredEmptyError):
            resolve_profile(environ)


def test_an_unconsented_run_is_not_the_local_profile_for_any_relaxation() -> None:
    choice = resolve_profile({})
    assert choice.exposure_profile == UNCONSENTED_PROFILE
    assert choice.exposure_profile != "local"
    assert UNCONSENTED_PROFILE not in RUNTIME_PROFILES


def test_an_unconsented_run_still_binds_loopback() -> None:
    """The bind guard fails closed in the opposite direction: local is the restrictive case."""
    assert resolve_profile({}).bind_profile == "local"


def test_a_deliberate_profile_is_carried_through_unchanged() -> None:
    choice = resolve_profile({"MKT_NBA_PROFILE": "gcp"})
    assert (choice.profile, choice.explicit) == ("gcp", True)
    assert choice.exposure_profile == "gcp"
    assert choice.bind_profile == "gcp"


def test_a_profile_written_into_the_reviewed_settings_file_is_a_deliberate_choice() -> None:
    choice = resolve_profile({}, configured="gcp")
    assert (choice.profile, choice.explicit) == ("gcp", True)


@pytest.mark.parametrize("value", ["bogus", "Local", "GCP", "LOCAL"])
def test_an_unknown_or_mis_capitalised_profile_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="MKT_NBA_PROFILE"):
        resolve_profile({"MKT_NBA_PROFILE": value})


def test_direct_construction_is_deliberate_by_definition() -> None:
    """A caller who names the profile in code has chosen it; only ``load`` can be unconsented."""
    assert Settings(profile="local").profile_explicit is True
    assert Settings(profile="local").exposure_profile == "local"


# --------------------------------------------------------------------------- #
# The jurisdiction allowlist: unset keeps the reviewed set, empty REFUSES.
# --------------------------------------------------------------------------- #
def test_an_unset_jurisdiction_variable_keeps_the_reviewed_set() -> None:
    """The direction of a restriction: absence must never shrink the redaction boundary."""
    assert resolve_pii_jurisdictions({}, configured=("SG", "JP", "AU")) == ("SG", "JP", "AU")


@pytest.mark.parametrize("value", ["", "   ", ",", " , , "])
def test_a_set_but_empty_jurisdiction_allowlist_refuses(value: str) -> None:
    """This is the bug: a comma split that yields () disables every national-id row."""
    with pytest.raises(ValueError, match="MKT_NBA_PII_JURISDICTIONS"):
        resolve_pii_jurisdictions(
            {"MKT_NBA_PII_JURISDICTIONS": value}, configured=("SG", "JP", "AU")
        )


def test_an_unsupported_jurisdiction_code_is_refused() -> None:
    """The shared pack SKIPS unknown codes, so an unvalidated typo redacts nothing."""
    with pytest.raises(ValueError, match="SGP"):
        resolve_pii_jurisdictions({"MKT_NBA_PII_JURISDICTIONS": "SGP"})


def test_an_empty_reviewed_set_refuses_too() -> None:
    with pytest.raises(ValueError, match="settings.yaml"):
        resolve_pii_jurisdictions({}, configured=())


def test_a_named_jurisdiction_set_is_normalised_and_carried_through() -> None:
    assert resolve_pii_jurisdictions({"MKT_NBA_PII_JURISDICTIONS": " sg , jp "}) == ("SG", "JP")


def test_the_shipped_default_jurisdictions_are_all_supported() -> None:
    assert set(PiiSettings().jurisdictions) <= SUPPORTED_JURISDICTIONS
