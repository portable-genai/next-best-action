# Mkt5 Next-Best-Action : deploy infrastructure (Terraform)

This directory makes the Mkt5 Next-Best-Action service's cloud posture enforceable at deploy
time, not merely documented. Residency, encryption, perimeter, and audit are pinned here so
`terraform plan` fails when a deploy would violate them, and a reviewer can read the control
next to the resource it governs.

Reference cloud: Google Cloud. The region is selected at deploy time and validated in
`variables.tf` against the residency allow-list `allowed_regions` (and again at app settings
load via `adapters/gcp/_region.py`), so code and infra share one residency boundary. Both
variables default to Singapore (`asia-southeast1`), making this a Singapore (SG market)
deployment out of the box; the JP and AU markets are separate deployments, each selecting its
own region and allow-list.

## What gets created

| File | Purpose |
| ---- | ------- |
| `providers.tf` | Provider + region pinning (google + google-beta), both wired to `var.region`. |
| `variables.tf` | The only knobs: project / org ids, existing Shared VPC resource names, shared-perimeter membership/ownership, retention, image, channels, and reviewed Mkt6 URL/OIDC audience. Region validated against `allowed_regions`; both default to `asia-southeast1`. |
| `terraform.tfvars.example` | Fictional sample values for a Singapore deploy. |
| `apis.tf` | Enables only the managed services the gcp adapters use (see mapping below). |
| `org_policy.tf` | Residency allowlist, disable SA-key creation, no external IPs, uniform bucket access. |
| `kms.tf` | One regional CMEK key + a per-service IAM binding (BigQuery, Discovery Engine, Vertex, Logging, Cloud Run). |
| `bigquery.tf` | The recommendation / propensity feature dataset, in-region, CMEK; Mkt5 owns no consent table. |
| `model_armor.tf` | The `mkt-nba-guardrail` template the guardrail adapter screens with. |
| `network.tf` | Validates the existing Shared VPC subnet and grants the Cloud Run service agent least-privilege network viewer/subnet user roles. |
| `vpc_sc.tf` | Shared Mkt5/Mkt6/host-project regular perimeter contract, dry-run first; Mkt6 owns it by default. |
| `logging_worm.tf` | Locked (WORM) audit log bucket + sink + data-access audit config. |
| `monitoring.tf` | Log-based metrics + alert policies on the posture-violation signals. |
| `iam.tf` | Least-privilege Cloud Run runtime service account (no broad roles). |
| `cloud_run.tf` | The FastAPI service as `google_cloud_run_v2_service` (port 8104, CMEK, internal ingress, Direct VPC all-traffic egress, `/healthz` probes, `MKT_NBA_PROFILE=gcp`). |
| `agent_runtime.tf` | CMEK-encrypted, in-region staging bucket for the Agent Runtime (reasoningEngine) deploy. |
| `outputs.tf` | The ids / urls to export into the runtime environment after apply. |

## Service -> adapter mapping (why each API is enabled)

Only the services the pinned `gcp` profile actually uses are enabled (`config/settings.yaml`
`adapters:`):

- `aiplatform` : recommendation (Vertex recommendations + propensity), llm (Gemini),
  evaluation (Gen AI eval), agent runtime, A2A registry / MCP tool catalog.
- `bigquery` : the recommendation feature store (`recommendation.bigquery_dataset = mkt_nba`).
- `discoveryengine` : the knowledge_base offer / policy corpus (File / Agent Search).
- `modelarmor` : the guardrail (`model_armor.template_id = mkt-nba-guardrail`).
- `logging` : the WORM audit sink (`logging.bucket = next-best-action-worm`).
- `cloudtrace` : the observability tracer.
- `run` + `artifactregistry` : the Cloud Run API service and its image.
- `cloudkms`, `orgpolicy`, `accesscontextmanager`, `monitoring`, `compute`, `iam` : the
  posture controls themselves.
- Mkt6 consent is an HTTPS service contract, not another local data API: Cloud Run receives
  `MKT_CONSENT_STORE_URL` plus the reviewed custom `MKT_CONSENT_STORE_AUDIENCE`; the adapter
  lazily mints a short-lived Google ID token through the runtime Workload Identity.

## Controls (SPEC.md invariants + README residency posture)

