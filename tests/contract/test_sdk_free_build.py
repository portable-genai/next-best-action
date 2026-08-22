"""EVERY profile builds in an interpreter where the cloud SDKs cannot be imported.

Not "no SDK installed on this machine": ``tests/contract/_sdk_free_probe.py`` installs a
meta-path finder that refuses the ``google`` and ``vertexai`` roots, then constructs every
adapter binding of the profile in a fresh process. Proving the claim by absence would tie it to
the developer machine: one with the SDK installed would pass while hiding an eager import that
breaks the offline gate everywhere else.

Every profile, INCLUDING ``gcp`` and ``platform``, and that is the point rather than an
overreach. The managed adapters import their SDK lazily, inside the method that needs it, so
they CONSTRUCT with no SDK present; that laziness is what lets a fork run the offline stack
without installing a cloud SDK at all, and it is the repository's hard constraint.

What enforced it was thinner than it looks. The parity and portability suites construct only
the SDK-free profiles, so they never import the managed adapter modules at all, and
``tests/unit/test_gcp_adapters_import_safe.py`` covers them by importing a HAND-WRITTEN list of
managed modules and constructing each class. It never asks whether ``google`` was imported, so
it proves the contract only on a machine where the SDK happens to be absent, which is the exact
"no SDK installed here" argument this file exists to replace; its list also omits the identity,
consent and redaction bindings, and it says nothing about the ``platform`` family, which reuses
several of those same modules, or about the ``vertexai`` root.

Proved rather than asserted: with an importable ``google.cloud`` on the path and
``from google.cloud import logging`` hoisted to module scope in ``adapters/gcp/iap_identity.py``,
that guard stayed GREEN while the ``gcp`` and ``platform`` cases here went red. Constructing
every profile under an active prohibition is what makes the detection real.

The parity suite next door proves the bindings satisfy their Protocols in-process; this file
proves every one of them imports and constructs under prohibition.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.contract.test_port_parity import PORT_PROTOCOLS, SDK_FREE_PROFILES, _settings

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every profile the settings file binds, discovered rather than restated, so a profile added
#: to the binding table is proved from the moment it exists instead of when somebody remembers
#: this list. A hand-written tuple here is how ``platform`` would go unproved for a release.
ALL_PROFILES = tuple(sorted(set().union(*(_settings("local").adapters[p] for p in PORT_PROTOCOLS))))


def _run_probe(argument: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tests.contract._sdk_free_probe", argument],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": "src"},
        check=False,
        timeout=300,
    )


@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_the_profile_constructs_with_the_cloud_sdks_blocked(profile: str) -> None:
    completed = _run_probe(profile)
    assert completed.returncode == 0, (
        f"the {profile} profile could not be built with the cloud SDKs blocked:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    assert "no cloud SDK importable" in completed.stdout


def test_the_sdk_free_profiles_are_among_the_profiles_proved() -> None:
    """The discovered set must still cover the ones the parity suite calls SDK-free.

    Discovery is worth more than a hand-written list only while it keeps finding at least what
    the list held. A settings file that lost a binding would otherwise shrink this suite in
    silence, and a suite that quietly proves less is the failure this whole file exists about.
    """
    missing = set(SDK_FREE_PROFILES) - set(ALL_PROFILES)
    assert not missing, f"profiles the parity suite proves SDK-free are unbound here: {missing}"
    assert len(ALL_PROFILES) >= len(SDK_FREE_PROFILES)


def test_the_blocker_still_blocks() -> None:
    """A probe whose blocker quietly stopped blocking would make every proof above vacuous."""
    completed = _run_probe("--self-test")
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert "blocker refused google.auth" in completed.stdout
