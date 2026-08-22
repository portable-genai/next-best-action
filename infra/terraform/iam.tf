# iam.tf : Dedicated least-privilege runtime identity for the Cloud Run service.
#
# Principle map:
#   No lock-in / no keys : Cloud Run uses this service account as its identity via Workload
#               Identity : no exported keys anywhere (org_policy.tf disables SA-key creation).
#   Least privilege : the runtime gets only the roles the gcp adapters need : Vertex AI for
#               recommendations / propensity / Gemini / eval / agent, BigQuery read on the
#               feature store, Discovery Engine for the corpus, plus log / trace / metric
#               write and token minting for outbound A2A. No broad / project-owner grants.

resource "google_service_account" "runtime" {
  account_id   = "mkt-nba-run"
  display_name = "Mkt5 Next-Best-Action : Cloud Run runtime"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

# Vertex AI : recommendations, propensity endpoint, Gemini, Gen AI eval, agent.
resource "google_project_iam_member" "runtime_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# BigQuery : read the feature store + run queries. Data viewer + job user, nothing more.
resource "google_project_iam_member" "runtime_bq_data_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Discovery Engine : query the offer / policy corpus (File / Agent Search).
resource "google_project_iam_member" "runtime_discoveryengine_viewer" {
  project = var.project_id
  role    = "roles/discoveryengine.viewer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# WORM audit : write the app audit log (the locked bucket sink handles retention).
resource "google_project_iam_member" "runtime_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Cloud Trace : emit reasoning-loop spans.
resource "google_project_iam_member" "runtime_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Monitoring : write the metrics behind the posture alerts.
resource "google_project_iam_member" "runtime_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Mint ID tokens for outbound A2A calls to sibling platform services.
resource "google_project_iam_member" "runtime_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
