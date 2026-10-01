# posture_defaults.tftest.hcl: the reversible posture controls are OFF unless stated.
#
# Slice 7 of the 2026-09-23 posture rule (2026-10-01): a compliance control that is not
# irreversible defaults off in code, and terraform.tfvars.example carries the production
# form. This file pins that default with mock providers only, like the rest of the suite.

mock_provider "google" {}
mock_provider "google-beta" {}

# Required variables with no default, stated only so the plan runs.
variables {
  project_id  = "fictional-nba-project"
  org_id      = "123456789012"
  worm_locked = false

  mkt5_project_number            = "111111111111"
  mkt6_project_number            = "222222222222"
  shared_vpc_host_project_number = "333333333333"
  shared_vpc_network             = "projects/fictional-network-host/global/networks/mkt-test"
  shared_vpc_subnetwork          = "projects/fictional-network-host/regions/asia-southeast1/subnetworks/cloud-run-mkt"

  consent_store_url      = "https://consent.fictional.example"
  consent_store_audience = "https://mkt6-consent.fictional.example"
  human_review_url       = "https://review.fictional.example"
  access_policy_id       = "987654321098"
}

override_data {
  target = data.google_project.this
  values = { number = "111111111111" }
}

override_data {
  target = data.google_project.shared_vpc_host
  values = { number = "333333333333" }
}

override_data {
  target = data.google_compute_subnetwork.shared_cloud_run
  values = {
    private_ip_google_access = true
    ip_cidr_range            = "10.10.0.0/26"
    network                  = "https://www.googleapis.com/compute/v1/projects/fictional-network-host/global/networks/mkt-test"
  }
}

run "reversible_posture_controls_default_off" {
  command = plan


  assert {
    condition     = length(google_access_context_manager_service_perimeter.nba) == 0
    error_message = "enable_vpc_sc defaults to false: no perimeter unless the deployment states it."
  }
}
