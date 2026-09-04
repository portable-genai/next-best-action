"""Managed consent is one OIDC-authenticated hop to
marketing-compliance-gate, never a second store.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra" / "terraform"


def test_cloud_run_wires_the_reviewed_url_and_oidc_audience_without_static_secrets() -> None:
    cloud_run = (TF / "cloud_run.tf").read_text(encoding="utf-8")
    variables = (TF / "variables.tf").read_text(encoding="utf-8")

    assert 'name  = "MKT_CONSENT_STORE_URL"' in cloud_run
    assert "value = var.consent_store_url" in cloud_run
    assert 'name  = "MKT_CONSENT_STORE_AUDIENCE"' in cloud_run
    assert "value = var.consent_store_audience" in cloud_run
    assert 'variable "consent_store_url"' in variables
    assert 'variable "consent_store_audience"' in variables
    assert "CONSENT_S2S_TOKEN" not in cloud_run
    assert "secret_data" not in "\n".join(
        path.read_text(encoding="utf-8") for path in TF.glob("*.tf")
    )


def test_mkt5_does_not_provision_a_second_consent_store() -> None:
    bigquery = (TF / "bigquery.tf").read_text(encoding="utf-8")
    assert 'table_id            = "consent_records"' not in bigquery
    assert 'resource "google_bigquery_table" "consent_records"' not in bigquery
