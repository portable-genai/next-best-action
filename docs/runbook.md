# Runbook: Mkt5 Next-Best-Action Recommendations and Cross-Sell Engine

Operational notes for deploying and running Mkt5 on the Gemini Enterprise Agent Platform in a
residency region (defaults `asia-southeast1`; JP and AU are per-market overrides). Mkt5 is the
only per-customer marketing repo, so the PII, tenancy and consent controls below are
load-bearing. This is a reference build; adapt it to your own change-management and model-risk
sign-off before any live use.

## 0. Profiles

`MKT_NBA_PROFILE` selects the adapter stack. It has **no default**: an unset (or blank)
variable is treated as "no profile was chosen", which binds the SDK-free adapters so the
process still boots but grants none of the local relaxations. The seeded dev personas are
refused (every end-user route answers 401) and the CORS dev origins are withheld. Name the
profile deliberately. An unknown or mis-capitalised value (`Local`, `GCP`) is refused outright
rather than silently selecting neither the relaxations nor the restrictions.

- `local` (SDK-free): the whole pipeline runs offline (deterministic recommender and LLM,
  in-memory customers / offers, fictional Mkt6 consent stand-in using canonical wire types).
  No Google Cloud SDK. This is what CI and the demo run.
- `gcp`: the managed stack (Vertex recommendations, BigQuery features, Cloud DLP, Model Armor,
  Cloud Logging).
- `platform`: consume the shared Hrz services (guardrail / KB / audit / eval / registry) over
  S2S.
- `onprem`: fail-fast placeholders that raise `NotImplementedError`, the migration target (see
  `docs/onprem-migration.md`).

Managed profiles also require `MKT_CONSENT_STORE_URL` and `MKT_CONSENT_STORE_AUDIENCE`; the GCP
adapter mints an audience-bound Google ID token through Workload Identity. The kit resolves
`CONSENT_S2S_TOKEN` and optional `CONSENT_S2S_SIGNING_KEY` only for non-GCP consumers. An absent store URL
or unavailable answer suppresses the candidate. There is no BigQuery consent fallback.

`MKT_VERTICAL` (`banking` | `online_retail`) and `MKT_MARKET` (`JP` | `AU` | `SG`) select the
active vertical and market; the market's residency region and locales come from the per-market
profile in `config/settings.yaml`, never a hard-coded branch.

## 1. Offline demo and smoke (no cloud)

```bash
make demo          # recommend + render the static audit-first HTML into scripts/out
make smoke-local   # end-to-end offline: recommend for one customer under the local profile
make run-api       # FastAPI on 127.0.0.1:8104 (local profile binds loopback by default)
```

The agent card is served at `GET /.well-known/agent-card.json` and the health probe at
`GET /healthz`. Recommendation requests resolve a **server-verified** principal; a customer
outside the caller's tenant is denied with 403 (never 200 or 404).

## 2. Deploy (managed stack)

The network platform must first associate both service projects with the existing Shared VPC
host and provide a `/26` or larger Singapore subnet with Private Google Access. Apply Mkt6
before Mkt5: Mkt6 owns the single regular VPC-SC perimeter and supplies the `service_url` and
`s2s_audience` values used below. Keep this repo's
`manage_shared_vpc_sc_perimeter = false`; the host, Mkt5 and Mkt6 numeric project numbers and
the perimeter name must exactly match Mkt6's inputs.

```bash
# 1. Provision infra (review the plan; the WORM bucket lock is irreversible when
#    locked = true, the default).
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id, org_id, access_policy_id
terraform init -input=false && terraform plan
terraform apply

# 2. Export the outputs the app reads.
export GOOGLE_CLOUD_PROJECT="$(terraform output -raw project_id)"
export MKT_NBA_REGION="$(terraform output -raw region)"
export MKT_NBA_CMEK_KEY="$(terraform output -raw cmek_key)"
export MKT_NBA_MODEL_ARMOR_TEMPLATE="$(terraform output -raw model_armor_template)"
export MKT_NBA_LOG_BUCKET="$(terraform output -raw log_bucket)"

# 3. Install the managed stack and run the API. Every pinned kit is public, so this needs no
#    source credential.
pip install -e ".[gcp,dev]"
export GOOGLE_CLOUD_PROJECT=your-sg-project MKT_NBA_PROFILE=gcp
export MKT_CONSENT_STORE_URL=https://mkt6.example.internal
export MKT_CONSENT_STORE_AUDIENCE=https://mkt6-consent.internal.example
gcloud auth application-default login
make run-api PROFILE=gcp          # FastAPI on :8104 (front with the platform ingress)
```

