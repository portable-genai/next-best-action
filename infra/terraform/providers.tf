# providers.tf : Provider pinning for the Mkt5 Next-Best-Action sovereign deploy.
#
# Principle map (SPEC.md invariants + README residency posture):
#   Residency : every provider call is pinned to var.region (the allow-listed selection).
#               There is no global / multi-region default. The app mirrors this with the
#               per-market allow-list in adapters/gcp/_region.py (SG => asia-southeast1).
#   No lock-in : Terraform is the only place infra is described; the app talks to ports
#               (SPEC.md "Ports" table), not to these resources.
#
# google-beta is required because Model Armor templates and some org-policy / Access
# Context Manager surfaces are only exposed on the beta provider as of the pinned line.

terraform {
  # Cross-variable validation keeps the Shared VPC and perimeter membership internally
  # consistent; Terraform 1.9 is the first supported line for that contract.
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.40, < 7.0"
    }
  }
}

# Primary (GA) provider : every resource defaults to Singapore.
provider "google" {
  project = var.project_id
  region  = var.region # the selected region : pinned, never global
}

# Beta provider : same project/region, used only where a resource needs it (Model Armor).
provider "google-beta" {
  project = var.project_id
  region  = var.region
}
