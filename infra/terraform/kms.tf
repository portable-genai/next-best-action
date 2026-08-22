# kms.tf : Regional Customer-Managed Encryption Keys (CMEK) in Singapore.
#
# Principle map:
#   CMEK does NOT cascade : a CMEK on one resource does not automatically protect data that
#               resource hands to another service. Each managed service (BigQuery, Discovery
#               Engine, Vertex / Agent Runtime, Logging, Cloud Run) must be told to use this
#               key explicitly. We keep ONE regional key ring + crypto key here and wire it
#               into every resource that supports CMEK in its own file.
#   Residency : the key ring location is var.region : a regional key, never the
#               global / multi-region key. Regional CMEK pins crypto material in-country.

resource "google_kms_key_ring" "nba" {
  name     = "mkt-nba-ring"
  location = var.region # the selected region : regional, in-country key material (residency)

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "nba" {
  name     = "mkt-nba-cmek"
  key_ring = google_kms_key_ring.nba.id

  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = "7776000s" # 90 days : periodic rotation for key hygiene

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE"
  }

  lifecycle {
    # A destroyed key is unrecoverable and would strand all CMEK-encrypted data.
    prevent_destroy = true
  }
}

# --------------------------------------------------------------------------- #
# Grant each service agent the right to use the key. CMEK does not cascade:
# every service that encrypts with this key needs its OWN binding here.
# --------------------------------------------------------------------------- #
data "google_project" "this" {
  project_id = var.project_id
}

# BigQuery service agent (recommendation feature dataset CMEK).
resource "google_kms_crypto_key_iam_member" "bigquery" {
  crypto_key_id = google_kms_crypto_key.nba.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:bq-${data.google_project.this.number}@bigquery-encryption.iam.gserviceaccount.com"
}

# Discovery Engine (File / Agent Search) service agent : offer / policy corpus.
resource "google_kms_crypto_key_iam_member" "discoveryengine" {
  crypto_key_id = google_kms_crypto_key.nba.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-discoveryengine.iam.gserviceaccount.com"
}

# Vertex AI / Agent Runtime service agent : recommendations, propensity, Gemini, eval, agent.
resource "google_kms_crypto_key_iam_member" "aiplatform" {
  crypto_key_id = google_kms_crypto_key.nba.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# Cloud Logging service agent (CMEK on the WORM bucket).
resource "google_kms_crypto_key_iam_member" "logging" {
  crypto_key_id = google_kms_crypto_key.nba.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-logging.iam.gserviceaccount.com"
}

# Cloud Run service agent (CMEK on the API service revision).
resource "google_kms_crypto_key_iam_member" "run" {
  crypto_key_id = google_kms_crypto_key.nba.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@serverless-robot-prod.iam.gserviceaccount.com"
}
