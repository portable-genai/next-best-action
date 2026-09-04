# Adopting this repo as your base

This repository is a **common base** for building a per-customer **next-best-action /
cross-sell** agent. It ships a reusable hexagonal core (a pure-stdlib domain, typed ports,
swappable adapter profiles, a green offline gate) plus a fully worked recommendation
vertical that is generic across banking and online retail and the JP / AU / SG markets. You
fork it to serve your own customers, offers, eligibility rules and consent regimes, keeping,
replacing, or learning from the reference vertical.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical
rebrand** (one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the hexagon),
> [`SPEC.md`](../SPEC.md) (the domain contract), [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> (adding a port / sub-service), the [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The domain is split so the boundary is explicit:

| Layer | Where | For a new deployment |
|---|---|---|
| **Core** (vertical-neutral machinery) | the stable `domain/kernel.py` import surface, generic ports, serialization/audit primitives, DI wiring and eval scaffold | keep untouched |
| **Policy** (your numbers) | the `ranking:` block of `config/settings.yaml` (`propensity_weight`, `value_weight`, `min_score`) and the per-market residency / locale profiles | change by config, not code |
| **Vertical** (offers, customers, rules) | the domain models (`domain/models.py`), the deterministic engines' rule inputs, the prompts, the local seed (`adapters/local/_seed.py`), the eval golden set, the UI panels | rewrite for your catalog |

If your product is another per-customer recommendation surface (banking cross-sell, retail
affinity, telecom upsell, insurance next-best-offer), the core plus three deterministic engines
(candidate filtering, eligibility / suitability, ranking) transfer directly. Consent remains an
external legal decision behind `ConsentPort`; bind `marketing-compliance-gate` or the client's preference centre rather
than adding consent rows to the recommendation store.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): the generic `ports/`, the contract tests
  (`tests/contract/`), the eval harness mechanics (`eval/run_eval.py`), the hexagon wiring
  (`config.py`, `api/deps.py`), the shared-commons integrations (`hex-service-kit`,
  `agent-eval-kit`, `pii-kit`, `review-kit`, `consent-preference-kit`), and CI workflows.
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the local
  seed and any synthetic fixtures, `adapters/onprem/*`, UI theming / branding, the golden
  eval dataset, and `COMPLIANCE.md` jurisdiction rows.

Track upstream via git tags; rebase your adopter-owned
changes onto each release rather than merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name, the CLI entry point, the `MKT_` env
prefix, and the baked-in resource ids across the tree in one pass. Preview first, then
apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_nba --cli acme-nba \
    --env-prefix ACME --resource acme-next-best-action --dry-run

# Apply:
python scripts/rename_fork.py --package acme_nba --cli acme-nba \
    --env-prefix ACME --resource acme-next-best-action --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.14 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make gate
```

The distribution / repo name is the resource stem here, so `--dist` defaults to the
`--resource` value; pass it only if your repo folder differs from the resource id. Add `--include-docs` to sweep Markdown prose too. The script deliberately does
NOT touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region / residency and market.** The active `market` (`JP` / `AU` / `SG`) and
   `vertical` (`banking` / `online_retail`) are settings, and each market pins its own
   in-country residency region (JP to Tokyo, AU to Sydney, SG to Singapore), validated to
   fail fast. Set your market and confirm the Terraform `region` / tfvars match. See
   [`docs/runbook.md`](runbook.md).
2. **Identity / IdP.** Identity is server-verified and never asserted by the client. The
   profile picks the source: `local` seeded dev personas (offline only), `gcp` / `platform`
   verify the Cloud IAP assertion (`MKT_NBA_IAP_AUDIENCE`), `onprem` is a client-IdP
   placeholder. Wire your issuer(s) for the secure profiles. See
   [`docs/embedding-and-identity.md`](embedding-and-identity.md).
3. **PII / jurisdiction pack.** Set `pii.jurisdictions` (and `MKT_NBA_PII_JURISDICTIONS`
   for the eval gate) so redaction and the `pii_safety` metric detect YOUR national
   identifiers. The detectors come from the shared, versioned `pii-kit` package (SG / JP /
   AU home-market rows by default); add your jurisdiction there if it is not yet listed.
   An empty set, and any code the pack has no rows for, is refused at configuration load
   rather than silently reducing redaction to email and phone.
4. **Ranking and consent boundary.** Own the numbers under `ranking:` in
   `config/settings.yaml` (`propensity_weight`, `value_weight`, `min_score`). Set
   `MKT_CONSENT_STORE_URL` plus the reviewed `MKT_CONSENT_STORE_AUDIENCE` for `marketing-compliance-gate` Workload
   Identity, or implement the on-prem adapter
   against the client's preference centre. Only the exact canonical allow outcome may permit.
5. **Reference data is fictional.** Every seeded customer, offer, eligibility rule, consent
   record and propensity score (`adapters/local/_seed.py`, `tests/`, `eval/`) uses
   obviously-fake data. Replace the seed with your own synthetic catalog. **Do not run
   against live customer data without your own legal, security and model-risk sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/` and the rubrics for your catalog: a fork
   inherits a green gate that measures the WRONG thing until you do. The gate structure is
   generic; the golden cases are yours.
7. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root, `USER
   appuser`, healthcheck) and `infra/terraform/` (Org Policy, CMEK, VPC-SC, WORM logging)
   and the loopback-by-default binding before you expose anything.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it
*touches* are owned by sibling platform services, and you should integrate rather than
rebuild them (see [`docs/faq/features-faq.md`](faq/features-faq.md) for the full map): the
guardrail gateway (`agent-guardrail-gateway`), the governed knowledge base (`enterprise-knowledge-base`), the agent registry (`agent-registry`),
the AI-quality / eval gate (`model-quality-gate`), observability + WORM audit (`agent-observability`), the human-review and
maker-checker console (`human-review-console`), the marketing-compliance governor (`marketing-compliance-gate`), and the on-prem DLP
gate (`onprem-dlp`). The `platform` profile's adapters are already thin HTTP clients to those
services.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` green.
- [ ] Set market + Terraform tfvars to your in-country region.
- [ ] Wired your IdP / IAP audience for the secure profiles.
- [ ] Set `pii.jurisdictions` + added a pattern pack if needed; `pii_safety` exercises your ids.
- [ ] Owned the `ranking:` numbers and bound `marketing-compliance-gate` or the client's preference centre.
- [ ] Replaced the local seed and every synthetic fixture with your own catalog.
- [ ] Rebuilt the eval golden set + rubrics for your offers.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address).
- [ ] Decided which sibling platform services you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
