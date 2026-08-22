# variables.tf : The only knobs. Everything else is a concrete in-region value.
#
# Principle map:
#   Residency : `region` is SELECTED AT DEPLOY TIME and validated against the residency
#               allow-list `allowed_regions`, so a caller fails fast rather than deploying
#               to an unvetted region. Both default to asia-southeast1 (the SG market), so
#               the out-of-the-box posture is unchanged and deploying elsewhere means
#               setting BOTH variables. The app validates its own region at settings load
#               (adapters/gcp/_region.py), so code and infra share one residency boundary.
#   Auditability / retention : `retention_days` is a variable (the WORM bucket lock is
#               irreversible, so retention must be a deliberate input). Mirrors
#               config/settings.yaml logging.retention_days (2557, ~7 years).
#
# Per the build contract, ONLY project_id and a few genuinely per-tenant values (org /
# billing ids, the VPC-SC toggle, notification channels, the image ref) are variables.
# All service identifiers, locations, and template names are concrete.

variable "project_id" {
  description = "Target GCP project id (required). Single-tenant, Singapore-resident."
  type        = string
}

variable "allowed_regions" {
  description = <<-EOT
    Residency allow-list: the regions this stack may be deployed to. The region is chosen at
    deploy time (var.region) and validated against this list to FAIL FAST, so an operator
    cannot accidentally deploy to an unvetted region. Extending this list is the deliberate
    residency review point: add a region only after confirming the full managed stack
    (Vertex AI / Agent Platform, Model Armor, DLP, BigQuery, Cloud Run, Cloud KMS, Logging)
    and your residency obligations are satisfied in that region.
  EOT
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Defaults to asia-southeast1 (Singapore, the
    SG market profile in config/settings.yaml) but is overridable. Validated against
    var.allowed_regions so an unapproved region fails fast at `terraform plan` rather than
    deploying data out of jurisdiction. JP/AU are separate deployments, each selecting its
    own region and its own allow-list.
  EOT
  type        = string
  default     = "asia-southeast1"

  validation {
    # Cross-variable validation (Terraform >= 1.9). Fails at plan time = setup time.
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (residency allow-list). Add it there first if that region is approved for this workload."
  }
}

variable "zone" {
  description = "Default zone for zonal resources. Must lie inside the selected var.region."
  type        = string
  default     = "asia-southeast1-a"

  validation {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "zone must be a zone of the selected region (e.g. \"${var.region}-a\")."
  }
}

variable "retention_days" {
  description = "WORM audit-log retention in days. Default ~7 years. Lock is irreversible."
  type        = number
  default     = 2557 # ~7 years; mirrors config/settings.yaml logging.retention_days

  validation {
    condition     = var.retention_days >= 2557
    error_message = "Compliance retention must be at least 2557 days (~7 years)."
  }
}

variable "org_id" {
  description = "Organization id : required for Org Policy and Access Context Manager."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (used for FinOps tagging). Optional."
  type        = string
  default     = ""
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the org.
    Required when enable_vpc_sc = true; the service perimeter is created under it.
    Create once per org with:
      gcloud access-context-manager policies create \
        --organization=ORG_ID --title="sg-residency"
  EOT
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_vpc_sc || can(regex("^[0-9]{6,20}$", var.access_policy_id))
    error_message = "access_policy_id must be numeric when the shared VPC-SC contract is enabled."
  }
}

variable "enable_vpc_sc" {
  description = "Participate in the shared Mkt5/Mkt6 VPC-SC perimeter contract. The designated owner creates it."
  type        = bool
  default     = true
}

variable "manage_shared_vpc_sc_perimeter" {
  description = <<-EOT
    Whether this module owns the one regular perimeter shared by Mkt5, Mkt6 and their Shared
    VPC host project. Exactly one stack may own it. The governance (Mkt6) stack owns it in the
    reference topology, so this default is false; this stack still declares and validates the
    exact shared membership it expects.
  EOT
  type        = bool
  default     = false
}

variable "shared_vpc_sc_perimeter_name" {
  description = "Short name of the single regular VPC-SC perimeter shared by Mkt5 and Mkt6."
  type        = string
  default     = "mkt_marketing_sg"

  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{0,49}$", var.shared_vpc_sc_perimeter_name))
    error_message = "shared_vpc_sc_perimeter_name must be a lower-case Access Context Manager short name (max 50 characters)."
  }
}