For a quick project-scoped evaluation WITHOUT org-level prerequisites, set `enable_vpc_sc =
false` and the audit bucket `locked = false` so everything stays deletable (not compliant for
production, and never with real customer data). See `infra/terraform/terraform.tfvars.example`
and `infra/terraform/README.md`.

The managed consent route uses Mkt5 Direct VPC egress with `ALL_TRAFFIC`, the Mkt6 default
`run.app` URL, and Mkt6's fixed internal-only ingress. Do not switch to private-ranges-only or
an internet-facing custom domain: the former bypasses the VPC for `run.app`, and the latter is
correctly rejected. OIDC audience/caller verification and Cloud Run invoker IAM remain
mandatory even on the internal network.

The ADK agent is deployed to Agent Runtime separately via the Agent Platform SDK; see the
docstring in `src/next_best_action/agent/root_agent.py`. Record the resulting `reasoningEngine`
resource name in `settings.agent_engine.resource_name` (or `MKT_AGENT_ENGINE`). To attach an
out-of-process governed MCP tool server, set `MKT_NBA_MCP_SERVER_URL`; unset, the agent uses
its in-process FunctionTools.

## 3. PII redaction and the jurisdiction pack

Customer PII is redacted before any model / span / audit call (P-04, R1). The
national-identifier detectors come from the shared, versioned `pii-kit`
(`adapters/gcp/dlp_redaction.py`), so switching markets switches the detectors: confirm the
`pii-kit` rows for the active market are the ones you intend to scrub and gate on. The DLP
inspect / de-identify templates are region-pinned like every other resource.

## 4. Region selection and fail-fast

The Terraform `region` is validated against the residency allowlist; an apply against a region
outside it fails at `terraform plan`, before anything is created. Vertex, BigQuery, DLP, Cloud
Logging and the WORM bucket are all created in the selected region, and a `gcp.resourceLocations`
Org Policy hard-restricts resource creation to it. The app also validates the active market's
region at load, so a mismatched deploy fails fast on both sides.

## 5. Key rotation, retention and the WORM lock

The CMEK crypto key (`kms.tf`) rotates on schedule; rotation is transparent to the app. The
audit bucket retention is `retention_days` (default 2557, ~7 years) and the bucket is
`locked = true` by default, which is **irreversible**. To trial without locking, set
`locked = false` (not compliant for production). Only redacted prompts / responses are ever
written to the audit log (P-04, R1).

## 6. Kill switch

To stop serving without tearing down state: scale the Cloud Run / Agent Runtime deployment to
zero, or remove the app service account's `roles/aiplatform.user` binding. The audit trail
remains intact.

## 7. Common failures

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `NotImplementedError` from a CLI command (exit 2) | `MKT_NBA_PROFILE=onprem` with placeholder adapters | Set `MKT_NBA_PROFILE=gcp` (or implement the on-prem adapter) |
| HTTP 403 on recommend | Cross-tenant object reference (customer not in the principal's tenant) | Expected fail-closed behaviour; use an entitled identity |
| `UnknownCustomerError` (HTTP 404) | No such customer in the source | Confirm the `customer_id`, market and vertical |
| `NoCandidatesError` (HTTP 404) | No eligible, consented offers for the customer | Expected when everything is held / consent-suppressed; check consent and eligibility |
| Every candidate is consent-suppressed | Mkt6 URL, OIDC audience/caller policy, or decision is unavailable | Check `MKT_CONSENT_STORE_URL`, `MKT_CONSENT_STORE_AUDIENCE`, Mkt6's caller allowlist and Cloud Run invoker grant; do not add a local production fallback |
| Guardrail block on a benign request (HTTP 400) | Model Armor template too strict | Tune the `model_armor` template filter confidence levels |
| Mkt6 returns an ingress 404/403 before app verification | Mkt5 did not route the `run.app` request through the Shared VPC | Confirm both projects are associated to the same host, the subnet has Private Google Access, and Mkt5 Direct VPC egress is `ALL_TRAFFIC` |
| VPC-SC denies the apply or consent hop | Projects are in distinct perimeters, the Shared VPC host is absent, or the runner is outside the perimeter | Confirm Mkt6 solely owns one dry-run perimeter containing host + Mkt5 + Mkt6; review dry-run denials before the owner enforces it |
