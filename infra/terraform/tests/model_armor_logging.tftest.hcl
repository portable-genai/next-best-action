# model_armor_logging.tftest.hcl : the guardrail template never logs sanitize operations,
# read as the PLANNED template rather than as template text.
#
# Why the file exists: a sanitize-operation log entry carries the prompt and response text Model
# Armor screened, which here is customer context and recommendation text. The template's own
# comment said the payloads stay out of logs while the flag was true, and nothing caught the
# contradiction: `terraform validate` accepts either value. A plan reads the value that would
# actually be applied.
#
# The second run proves declining the regional capabilities (the asia-southeast1 form) leaves
# the logging decision and the required template_metadata block alone.
#
# Mock providers and plan-only, so this runs with NO credentials and NO state, which is what the
# CI gate's terraform test step runs. Every value is fictional.

mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "fictional-nba-project"
  org_id     = "123456789012"
  # Named because it has no default; false keeps a plan from ever describing a locked bucket.
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

# The Cloud Run preconditions resolve the project numbers and the Shared VPC subnet from data
# sources; a mock provider returns random strings for them, so the plan states what a correctly
# wired deployment would read.
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

run "sanitize_operations_are_never_logged" {
  command = plan

  assert {
    condition     = google_model_armor_template.nba_guardrail.template_metadata[0].log_sanitize_operations == false
    error_message = "log_sanitize_operations must be false: a sanitize-operation log entry carries the screened customer text."
  }

  assert {
    condition     = google_model_armor_template.nba_guardrail.template_metadata[0].log_template_operations == true
    error_message = "log_template_operations must stay true: template changes are the audit trail, and they carry no customer text."
  }
}

run "declined_capabilities_keep_the_logging_decision" {
  command = plan

  variables {
    model_armor_full_capabilities = false
  }

  assert {
    condition     = length(google_model_armor_template.nba_guardrail.filter_config[0].malicious_uri_filter_settings) == 0
    error_message = "model_armor_full_capabilities = false must drop malicious_uri_filter_settings: asia-southeast1 refuses the whole template while it is present."
  }

  assert {
    condition = (
      length(google_model_armor_template.nba_guardrail.template_metadata) == 1 &&
      google_model_armor_template.nba_guardrail.template_metadata[0].log_sanitize_operations == false
    )
    error_message = "Declining the regional capabilities must leave template_metadata in place with log_sanitize_operations = false."
  }
}
