"""No CI gate may be weakened by a hardcoded calendar date.

A supply-chain step here once carried a "TEMPORARY: expires 2026-08-06" exception that
compared ``$(date -u +%F)`` against that literal and, until the date passed, waved a set of
named advisories through. The class of defect is not the exception itself but the fact that
it rots SILENTLY: the branch that lets findings through keeps running unchallenged until a
day nobody is watching, and the allowlist it guards drifts out of step with the real report
long before then. (It did: the advisory it excepted had disappeared, while the finding that
actually failed the build was never on its list.)

So the rule is structural rather than case-by-case: a workflow must not decide anything by
comparing the current date to a date literal. A gate is either on or off, and turning one off
is a reviewed edit, never a clock tick.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

# A hardcoded calendar date, e.g. 2026-08-06.
_DATE_LITERAL = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# The shell reading the CURRENT date: `date -u +%F`, `date +%Y-%m-%d`, `date --utc ...`.
_CURRENT_DATE_CALL = re.compile(r"\bdate\s+[-+]")


def _workflow_files() -> list[Path]:
    return sorted(p for p in _WORKFLOWS.rglob("*") if p.suffix in {".yaml", ".yml"})


def test_the_workflow_directory_is_where_this_guard_thinks_it_is() -> None:
    """A guard that silently scans nothing is the same failure it exists to prevent."""
    assert _workflow_files(), f"no workflow files found under {_WORKFLOWS}"


def test_no_workflow_gates_on_a_hardcoded_date() -> None:
    offenders: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        if not _CURRENT_DATE_CALL.search(text):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _DATE_LITERAL.search(line):
                offenders.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "these workflow lines pair a hardcoded date with a reading of the current date, so a "
        "gate decides whether to enforce itself by the calendar and rots without a review:\n"
        + "\n".join(offenders)
    )
