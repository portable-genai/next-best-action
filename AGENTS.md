# next-best-action

The shared working agreement is [`.github/AGENTS.md`](https://github.com/portable-genai/.github/blob/main/AGENTS.md).
It carries the architecture rules, the gate contract, the fleet invariants, the
falsification discipline, versions and house style, and it holds in every repository
here. Read it first. This file carries only what is specific to this one.

## What this is

Catalog id **Mkt5**. A multi-vertical next-best-action engine: candidate filtering, eligibility
and suitability, and ranking are deterministic unit-tested engines, and the model only explains
why an offer was recommended.

## Concrete bindings

| | |
|---|---|
| Catalog id | `Mkt5` |
| Package | `src/next_best_action/` |
| Profile variable | `MKT_NBA_PROFILE` |
| Adapter families | `gcp`, `local`, `onprem`, `platform` |
| Gate | `make gate` |

`config.py` holds the one resolution of that variable (`_PROFILE_ENV`) and every consumer keys
off what it publishes. An unset value is no choice: it binds the SDK-free adapters but grants
none of the `local` relaxations, so `adapters/local/identity.py` refuses to seed a dev persona
until the profile was named deliberately.

Marketing consent is a cited decision obtained through Mkt6's `consent-preference-kit` client
contract (`ports/consent.py`), never a second consent store in this repository.

## What this repository still owes

The `Capability gaps` cell on this repository's row in the maintainer's system tracker is the
authoritative list. Its verdict against the shared checks, including the ones it does not pass,
is in [`docs/practices-audit.md`](docs/practices-audit.md).
