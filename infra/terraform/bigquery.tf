# bigquery.tf : Next-Best-Action feature dataset (recommendation / propensity, CMEK).
#
# Principle map:
#   Residency : the dataset is created in var.region; customer / shopper features and
#               propensity signals never leave Singapore.
#   CMEK explicit : the dataset uses the regional CMEK from kms.tf (the BigQuery service-agent
#               key binding lives in kms.tf : CMEK does not cascade).
#   Data minimisation : the recommendation adapter reads only the features ranking needs; PII
#               is redacted at the boundary before any text reaches a model or the audit log.
#
# This dataset backs the RecommendationPort (VertexRecommendationAdapter): the offer,
# eligibility and propensity feature store. Consent is owned only by marketing-compliance-gate and is never stored
# in this next-best-action dataset. The dataset id matches
# config/settings.yaml recommendation.bigquery_dataset (mkt_nba).

resource "google_bigquery_dataset" "nba_features" {
  dataset_id  = "mkt_nba" # matches settings.yaml recommendation.bigquery_dataset
  project     = var.project_id
  location    = var.region # the selected region (residency)
  description = "next-best-action next-best-action feature store (customer + offer + propensity, CMEK)."

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.nba.id # CMEK does not cascade
  }

  # Internal data : never world-readable; protect against accidental teardown.
  delete_contents_on_destroy = false

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.bigquery,
  ]
}

# Raw feature inputs. JSON columns carry genuinely vertical-specific attributes while the
# typed keys used for authorization, residency and deterministic policy remain first-class.
resource "google_bigquery_table" "customers" {
  dataset_id          = google_bigquery_dataset.nba_features.dataset_id
  table_id            = "customers"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "customer_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
    { name = "market", type = "STRING", mode = "REQUIRED" },
    { name = "vertical", type = "STRING", mode = "REQUIRED" },
    { name = "attributes_json", type = "JSON", mode = "REQUIRED" },
    { name = "holdings", type = "STRING", mode = "REPEATED" },
    { name = "affinities_json", type = "JSON", mode = "REQUIRED" },
    { name = "updated_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "offers" {
  dataset_id          = google_bigquery_dataset.nba_features.dataset_id
  table_id            = "offers"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "offer_id", type = "STRING", mode = "REQUIRED" },
    { name = "name", type = "STRING", mode = "REQUIRED" },
    { name = "kind", type = "STRING", mode = "REQUIRED" },
    { name = "market", type = "STRING", mode = "REQUIRED" },
    { name = "vertical", type = "STRING", mode = "REQUIRED" },
    { name = "category", type = "STRING", mode = "NULLABLE" },
    { name = "base_value", type = "FLOAT", mode = "REQUIRED" },
    { name = "required_consent_channel", type = "STRING", mode = "NULLABLE" },
    { name = "required_attributes_json", type = "JSON", mode = "REQUIRED" },
    { name = "excluded_if_held", type = "STRING", mode = "REPEATED" },
    { name = "stock", type = "INTEGER", mode = "NULLABLE" },
    { name = "evidence_summary", type = "STRING", mode = "REQUIRED" },
    { name = "active", type = "BOOLEAN", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "eligibility_rules" {
  dataset_id          = google_bigquery_dataset.nba_features.dataset_id
  table_id            = "eligibility_rules"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "rule_id", type = "STRING", mode = "REQUIRED" },
    { name = "market", type = "STRING", mode = "REQUIRED" },
    { name = "vertical", type = "STRING", mode = "REQUIRED" },
    { name = "effect", type = "STRING", mode = "REQUIRED" },
    { name = "attribute", type = "STRING", mode = "NULLABLE" },
    { name = "value", type = "STRING", mode = "NULLABLE" },
    { name = "applies_to_kind", type = "STRING", mode = "NULLABLE" },
    { name = "applies_to_category", type = "STRING", mode = "NULLABLE" },
    { name = "description", type = "STRING", mode = "REQUIRED" },
    { name = "citation_title", type = "STRING", mode = "REQUIRED" },
    { name = "active", type = "BOOLEAN", mode = "REQUIRED" },
  ])
}

# Propensity signal table : a 0..1 model score per (customer, offer). Schema mirrors the
# PropensitySignal domain type (SPEC.md "Domain types").
resource "google_bigquery_table" "propensity_signals" {
  dataset_id          = google_bigquery_dataset.nba_features.dataset_id
  table_id            = "propensity_signals"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "customer_id", type = "STRING", mode = "REQUIRED" },
    { name = "offer_id", type = "STRING", mode = "REQUIRED" },
    { name = "market", type = "STRING", mode = "REQUIRED" },
    { name = "vertical", type = "STRING", mode = "REQUIRED" },
    { name = "score", type = "FLOAT", mode = "REQUIRED" },
    { name = "model_version", type = "STRING", mode = "NULLABLE" },
    { name = "computed_at", type = "TIMESTAMP", mode = "NULLABLE" },
  ])
}
