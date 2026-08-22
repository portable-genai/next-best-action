"""Local PII redaction adapter (PIIRedactionPort) — regex de-identification.

The ``local`` profile's stand-in for **Sensitive Data Protection / DLP**: masks the
national identifiers for the configured jurisdiction(s) plus universal email/phone with
deterministic regexes, returning findings. This is the redact-before-everything boundary
(R1, P-04) so customer PII never reaches the model, a trace span or the audit sink. The
pattern set is jurisdiction-driven (``settings.pii.jurisdictions``, default JP/AU/SG) so a
non-APAC deployment detects its own identifiers by config, not a code change.

The rows and their checksum validators come from the shared ``pii-kit`` package, NOT a
local copy: this redactor, the DLP adapter and the eval leak-check all read the SAME rows,
so a pattern fix is a version bump rather than a copy that drifts out of sync (a copy that
narrows three rows in the copying leaks identifiers no gate can see).

Rows that carry a checksum validator (JP My Number, AU TFN) mask only genuine identifiers,
so an ordinary 9- or 12-digit reference number is left intact rather than falsely redacted.
D5 has no bank-account row, so the universal email/phone rows lead and the national-id rows
follow with no bare-digit catch-all and therefore no row-ordering hazard.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit.patterns import Pattern

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult


class LocalRegexRedactionAdapter:
    """Mask the configured jurisdictions' national ids + email/phone, like DLP de-identify."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        jurisdictions = getattr(getattr(settings, "pii", None), "jurisdictions", ("SG", "JP", "AU"))
        # An EMPTY set is refused here as well as at configuration load, so a code path that
        # skips ``Settings.load`` cannot silently reduce the boundary to email and phone. An
        # unknown-but-named code still degrades rather than raising (the shared pack's
        # documented contract); ``config.resolve_pii_jurisdictions`` is what stops one reaching
        # here from configuration.
        if not tuple(jurisdictions):
            raise ValueError(
                "no PII jurisdictions configured; refusing to redact with the national-id "
                "pattern set empty (see config.resolve_pii_jurisdictions)"
            )
        # Universal rows first, then the national-id rows for the configured jurisdictions.
        # D5 has no account row, so this order carries no subsumption hazard.
        self._patterns: tuple[Pattern, ...] = (
            *UNIVERSAL_PATTERNS,
            *tuple(national_patterns_for(jurisdictions)),
        )

    def redact(self, text: str) -> RedactionResult:
        redacted = text
        counts: dict[str, int] = {}
        for info_type, pattern, validator in self._patterns:

            def _sub(
                m: re.Match[str],
                _it: str = info_type,
                _val: Callable[[str], bool] | None = validator,
            ) -> str:
                if _val is not None and not _val(m.group(0)):
                    return m.group(0)  # checksum fail: not a real identifier, leave it intact
                counts[_it] = counts.get(_it, 0) + 1
                return f"[{_it}]"

            redacted = pattern.sub(_sub, redacted)
        findings = tuple(RedactionFinding(info_type=it, count=n) for it, n in counts.items() if n)
        return RedactionResult(text=redacted, findings=findings)
