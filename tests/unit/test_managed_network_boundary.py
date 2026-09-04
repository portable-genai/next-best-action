"""Static contracts for the managed next-best-action -> marketing-compliance-gate network and
perimeter path.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra" / "terraform"


def _read(name: str) -> str:
    return (TF / name).read_text(encoding="utf-8")


def test_mkt5_routes_all_egress_over_the_validated_shared_vpc() -> None:
    cloud_run = _read("cloud_run.tf")
    network = _read("network.tf")
    variables = _read("variables.tf")

    assert 'egress = "ALL_TRAFFIC"' in cloud_run
    assert "network    = var.shared_vpc_network" in cloud_run
    assert "subnetwork = var.shared_vpc_subnetwork" in cloud_run
    assert "data.google_compute_subnetwork.shared_cloud_run.private_ip_google_access" in cloud_run
    cidr_guard = (
        'tonumber(split("/", '
        "data.google_compute_subnetwork.shared_cloud_run.ip_cidr_range)[1]) <= 26"
    )
    assert cidr_guard in cloud_run
    assert "data.google_project.this.number) == var.mkt5_project_number" in cloud_run
    assert (
        "data.google_project.shared_vpc_host.number) == var.shared_vpc_host_project_number"
        in cloud_run
    )
    assert 'variable "shared_vpc_network"' in variables
    assert 'variable "shared_vpc_subnetwork"' in variables
    assert "roles/compute.networkViewer" in network
    assert "roles/compute.networkUser" in network
    assert 'resource "google_project_service_identity" "run"' in network
    assert 'data "google_project" "shared_vpc_host"' in network


def test_mkt5_declares_both_services_and_host_in_one_non_owned_perimeter() -> None:
    perimeter = _read("vpc_sc.tf")
    variables = _read("variables.tf")
    example = _read("terraform.tfvars.example")

    assert "var.enable_vpc_sc && var.manage_shared_vpc_sc_perimeter" in perimeter
    assert '"projects/${var.shared_vpc_host_project_number}"' in perimeter
    assert '"projects/${var.mkt5_project_number}"' in perimeter
    assert '"projects/${var.mkt6_project_number}"' in perimeter
    assert "resources           = local.shared_perimeter_resources" in perimeter
    assert 'variable "shared_vpc_host_project_number"' in variables
    assert 'variable "mkt5_project_number"' in variables
    assert 'variable "mkt6_project_number"' in variables
    assert "manage_shared_vpc_sc_perimeter  = false" in example
    assert 'shared_vpc_sc_perimeter_name    = "mkt_marketing_sg"' in example


def test_mkt5_example_uses_a_run_app_target_and_no_connector_fallback() -> None:
    example = _read("terraform.tfvars.example")
    terraform = "\n".join(path.read_text(encoding="utf-8") for path in TF.glob("*.tf"))

    assert ".a.run.app" in example
    assert "google_vpc_access_connector" not in terraform
    assert "PRIVATE_RANGES_ONLY" not in _read("cloud_run.tf")
