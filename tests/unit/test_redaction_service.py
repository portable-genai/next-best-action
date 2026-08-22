"""PII redaction adapter tests (the redact-before-everything boundary, R1).

Prove the jurisdiction-driven local redactor masks D5's home-market national identifiers
(SG NRIC, JP My Number, AU TFN) plus universal email/phone, that the JP My Number checksum
validator masks only genuine numbers (not any 12-digit run), and that an unknown
jurisdiction degrades safely to email/phone only rather than raising. Same pattern source as
the eval gate, so what these tests mask is exactly what the gate detects.
"""

from __future__ import annotations

from next_best_action.adapters.local.redaction import LocalRegexRedactionAdapter
from next_best_action.config import PiiSettings, Settings

# FICTIONAL identifiers. The JP My Number is 12 digits with a valid check digit; the second
# is the same first 11 digits with a wrong check digit (an invalid number, must NOT mask).
_SG_NRIC = "S1234567A"
_JP_MYNUMBER_VALID = "123456789018"
_JP_MYNUMBER_INVALID = "123456789012"
_AU_TFN = "123 456 782"
_EMAIL = "ops@example.com"
_PHONE = "+81 90 1234 5678"


def _redactor(*jurisdictions: str) -> LocalRegexRedactionAdapter:
    return LocalRegexRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=jurisdictions)))


def test_sg_nric_and_email_and_phone_masked() -> None:
    r = _redactor("SG", "JP", "AU")
    out = r.redact(f"NRIC {_SG_NRIC}, email {_EMAIL}, phone {_PHONE}")
    assert _SG_NRIC not in out.text
    assert _EMAIL not in out.text
    assert _PHONE not in out.text
    info = {f.info_type for f in out.findings}
    assert {"SG_NRIC_FIN", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= info


def test_jp_my_number_masked_only_when_checksum_valid() -> None:
    r = _redactor("JP")
    valid = r.redact(f"My Number {_JP_MYNUMBER_VALID} on file.")
    assert _JP_MYNUMBER_VALID not in valid.text
    assert "[JP_MY_NUMBER]" in valid.text
    assert {"JP_MY_NUMBER"} <= {f.info_type for f in valid.findings}
    # A 12-digit run with a wrong check digit is NOT a My Number: it must survive intact.
    invalid = r.redact(f"Ref {_JP_MYNUMBER_INVALID} is not an id.")
    assert _JP_MYNUMBER_INVALID in invalid.text
    assert not invalid.findings


def test_au_tfn_masked() -> None:
    r = _redactor("AU")
    out = r.redact(f"TFN {_AU_TFN} recorded.")
    assert _AU_TFN not in out.text
    assert "AU_TFN" in {f.info_type for f in out.findings}


def test_all_home_market_ids_masked_together() -> None:
    r = _redactor("SG", "JP", "AU")
    out = r.redact(f"{_SG_NRIC} / {_JP_MYNUMBER_VALID} / {_AU_TFN} / {_EMAIL}")
    for raw in (_SG_NRIC, _JP_MYNUMBER_VALID, _AU_TFN, _EMAIL):
        assert raw not in out.text
    assert out.redacted


def test_unknown_jurisdiction_degrades_to_email_and_phone_only() -> None:
    r = _redactor("XX")  # unknown ISO code: no national-id pack, universal PII still applies
    out = r.redact(f"NRIC {_SG_NRIC}, email {_EMAIL}")
    # The national id survives (its pack was not configured) ...
    assert _SG_NRIC in out.text
    # ... but the universal email is still masked, and the adapter never raises.
    assert _EMAIL not in out.text
    assert {f.info_type for f in out.findings} == {"EMAIL_ADDRESS"}
