# The demo book

Fictional customers, the offers they could be recommended, the per-market eligibility rules,
and one propensity score per customer and offer. Every id is visibly invented and no row
describes a real person, institution or product.

One file per table, newline-delimited JSON, keys in the column order the BigQuery schema in
`infra/terraform/bigquery.tf` declares. The same rows feed three consumers, which is why they
live here rather than in code:

| Consumer | How it reads the files |
|---|---|
| The `local` profile | `adapters/local/recommendation.py` opens a DuckDB file holding the same four tables and, when they are empty, inserts these rows |
| The deployment | `scripts/load_demo_book.py` streams them into the `mkt_nba` dataset, rewriting `tenant` to whatever the deployment's identity adapter resolves |
| Tests and the eval gate | `next_best_action.demo_book` builds the domain objects, and `adapters/local/_seed.py` derives its long-standing names from the same rows |

| File | Rows | What a row is |
|---|---|---|
| `customers.ndjson` | 6 | one customer, their attributes, holdings and category affinities, and the tenant that owns them |
| `offers.ndjson` | 14 | one offer: kind, category, business value, the consent channel it needs, and what excludes it |
| `eligibility_rules.ndjson` | 12 | one per-market, per-vertical rule the deterministic engine evaluates |
| `propensity_signals.ndjson` | 14 | one model score for one customer and offer |
| `book_manifest.ndjson` | 1 | the book's version and `fictional: true`, which is what the loader's overwrite guard reads |

**Propensity is stored rather than computed, and that was a change.** The local adapter used
to derive a score at request time while the managed adapter read rows and refused any offer
with no signal, so the two profiles disagreed about what a propensity is and the laptop could
rank an offer the deployment would refuse. In production a model writes these rows. The
scores here are exactly what the old formula produced, which is recorded in
`scripts/render_demo_book.py`, and `model_version` says which model produced them.

**Consent is deliberately absent.** It belongs to `marketing-compliance-gate` and is read
from that service. A copy here would give the ranking engine a second, private answer to a
question another system owns.

Edit these files by hand. `tests/contract/test_demo_book.py` refuses a signal for an unknown
offer, a customer holding an offer that is not in the catalog, and any candidate offer left
without a signal, which is the case the managed adapter refuses outright.
