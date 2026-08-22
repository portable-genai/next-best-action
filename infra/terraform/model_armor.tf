# model_armor.tf : Model Armor guardrail template 'mkt-nba-guardrail'.
#
# Principle map:
#   Safety at the boundary : every prompt / response is screened by Model Armor for
#               prompt-injection / jailbreak, malicious URLs, and RAI categories BEFORE it
#               reaches the model. The guardrail adapter (ModelArmorGuardrailAdapter) calls
#               :sanitizeUserPrompt / :sanitizeModelResponse against this template on both
#               the INPUT and OUTPUT legs of the recommend pipeline (SPEC.md steps 1 + 10).
#   Residency : the template lives in var.region.
#
# The template id matches config/settings.yaml model_armor.template_id (mkt-nba-guardrail).
# verify: https://registry.terraform.io/providers/hashicorp/google-beta/latest/docs/resources/model_armor_template

resource "google_model_armor_template" "nba_guardrail" {
  provider    = google-beta
  project     = var.project_id
  location    = var.region          # the selected region (residency)
  template_id = "mkt-nba-guardrail" # matches settings.yaml model_armor.template_id

  filter_config {
    # --- Responsible AI floor: block high-confidence harmful content. --- #
    rai_settings {
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }

    # --- Prompt injection & jailbreak floor. --- #
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "LOW_AND_ABOVE"
    }

    # --- Malicious URL floor. --- #
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
  }

  # Audit hygiene: log that operations ran, but never log the sanitized payloads (content
  # stays out of logs : customer data never lands in a log line).
  template_metadata {
    log_sanitize_operations = true
    log_template_operations = true
    enforcement_type        = "INSPECT_AND_BLOCK"
  }

  depends_on = [google_project_service.required]
}
