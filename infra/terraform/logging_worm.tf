# logging_worm.tf : WORM audit trail : lockable Cloud Logging bucket + sink + audit config.
#
# Principle map:
#   Immutable audit / WORM : the audit log is routed to a Cloud Logging bucket whose
#               retention is var.retention_days (~7 years) and whose lock (var.worm_locked) makes it
#               Write-Once-Read-Many. The audit adapter (CloudLoggingAuditAdapter) writes
#               AuditEvents to the next-best-action-audit log; the app redacts before it
#               logs, and this bucket guarantees those events cannot be altered or deleted.
#   Residency : bucket location is var.region (the selected, allow-listed region).
#   CMEK explicit : the bucket is CMEK-encrypted (logging SA key binding in kms.tf).
#
# ############################################################################ #
# # WARNING : LOCKING IS IRREVERSIBLE.                                        # #
# # Setting worm_locked = true permanently prevents reducing retention or     # #
# # deleting this bucket for the full retention window. You CANNOT undo it,   # #
# # not even with project-owner rights. Confirm retention_days before apply.  # #
# # No default: state worm_locked. false keeps it deletable (NOT for prod).   # #
# ############################################################################ #

resource "google_logging_project_bucket_config" "worm_audit" {
  project        = var.project_id
  location       = var.region              # the selected region (residency)
  bucket_id      = "next-best-action-worm" # matches settings.yaml logging.bucket
  description    = "WORM audit bucket for next-best-action next-best-action (lockable, ~7y retention)."
  retention_days = var.retention_days # 2557 (~7 years) by default

  # IRREVERSIBLE when true (see the warning banner above), and never defaulted.
  locked = var.worm_locked

  # CMEK on the log bucket : explicit, does not cascade.
  dynamic "cmek_settings" {
    for_each = var.cmek_enabled ? [1] : []
    content {
      kms_key_name = one(google_kms_crypto_key.nba[*].id)
    }
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.logging,
  ]
}

# Route the audit log stream into the WORM audit bucket.
resource "google_logging_project_sink" "audit_to_worm" {
  project     = var.project_id
  name        = "mkt-nba-audit-to-worm"
  description = "Routes the next-best-action-audit log to the WORM audit bucket."

  destination = "logging.googleapis.com/${google_logging_project_bucket_config.worm_audit.id}"

  # Capture this app's audit log only. Cloud Audit Logs are NOT copied here: _Default already keeps them.
  filter = <<-EOT
    logName="projects/${var.project_id}/logs/next-best-action-audit"
  EOT

  unique_writer_identity = true
}

# --------------------------------------------------------------------------- #
# Enable Data Access audit logs so every read of the feature store, the corpus,
# and the audit store itself is itself audited.
# --------------------------------------------------------------------------- #
resource "google_project_iam_audit_config" "data_access" {
  count   = var.manage_audit_config ? 1 : 0
  project = var.project_id
  service = "allServices"

  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
  audit_log_config {
    log_type = "ADMIN_READ"
  }
}
