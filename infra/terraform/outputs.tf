# outputs.tf : Values the app / operators need to wire settings.yaml after apply.
#
# These map onto config/settings.yaml fields so a deploy is just "apply, then export these
# into the runtime environment".

output "project_id" {
  description = "The deployment project id."
  value       = var.project_id
}

output "region" {
  description = "The region this stack deployed to (selected at deploy time from var.allowed_regions)."
  value       = var.region
}

# --------------------------------- KMS -------------------------------------- #
output "cmek_key" {
  description = "Regional CMEK crypto key id (protects BigQuery, logs, Cloud Run, staging)."
  value       = google_kms_crypto_key.nba.id
}

# ------------------------------- BigQuery ----------------------------------- #
output "feature_dataset" {
  description = "BigQuery feature dataset id (settings.yaml recommendation.bigquery_dataset)."
  value       = google_bigquery_dataset.nba_features.dataset_id
}

output "feature_dataset_location" {
  description = "Confirms feature-store residency : must equal the selected var.region."
  value       = google_bigquery_dataset.nba_features.location
}

# ------------------------------- WORM logging ------------------------------- #
output "log_bucket" {
  description = "Locked WORM audit log bucket id (settings.yaml logging.bucket)."
  value       = google_logging_project_bucket_config.worm_audit.id
}

output "audit_sink_writer_identity" {
  description = "Sink writer identity (grant it bucket access if cross-project)."
  value       = google_logging_project_sink.audit_to_worm.writer_identity
}

# ------------------------------- Guardrail ---------------------------------- #
output "model_armor_template" {
  description = "Model Armor template id (settings.yaml model_armor.template_id)."
  value       = google_model_armor_template.nba_guardrail.template_id
}

# ------------------------------- Cloud Run ---------------------------------- #
output "service_url" {
  description = "Base URL of the Mkt5 Cloud Run service."
  value       = google_cloud_run_v2_service.nba.uri
}

output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.nba.name
}

output "runtime_service_account" {
  description = "Least-privilege runtime identity (Workload Identity) used by Cloud Run."
  value       = google_service_account.runtime.email
}

output "consent_store_url" {
  description = "Reviewed Mkt6 consent authority URL injected into the service."
  value       = var.consent_store_url
}

output "consent_store_audience" {
  description = "Custom OIDC audience Mkt5 mints for and Mkt6 verifies."
  value       = var.consent_store_audience
}

output "agent_staging_bucket" {
  description = "CMEK-encrypted, in-region staging bucket for the Agent Runtime deploy."
  value       = google_storage_bucket.agent_staging.name
}

# ------------------------------- Perimeter ---------------------------------- #
output "vpc_sc_perimeter" {
  description = "Expected shared VPC-SC perimeter name (empty when enable_vpc_sc = false), whether this stack owns it or consumes it."
  value       = var.enable_vpc_sc ? "accessPolicies/${var.access_policy_id}/servicePerimeters/${var.shared_vpc_sc_perimeter_name}" : ""
}

output "manages_vpc_sc_perimeter" {
  description = "True only for the Terraform state that owns the shared regular perimeter."
  value       = var.enable_vpc_sc && var.manage_shared_vpc_sc_perimeter
}

output "shared_vpc_network" {
  description = "Existing Shared VPC network used for all Cloud Run egress."
  value       = var.shared_vpc_network
}

output "shared_vpc_subnetwork" {
  description = "Existing region-local Shared VPC subnet used for Direct VPC egress."
  value       = var.shared_vpc_subnetwork
}

output "vpc_sc_dry_run" {
  description = "True while the perimeter is in dry-run (logs, does not block)."
  value       = var.vpc_sc_dry_run
}