This repo has no `COMPLIANCE.md`; the controls below realize the SPEC.md invariants
("deterministic under the local profile", "requires_human_review", "every recommendation
carries a citation") plus the residency posture stated in `README.md`.

1. Residency selected + validated : `var.region` is constrained to the `var.allowed_regions`
   allow-list (default `["asia-southeast1"]`) and rejected at plan time otherwise; the app
   validates its own region at settings load.
2. Location Org Policy : `gcp.resourceLocations` pins where resources may be created, plus
   disable-SA-keys, no-external-IP, uniform-bucket-access.
3. Managed-first, minimal surface : `apis.tf` enables only the services used; Cloud Run
   ingress is internal + load balancer, not the open internet.
4. CMEK does not cascade : one regional key, an explicit IAM binding per service agent.
5. VPC-SC perimeter, dry-run first : `vpc_sc_dry_run = true` by default; watch the audit logs,
   then set it false to enforce.
6. WORM audit logs : a locked Cloud Logging bucket (~7-year retention); the app redacts before
   it logs.
7. Posture alerts : log-based alerts on guardrail blocks, SA-key creation, VPC-SC denials, and
   CMEK key changes.
8. One consent authority : Mkt6 owns consent state. Mkt5 provisions no consent table and its
   managed adapter fails closed unless the reviewed HTTPS URL and OIDC audience are present.
   Mkt6 separately grants this runtime identity Cloud Run invoker and verifies it in-app.
9. One network and perimeter path : Mkt5 and Mkt6 use an existing Shared VPC subnet with
   Private Google Access and sit in one regular VPC-SC perimeter with its host project. Mkt5
   sends `ALL_TRAFFIC` through Direct VPC egress, so Mkt6 can remain internal-only. The custom
   OIDC audience and exact invoker IAM remain independent application/service identity gates.

## Required shared topology

The application modules do not create or own the horizontal Shared VPC. Before planning them,
the network owner must:

1. create the host network and a region-local `/26` or larger subnet with Private Google
   Access enabled;
2. associate **both** Mkt5 and Mkt6 service projects with that Shared VPC host;
3. permit the application Terraform identity to read host networking and add the two narrow
   IAM grants in `network.tf`; and
4. provide the same access policy id, perimeter short name, host project number, Mkt5 project
   number and Mkt6 project number to both repos.

Mkt6 is the sole perimeter owner in the reference topology
(`manage_shared_vpc_sc_perimeter = true` there and `false` here). A project can belong to only
one regular perimeter, so never enable ownership in both Terraform states. If ownership must
move, use a reviewed Terraform state move/import before the first apply from the new owner.
The three project-number values are numeric project **numbers**, not ids.

The managed call targets Mkt6's default `run.app` `service_url`. Mkt5 must use Direct VPC
egress with `ALL_TRAFFIC`; `PRIVATE_RANGES_ONLY` would let this non-RFC1918 destination bypass
the VPC and fail Mkt6 internal ingress. Private Google Access keeps that request on the VPC
path. Cloud NAT is additionally required only if other Mkt5 dependencies need public internet
destinations.

## Usage

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # then edit ids (do NOT commit terraform.tfvars)

terraform init
terraform plan      # or: make tf-plan  (from the repo root)
terraform apply
```

Offline / no-credentials validation (what CI and the repo's `make tf-plan` rely on for shape):

```bash
terraform fmt -recursive
terraform init -backend=false
terraform validate
```

### Rollout order for the shared perimeter and consent route

1. Apply the horizontal Shared VPC and associate both service projects.
2. Apply Mkt6 (the perimeter owner) with `enable_vpc_sc = true` and
   `vpc_sc_enforce = false`; capture its `service_url` and `s2s_audience` outputs.
3. Put those outputs into this module's `consent_store_url` and
   `consent_store_audience`, then plan/apply Mkt5 with
   `manage_shared_vpc_sc_perimeter = false`.
4. Verify an authenticated Mkt5 request reaches Mkt6 while an internet request to the Mkt6
   `run.app` URL is rejected. Add your operator / CI identity to an access level and watch the audit logs
   (`VpcServiceControlAuditMetadata`, surfaced by `monitoring.tf`) for legitimate paths that
   would be denied.
5. Promote the **owner's** `vpc_sc_enforce` to `true`. This module's legacy
   `vpc_sc_dry_run` toggle is relevant only if perimeter ownership is deliberately transferred
   here. Never enforce blind.

## Warnings

- Locking the WORM bucket (`locked = true`) is IRREVERSIBLE. Confirm `retention_days` first.
- The CMEK key has `prevent_destroy = true`: a destroyed key strands all encrypted data.
- No secrets live in this directory. `terraform.tfvars` (your real ids) is git-ignored; only
  the fictional `terraform.tfvars.example` is committed. The Mkt6 URL and custom audience
  are routing/policy identifiers, not credentials; short-lived ID tokens come from Workload
  Identity and no bearer value is persisted in Terraform state.
