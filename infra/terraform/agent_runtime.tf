# agent_runtime.tf : staging for the Agent Runtime (reasoningEngine) deploy.
#
# Principle map:
#   Managed-first : the ADK agent (src/next_best_action/agent/) is hosted on Agent Runtime
#               (reasoningEngine), not self-managed infra. Its A2A AgentCard is registered
#               via the agent_registry port; settings.yaml agent_engine.resource_name is set
#               after deploy.
#   Residency : the reasoningEngine and its staging bucket are created in var.region.
#   CMEK explicit : the staging bucket uses the regional CMEK from kms.tf.
#
# The reasoningEngine itself is created by the Agent Platform SDK at deploy time (the build
# artifact is a packaged Python agent), not by Terraform. This file reserves the in-region,
# CMEK-encrypted staging bucket the SDK uploads to.
# verify: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/deploy

resource "google_storage_bucket" "agent_staging" {
  name                        = "${var.project_id}-mkt-nba-agent-staging"
  project                     = var.project_id
  location                    = var.region # the selected region : in-country staging (residency)
  uniform_bucket_level_access = true
  force_destroy               = false

  encryption {
    default_kms_key_name = google_kms_crypto_key.nba.id # CMEK
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.aiplatform,
  ]
}
