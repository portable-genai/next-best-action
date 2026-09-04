# cloud_run.tf : Cloud Run v2 service for the next-best-action Next-Best-Action API.
#
# Principle map:
#   Managed-first : the FastAPI service (next_best_action.api.app:app) runs on Cloud Run as
#               the dedicated least-privilege runtime identity (iam.tf, Workload Identity, no
#               keys), encrypted with the regional CMEK key.
#   Residency : the service is created in var.region; MKT_NBA_PROFILE=gcp is set
#               EXPLICITLY here (an unset variable is "no choice", which binds the SDK-free
#               adapters and refuses every end-user request, so production must set it).
#   Minimal surface : ingress is internal + load balancer, not the open internet. All egress
#               uses Direct VPC egress on the reviewed Shared VPC, which is required for the
#               marketing-compliance-gate internal-only run.app endpoint to recognise next-best-action as an internal source.
#
# The container listens on 8104 (Dockerfile EXPOSE / PORT) and serves /healthz.
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_service

resource "google_cloud_run_v2_service" "nba" {
  name     = "next-best-action"
  location = var.region # the selected region (residency)
  project  = var.project_id

  # Internal + load balancer ingress : not exposed directly to the public internet.
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    # Encrypt the revision with the regional CMEK key (CMEK does not cascade : kms.tf binds
    # the Cloud Run service agent).
    encryption_key                   = google_kms_crypto_key.nba.id
    service_account                  = google_service_account.runtime.email
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 1
      max_instance_count = 4
    }

    # ALL_TRAFFIC is deliberate. A run.app URL is not an RFC1918 destination; routing only
    # private ranges would bypass the VPC and marketing-compliance-gate's internal ingress would reject the call.
    vpc_access {
      egress = "ALL_TRAFFIC"

      network_interfaces {
        network    = var.shared_vpc_network
        subnetwork = var.shared_vpc_subnetwork
        tags       = ["mkt5-managed-egress"]
      }
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8104 # matches Dockerfile EXPOSE / PORT
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      # Opt in to the managed stack EXPLICITLY (never rely on a baked-in default to select
      # cloud). The app reads MKT_NBA_PROFILE; settings.yaml defaults to asia-southeast1.
      env {
        name  = "MKT_NBA_PROFILE"
        value = "gcp"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "MKT_MARKET"
        value = "SG"
      }
      env {
        name  = "PORT"
        value = "8104"
      }
      env {
        name  = "MKT_CONSENT_STORE_URL"
        value = var.consent_store_url
      }
      env {
        name  = "MKT_CONSENT_STORE_AUDIENCE"
        value = var.consent_store_audience
      }

      startup_probe {
        http_get {
          path = "/healthz"
          port = 8104
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8104
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [
    google_project_iam_member.cloud_run_shared_vpc_viewer,
    google_compute_subnetwork_iam_member.cloud_run_shared_vpc_user,
    google_kms_crypto_key_iam_member.run,
    google_project_iam_member.runtime_aiplatform_user,
    google_project_iam_member.runtime_bq_data_viewer,
  ]

  lifecycle {
    precondition {
      condition     = tostring(data.google_project.this.number) == var.mkt5_project_number
      error_message = "mkt5_project_number must be the numeric project number resolved from project_id."
    }

    precondition {
      condition     = tostring(data.google_project.shared_vpc_host.number) == var.shared_vpc_host_project_number
      error_message = "shared_vpc_host_project_number must match the host project encoded in shared_vpc_network."
    }

    precondition {
      condition     = data.google_compute_subnetwork.shared_cloud_run.private_ip_google_access
      error_message = "The Shared VPC subnet must enable Private Google Access so all-traffic egress can reach marketing-compliance-gate without leaving the VPC path."
    }

    precondition {
      condition     = tonumber(split("/", data.google_compute_subnetwork.shared_cloud_run.ip_cidr_range)[1]) <= 26
      error_message = "Direct VPC egress requires the Shared VPC subnet to be /26 or larger."
    }

    precondition {
      condition     = endswith(data.google_compute_subnetwork.shared_cloud_run.network, var.shared_vpc_network)
      error_message = "shared_vpc_subnetwork does not belong to shared_vpc_network."
    }
  }
}
