"""Sensitive Data Protection (DLP) redaction adapter (PIIRedactionPort, A1, R1).

Implements :class:`PIIRedactionPort` against **Sensitive Data Protection / DLP** of the
Gemini Enterprise Agent Platform. Because D5 reasons over customer profiles, every prompt,
model input and audit record is de-identified at the boundary first, so PII is minimised to
the model (P-04). The call is regional (``projects/{project}/locations/{region}``) to keep
inspection inside the configured residency boundary (JP / AU / SG).

The inline inspect/de-identify configuration is jurisdiction-driven: it masks universal
info types (name, email, phone, passport, card) plus the national identifiers configured in
``settings.pii.jurisdictions`` (NRIC, My Number, TFN, ...) sourced from
``domain/pii_patterns.py``, so the managed and local redactors detect the same identifiers.

The ``google.cloud.dlp_v2`` import is lazy so on-prem / local / test profiles load this
module with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from pii_kit import national_patterns_for, re2_pattern_for

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult
from ._region import resolve_region

# The national-id custom detectors come from the shared pii-kit rows for the configured
# jurisdictions, in their RE2-safe form. DLP custom info types are matched with RE2, which has
# NO lookaround, so a Python-only row (e.g. the JP My Number lookarounds) would make DLP reject
# the whole inspect config with INVALID_ARGUMENT and fail every call: re2_pattern_for returns the
# lookaround-free equivalent. Sharing pii-kit keeps this detector in step with the local
# redactor and the eval leak-check instead of drifting as a private copy would.

_DEFAULT_INFO_TYPES: tuple[str, ...] = (
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PASSPORT",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
)

_MASKING_CHAR = "#"


class DlpRedactionAdapter:
    """De-identify PII via DLP ``deidentify_content`` (jurisdiction-driven inline config)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._region = resolve_region(settings)
        self._parent = f"projects/{settings.project_id}/locations/{self._region}"
        self._jurisdictions = getattr(getattr(settings, "pii", None), "jurisdictions", ())
        # Refuse an empty pattern set BEFORE the lazy DLP client import, so the refusal does
        # not depend on the Google Cloud SDK being installed: an empty set would send DLP an
        # inspect config with no custom info types and return the text almost untouched.
        if not tuple(self._jurisdictions):
            raise ValueError(
                "no PII jurisdictions configured; refusing to build DLP custom info types "
                "from an empty set (see config.resolve_pii_jurisdictions)"
            )
        self._client: Any | None = None

    def redact(self, text: str) -> RedactionResult:
        """Return de-identified text plus per-info-type finding counts."""
        if not text:
            return RedactionResult(text=text, findings=())
        client = self._service_client()
        request = {
            "parent": self._parent,
            "item": {"value": text},
            "deidentify_config": self._inline_deidentify_config(),
            "inspect_config": self._inline_inspect_config(),
        }
        response = client.deidentify_content(request=request)
        redacted_text: str = response.item.value
        return RedactionResult(text=redacted_text, findings=self._summarise(response))

    def _service_client(self) -> Any:
        from google.cloud import dlp_v2  # noqa: PLC0415 — lazy: gcp profile only

        if self._client is None:
            self._client = dlp_v2.DlpServiceClient()
        return self._client

    def _custom_info_types(self) -> list[dict[str, Any]]:
        """The configured jurisdictions' national ids, as DLP custom info types.

        Derived from the same shared ``pii-kit`` rows the local redactor and the eval gate
        use, in their RE2-safe form (a DLP regex is RE2, with no lookaround, and cannot carry a
        checksum). Rows that share an info type under two shapes (HK's parenthesised and bare
        HKID) are OR-ed into one RE2 alternation, so each info-type name appears once.
        """
        # verify: https://cloud.google.com/dlp/docs/creating-custom-infotypes-likelihood
        by_name: dict[str, list[str]] = {}
        for info_type, pattern, _validator in national_patterns_for(self._jurisdictions):
            by_name.setdefault(info_type, []).append(re2_pattern_for(info_type, pattern))
        return [
            {
                "info_type": {"name": name},
                "regex": {"pattern": "|".join(f"(?:{p})" for p in patterns)},
                "likelihood": "POSSIBLE",
            }
            for name, patterns in by_name.items()
        ]

    def _inline_inspect_config(self) -> dict[str, Any]:
        # verify: https://cloud.google.com/dlp/docs/reference/rest/v2/InspectConfig
        return {
            "info_types": [{"name": name} for name in _DEFAULT_INFO_TYPES],
            "custom_info_types": self._custom_info_types(),
            "min_likelihood": "POSSIBLE",
            "include_quote": False,
        }

    def _inline_deidentify_config(self) -> dict[str, Any]:
        # verify: https://cloud.google.com/dlp/docs/reference/rest/v2/DeidentifyConfig
        all_info_types = [{"name": name} for name in _DEFAULT_INFO_TYPES] + [
            c["info_type"] for c in self._custom_info_types()
        ]
        return {
            "info_type_transformations": {
                "transformations": [
                    {
                        "info_types": all_info_types,
                        "primitive_transformation": {
                            "character_mask_config": {"masking_character": _MASKING_CHAR}
                        },
                    }
                ]
            }
        }

    def _summarise(self, response: Any) -> tuple[RedactionFinding, ...]:
        overview = getattr(response, "overview", None)
        summaries = getattr(overview, "transformation_summaries", None) or []
        findings: list[RedactionFinding] = []
        for summary in summaries:
            info_type = getattr(getattr(summary, "info_type", None), "name", "")
            if not info_type:
                continue
            findings.append(
                RedactionFinding(info_type=info_type, count=self._transformed_count(summary))
            )
        return tuple(findings)

    @staticmethod
    def _transformed_count(summary: Any) -> int:
        total = 0
        for result in getattr(summary, "results", None) or []:
            code = getattr(result, "code", None)
            code_name = getattr(code, "name", str(code))
            if code_name == "SUCCESS":
                total += int(getattr(result, "count", 0) or 0)
        return total or 1