variable "mkt5_project_number" {
  description = "Numeric project number of the Mkt5 service project; included in the shared perimeter."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{6,20}$", var.mkt5_project_number))
    error_message = "mkt5_project_number must be a numeric GCP project number, not a project id."
  }
}

variable "mkt6_project_number" {
  description = "Numeric project number of the Mkt6 service project; included in the shared perimeter."
  type        = string

  validation {
    condition = (
      can(regex("^[0-9]{6,20}$", var.mkt6_project_number)) &&
      var.mkt6_project_number != var.mkt5_project_number
    )
    error_message = "mkt6_project_number must be numeric and distinct from mkt5_project_number."
  }
}

variable "shared_vpc_host_project_number" {
  description = "Numeric project number of the Shared VPC host; VPC-SC requires the host in the same regular perimeter."
  type        = string

  validation {
    condition = (
      can(regex("^[0-9]{6,20}$", var.shared_vpc_host_project_number)) &&
      !contains(
        [var.mkt5_project_number, var.mkt6_project_number],
        var.shared_vpc_host_project_number,
      )
    )
    error_message = "shared_vpc_host_project_number must be numeric and distinct from both service-project numbers."
  }
}

variable "vpc_sc_dry_run" {
  description = <<-EOT
    Stand the perimeter up in DRY-RUN first (spec only, no enforcement). Watch the audit
    logs for legitimate paths denied, then flip to false to enforce. Only the perimeter-owner
    module's value has an effect. Never enforce blind.
  EOT
  type        = bool
  default     = true
}

variable "container_image" {
  description = "Fully-qualified API image (Artifact Registry, asia-southeast1)."
  type        = string
  default     = "asia-southeast1-docker.pkg.dev/REPLACE_WITH_PROJECT/mkt/next-best-action:0.1.0"
}

variable "shared_vpc_network" {
  description = "Fully-qualified existing Shared VPC network: projects/HOST_PROJECT/global/networks/NETWORK."
  type        = string

  validation {
    condition = can(regex(
      "^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/global/networks/[a-z][a-z0-9-]{0,61}[a-z0-9]$",
      var.shared_vpc_network,
    ))
    error_message = "shared_vpc_network must be a fully-qualified projects/HOST_PROJECT/global/networks/NETWORK resource name."
  }
}

variable "shared_vpc_subnetwork" {
  description = "Fully-qualified existing Shared VPC subnet. It must be in region, on shared_vpc_network, and have Private Google Access."
  type        = string

  validation {
    condition = (
      can(regex(
        "^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/regions/${var.region}/subnetworks/[a-z][a-z0-9-]{0,61}[a-z0-9]$",
        var.shared_vpc_subnetwork,
      )) &&
      try(split("/", var.shared_vpc_subnetwork)[1], "") == try(split("/", var.shared_vpc_network)[1], "")
    )
    error_message = "shared_vpc_subnetwork must be fully qualified, in var.region, and owned by the same host project as shared_vpc_network."
  }
}

variable "consent_store_url" {
  description = "Reviewed HTTPS base URL of the Mkt6 consent authority. Loopback is forbidden for this managed stack."
  type        = string

  validation {
    condition = can(regex(
      "^https://[^/[:space:]]+(?::[0-9]+)?(?:/[^[:space:]]*)?$",
      var.consent_store_url
    )) && !can(regex("^https://(?:localhost|127\\.0\\.0\\.1|\\[::1\\])", var.consent_store_url))
    error_message = "consent_store_url must be a reviewed non-loopback HTTPS Mkt6 URL."
  }
}

variable "consent_store_audience" {
  description = "Reviewed custom OIDC audience configured on Mkt6. It must match MKT6_S2S_AUDIENCE exactly."
  type        = string

  validation {
    condition     = can(regex("^https://[^[:space:]]+$", var.consent_store_audience))
    error_message = "consent_store_audience must be a reviewed nonblank HTTPS audience."
  }
}

variable "alert_notification_channels" {
  description = "Monitoring notification channel ids for the posture alerts (empty = none)."
  type        = list(string)
  default     = []
}
