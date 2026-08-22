# Adoption FAQ

For an engineering lead forking this repo as their institution's base. The step-by-step is
[`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my institution?

`scripts/rename_fork.py` rewrites the package name, the CLI entry point, the `MKT_` env
prefix, and the resource ids in one pass (preview with `--dry-run`, apply with `--yes`). Then
recreate the venv, `pip install -e ".[dev]"`, and run `make gate`. The script does the
mechanical rename; the human decisions (market / region, IdP, PII pack, ranking / consent
policy, seed data, eval golden set) are the checklist in `ADOPTING.md`. The distribution name
is the resource stem here, so `--dist` defaults to the `--resource` value.

### If several institutions fork this, how does each take upstream fixes?

Track upstream via **git tags** (semver). The repo declares a **core-vs-adopter-owned boundary** (ADOPTING section 2): upstream
owns the generic `ports/`, `tests/contract/`, the eval harness mechanics, the hexagon wiring
(`config.py`, `api/deps.py`) and the shared-commons integrations; you own `config/settings.yaml`
values, the seed, `adapters/onprem/*`, UI theming, and the eval golden set. Rebase your
adopter-owned changes onto each release rather than merging `main` continuously, and merge
conflicts stay in files you were told to expect.

### How do I add a new outbound dependency (a new port)?

The contract test fails loudly if the port map drifts
(`test_port_protocols_matches_settings_adapters` fails on **both** directions: a binding added
to `settings.adapters` but missing from `PORT_PROTOCOLS`, and vice-versa). The touch list:
define the `@runtime_checkable` Protocol under `ports/`, re-export it from `ports/__init__.py`,
implement one adapter per profile (at least `local` and `onprem`), bind all of them in
`config/settings.yaml`, add the port to the parity test's map, add a `cached_property` on the
`Container`, and wire it in `api/deps.py`. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md); note
that CONTRIBUTING does not yet enumerate the full touch list exhaustively (audit check G6,
PARTIAL), so use this list plus the parity test as the backstop.

### How do I add a new deterministic engine or output panel?

An engine is pure domain: add `domain/<name>_service.py` (stdlib only), thread any bank-owned
constants through the `ranking:` config (never hard-code them), construct it in `api/deps.py`,
and unit-test it the way `test_ranking_service.py` does. For an
output panel, the renderer (`scripts/render_recommendation_ui.py`) renders the attached
recommendation artifacts; add your panel there so the demo can target it.

### How do I change the taxonomy (offer kinds, channels, consent states)?

The vocabularies are `StrEnum`s (all thirteen, from the shared `hex-service-kit` base) and the
engines are typed on `str`, so members ARE their wire values and you extend the vocabulary
without editing engine code. Serialized JSON values are the enum strings. To replace a taxonomy
wholesale for a different vertical, edit the enums in `domain/models.py` and the seed.

### How do I retune ranking and bind my consent system without touching core logic?

Ranking weights live under `ranking:` in `config/settings.yaml` and are threaded into
`RankingService`; `tests/unit/test_ranking_service.py` shows the overrides. Consent is not a
tunable local policy. Set `MKT_CONSENT_STORE_URL` and `MKT_CONSENT_STORE_AUDIENCE` for managed
Workload Identity (or the kit's `CONSENT_S2S_*` credentials outside GCP),
or implement the on-prem `ConsentPort` against the client's preference centre. Every adapter
must preserve the rule that only an explicit canonical `allowed` outcome permits an offer.

### Will the demo rot after I diverge?

It is guarded, and the guard is inside the gate (audit check F2, PASS). The renderer and the
demo server emit stable `data-*` evidence hooks for every load-bearing figure.
`make demo-selftest`, which `make gate` runs, produces all six live recommendation sets and then
starts the REAL presenter server on an ephemeral port, fetches the artifact index and every
artifact page over HTTP, and compares each hook in the served bytes against the value the running
app just computed, so a refactor that breaks a page or quietly stops recomputing a figure fails
the gate rather than surfacing in front of an audience. `make demo-browser` adds the last layer:
headless Chromium loads the same served pages, follows the index's own links and reads the
figures out of the live DOM. Playwright is pinned in the `[demo]` extra rather than `[dev]`,
because the browser binary is a network download and the day-one offline install must not need
one; that stage skips itself when the extra is absent. Both stages have been proven able to go
RED against a planted stale figure and a stripped panel hook. If you diverge, keep the hooks:
they are the contract every stage reads.

### Does the CI run for my fork out of the box?

Yes. CI and the eval gate run on the `local` profile with **no cloud credentials and no org
secrets** (`MKT_NBA_PROFILE: local`, `permissions: contents: read`, install `-e ".[dev]"`
only), so a fork's build is green immediately. You add secrets only when you wire the `gcp` /
`platform` profiles. Note the eval gate measures the *reference* catalog until you rebuild the
golden set; that is an explicit adoption step, not a silent pass.
