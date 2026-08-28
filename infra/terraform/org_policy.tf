# org_policy.tf : Org Policy constraints enforcing Singapore residency + key hygiene.
#
# Principle map:
#   Residency (defence in depth) : even if someone hand-edits a resource, these org policies
#               REJECT the creation of resources outside Singapore. gcp.resourceLocations is
#               the master residency control.
#   No SA keys : disable service-account key creation : the runtime uses Workload Identity
#               (iam.tf), never exported keys. Key creation is also one of the posture alert
#               signals (monitoring.tf).
#   Private data plane : disable VM external IPs and require uniform bucket-level access so
#               data and compute stay in-country and private.
#
# Scoped to the project via google_project. To enforce org-wide, move these to an org-level
# policy with parent = "organizations/${var.org_id}".
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/org_policy_policy

# Master residency policy: only allow locations inside the selected region.
resource "google_org_policy_policy" "resource_locations" {
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        # e.g. "in:asia-southeast1-locations" : the selected region plus its sub-locations.
        # var.resource_location_values overrides this only where a required service has no
        # single-region presence (Agent Search has none at all; Document AI has none until
        # in-region access is granted). See that variable: widening is a jurisdiction
        # statement, not an exception list.
        allowed_values = length(var.resource_location_values) > 0 ? var.resource_location_values : ["in:${var.region}-locations"]
      }
    }
  }

  depends_on = [google_project_service.required]
}

# Disable service-account key creation : use Workload Identity instead (no exported keys).
resource "google_org_policy_policy" "disable_sa_keys" {
  name   = "projects/${var.project_id}/policies/iam.disableServiceAccountKeyCreation"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Disable VM external IPs : keep the data plane private.
resource "google_org_policy_policy" "no_external_ip" {
  name   = "projects/${var.project_id}/policies/compute.vmExternalIpAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      deny_all = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require uniform bucket-level access (no per-object ACL exfiltration paths).
resource "google_org_policy_policy" "uniform_bucket_access" {
  name   = "projects/${var.project_id}/policies/storage.uniformBucketLevelAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}
