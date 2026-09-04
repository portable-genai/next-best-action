# vpc_sc.tf : VPC Service Controls perimeter around the AI / data plane.
#
# Principle map:
#   Residency + exfiltration control : one regular perimeter draws a logical boundary around
#               the sovereignty-critical APIs (Vertex / Agent Platform, Discovery Engine,
#               BigQuery, Model Armor, Logging, Trace, KMS) for both marketing service projects
#               and the Shared VPC host. Separate regular perimeters cannot provide this path:
#               a project may belong to only one regular perimeter and cross-perimeter Cloud
#               Run calls can be denied even when IAM and OIDC are correct.
#
# DRY-RUN FIRST. var.vpc_sc_dry_run defaults to true, so the perimeter is created as a
# `spec` (dry-run) only : it logs what WOULD be denied without blocking anything. Watch the
# audit logs (VpcServiceControlAuditMetadata, surfaced by monitoring.tf), confirm no
# legitimate path is broken, then set vpc_sc_dry_run = false to enforce. Never enforce blind
# on a path you have not first watched in dry-run.
#
# The marketing-compliance-gate governance stack owns the perimeter in the reference topology. This module keeps the
# complete contract so ownership can be moved deliberately, but defaults to count = 0. Never
# set manage_shared_vpc_sc_perimeter in both states.
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/access_context_manager_service_perimeter

locals {
  perimeter_restricted_services = [
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudtrace.googleapis.com",
    "discoveryengine.googleapis.com",
    "logging.googleapis.com",
    "modelarmor.googleapis.com",
    "run.googleapis.com",
  ]

  shared_perimeter_resources = [
    "projects/${var.shared_vpc_host_project_number}",
    "projects/${var.mkt5_project_number}",
    "projects/${var.mkt6_project_number}",
  ]
}

resource "google_access_context_manager_service_perimeter" "nba" {
  count = var.enable_vpc_sc && var.manage_shared_vpc_sc_perimeter ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/${var.shared_vpc_sc_perimeter_name}"
  title  = var.shared_vpc_sc_perimeter_name

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  # ENFORCED status : populated only when NOT in dry-run.
  dynamic "status" {
    for_each = var.vpc_sc_dry_run ? [] : [1]
    content {
      resources           = local.shared_perimeter_resources
      restricted_services = local.perimeter_restricted_services

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  # DRY-RUN spec : evaluated and logged, never blocks. Watch the audit logs, then enforce.
  use_explicit_dry_run_spec = var.vpc_sc_dry_run

  dynamic "spec" {
    for_each = var.vpc_sc_dry_run ? [1] : []
    content {
      resources           = local.shared_perimeter_resources
      restricted_services = local.perimeter_restricted_services

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  depends_on = [google_project_service.required]
}
