"""On-prem placeholder for ``PIIRedactionPort`` — the sovereign target (fail-closed).

One of the reversibility / portability migration placeholders: in the managed profile this
port binds to the Sensitive Data Protection / DLP adapter; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so the
contract tests prove interface parity. ``redact`` deliberately RAISES rather than passing
text through unredacted: an unimplemented redactor must never leak customer PII to a model
or audit sink (R1, P-04), so porting on-premise *must* supply a real de-identifier. Filling
this body in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import RedactionResult

_MESSAGE = (
    "On-prem PIIRedactionPort adapter is a migration placeholder; implement against your "
    "on-premise de-identification platform. It fails closed (raises) rather than passing "
    "customer PII through unredacted. Core domain logic is unchanged."
)


class OnPremRedactionAdapter:
    """Fail-closed placeholder PII-redaction adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def redact(self, text: str) -> RedactionResult:
        raise NotImplementedError(_MESSAGE)
