# apis.tf : Enable exactly the managed services next-best-action depends on (SPEC.md Ports table).
#
# Principle map:
#   Managed-first / minimal surface : only the services the pinned gcp profile actually
#               uses are enabled : nothing speculative. Each maps to an adapter binding in
#               config/settings.yaml under `adapters:`.
#   Residency : enabling these APIs is a prerequisite for the regional, CMEK-protected
#               resources defined in the sibling files.
#
# disable_on_destroy = false so a `terraform destroy` of this stack does not yank platform
# APIs out from under other workloads in a shared project.
#
# Adapter -> API mapping:
#   recommendation (VertexRecommendationAdapter) : aiplatform + bigquery (feature dataset)
#   knowledge_base (FileSearchKnowledgeBaseAdapter) : discoveryengine (File / Agent Search)
#   llm (GeminiLLMAdapter) + evaluation (GenAiEvalAdapter) : aiplatform
#   guardrail (ModelArmorGuardrailAdapter) : modelarmor
#   audit (CloudLoggingAuditAdapter) : logging (WORM locked bucket)
#   tracer (CloudTraceTracerAdapter) : cloudtrace
#   agent_registry / tool_catalog : A2A + MCP over aiplatform (no extra API surface)
#   Cloud Run service : run + artifactregistry (image pull)

locals {
  required_services = [
    "aiplatform.googleapis.com",           # Vertex AI: recommendations, propensity, Gemini, eval, agent
    "bigquery.googleapis.com",             # BigQuery feature dataset (recommendation adapter)
    "discoveryengine.googleapis.com",      # File / Agent Search (knowledge_base adapter)
    "modelarmor.googleapis.com",           # Model Armor guardrail template (guardrail adapter)
    "logging.googleapis.com",              # Cloud Logging (WORM locked bucket + audit)
    "cloudtrace.googleapis.com",           # Cloud Trace (OpenTelemetry spans)
    "run.googleapis.com",                  # Cloud Run v2 (the API service)
    "artifactregistry.googleapis.com",     # Artifact Registry (the API image)
    "cloudkms.googleapis.com",             # Regional CMEK key ring + key
    "orgpolicy.googleapis.com",            # Org Policy residency constraints
    "accesscontextmanager.googleapis.com", # VPC Service Controls perimeter
    "monitoring.googleapis.com",           # Log-based metrics + posture alert policies
    # Supporting services the above transitively require.
    "compute.googleapis.com", # VPC / networking for the perimeter
    "iam.googleapis.com",     # Service accounts / least-privilege IAM
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
