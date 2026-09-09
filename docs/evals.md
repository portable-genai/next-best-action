# Evals

How this repository knows when its recommendations are wrong, and what it still cannot tell
you. Written for a reviewer deciding whether the offline gate is worth anything, not for
someone who already believes it is.

The short version: the gate scores seven metrics over eight golden cases, every bar sits at
1.0, every metric is shown failing on a planted defect before a single golden score is
trusted, and two of the seven exist because the other five all read the answer the service
returned and none of them could see the answer getting shorter.

## What the gate is for

A next-best-action engine decides which offer a customer is shown, in what order, on which
channel. Three of those are consequential and one is regulated. The offline gate is the
pre-merge check on the deterministic half: candidate filtering, eligibility, consent,
ranking, redaction. It is not a model evaluation, and it is not a substitute for the
promotion gate, which runs against `model-quality-gate` under the platform profile and is the
only thing here allowed to say a build may be promoted.

## What is measured, and against what bar

Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the
runner reads it from there. There is no dict of thresholds in the runner any more: a
metric scored with no reviewed bar fails the build, and so does a bar that names no
metric, which is the direction that rots quietly because it rots toward looking well
governed.

The third column is the denominator, MEASURED on a real run rather than assumed to be
the case count. It is the case count for five of these metrics and is not for the two
ranking ones, which score a decision per adjacent pair and per catalogue offer. The
rule it answers: a bar `t` tolerates a single miss only over at least `1/(1-t)` scored
decisions, so a bar below 1.0 on a short corpus is 1.0 wearing a friendlier number. The
bracket says what the loosest non-vacuous bar over that many decisions would be. Every
bar here is 1.0, and the rubric beside each one says whether that is the corpus being
short or the failure being intolerable.

| Metric | Bar | Decisions scored | What it measures |
|---|---|---|---|
| `citation_accuracy` | 1 | 8 (the loosest bar that tolerates one miss is 0.88) | Fraction of cited source ids that appear in the result's own derived evidence set (no fabricated citations). Binary per case over 8 cases, where the previous 0.90 was already 8-of-8 arithmetic. |
| `eligibility_accuracy` | 1 | 8 (the loosest bar that tolerates one miss is 0.88) | Fraction of golden cases where the deterministic eligibility + consent gate held (no ineligible / consent-suppressed recommendation) and the top recommendation matched the expected offer. Scored once per case; 8 cases. |
| `pii_safety` | 1 | 8 (the loosest bar that tolerates one miss is 0.88) | No unredacted customer PII (SG NRIC, JP My Number, AU TFN, email, phone) survives into the produced recommendation text or the audit records. Detected with the SAME jurisdiction pattern source the runtime redactor uses, so a single leak means the redact-before-audit boundary was bypassed. Binary per case over 8 cases: 0.99 and 1.0 were already the same bar, and 1.0 does not invite a reader to think one leak is priced in. |
| `ranking_completeness` | 1 | 25 (the loosest bar that tolerates one miss is 0.96) | Share of the shipped catalog's in-scope offers whose disposition matches what the book requires: recommended or explicitly suppressed when the customer could see it, absent from all three lists when the book removes it. |
| `ranking_order` | 1 | 9 (the loosest bar that tolerates one miss is 0.89) | Share of adjacent recommendation pairs, among those the shipped book's propensity and value both order the same way, that the engine ranked in that order. Silent on pairs where the two inputs disagree. |
| `recommendation_groundedness` | 1 | 8 (the loosest bar that tolerates one miss is 0.88) | Fraction of results whose every recommendation carries at least one citation. A recommendation built on uncited evidence fails. Binary per case; 8 cases. |
| `review_safety` | 1 | 8 (the loosest bar that tolerates one miss is 0.88) | Fraction of results that correctly set requires_human_review=True (maker-checker). Binary per case over 8 cases, where 0.99 was already 8-of-8; a recommendation set that lost the human gate is a defect and not a rounding loss. |

Scored over 8 golden cases, dataset digest `af656abd41f3`, by `offline heuristic (no GCP creds)`.

## What is exercised

- **8 golden cases** in `eval/datasets/golden_recommendations.jsonl`,
  8 of them carrying an expected top offer. The INPUTS are the shipped demo
  book, so the customers the gate measures are the customers the demo shows. The
  EXPECTATIONS are hand-written, and each was checked against the book's own dominance
  rule before being written down: an oracle read off the thing under test agrees with
  it by construction and measures nothing.
- **19 active offers** across 6 market/vertical scopes, with
  8 customers and 25 propensity signals, in
  `src/next_best_action/data/demo_book/`. Every scope ships at least three offers,
  asserted in `tests/contract/test_demo_book.py`. That is not decoration: with one or
  two candidates per customer, most golden cases returned a list of one, and a list of
  one makes no ordering claim at all.
- **The falsification proofs run first.** `eval/run_eval.py` calls
  `prove_before_scoring` as the opening statement of the scored run, so every metric is
  shown going red on its own planted defect in the same process, against the same
  thresholds, before any golden score is trusted. `tests/unit/test_not_falsely_green.py`
  runs the same proof objects and adds the one thing a proof cannot say about itself:
  that there is one for every metric the gate scores.

## The two metrics that were missing, and what they were missing

`eligibility_accuracy` reads `result.top` and the gate flags. Everything below rank one was
unscored, which meant a service that returned the right first offer and then anything at all,
in any order, scored a perfect 1.000 on every metric this repository had. A customer sees the
list. Rank two is the offer a relationship manager reaches for when the first is declined.

**`ranking_order`** scores the order, against the shipped demo book rather than against the
engine. Specifically against dominance in the book: where an offer has both a higher
published propensity and a higher published base value than the one below it, every weighting
with non-negative weights ranks it higher, so the book settles that pair without reference to
the tuning. Two things this deliberately is not:

- not the engine's combined score, which is in its own order by construction;
- not the published propensity order either. The ranking is `0.6*propensity + 0.4*value`, and
  the two inputs genuinely disagree on 4 of the 13 adjacent pairs in this corpus:
  `au-retail-bnpl` carries the higher propensity and the lower value, and the weights decide
  it. That is a business decision, not a correctness claim, so the metric scores nothing at
  all on those pairs rather than scoring a guess.

**`ranking_completeness`** scores the catalogue, not the answer. It is the only metric here
that reads the offers which are NOT in the result, and that is the point: an offer that
quietly stops being a candidate takes its own evidence with it, so groundedness, citation
accuracy, ranking order and eligibility accuracy all still read 1.000 over the shorter list.
Every active book offer in the case's market and vertical must appear exactly once across
recommendations, `suppressed` and `consent_suppressed`, unless the book itself removes it
(already held, conflicting with a holding, out of stock), in which case it must appear in
none of them.

## Two defects this work found

**The gate was scoring a cached copy of a book it did not ship.** `LocalSettings.book_path`
defaulted to `~/.next_best_action/book.duckdb`, and the shared store seeds a file once and
then leaves it alone, which is right for rows an audience writes during a demo and wrong for
the shipped tables. On any machine that had run the demo before, the eval, the console and
`scripts/demo.py` served whatever book that machine cached the first time, while a fresh
checkout in CI served the repository. The disagreement was invisible and it favoured the
laptop doing the demo. Fixed two ways: the eval now runs the store in memory, so a scored run
reads the book by construction, and `LocalRecommendationAdapter` re-seeds a file store whose
manifest version or row counts no longer match what the build ships.

**The corpus could not express what the bars claimed.** Five of the six original golden cases
returned one or two offers, so there was almost no rank two to check, and every bar below 1.0
was 1.0 in disguise: binary scoring over 6 cases means 0.90 needs 6 of 6, because 5/6 is
0.833. Rather than restate the same bars at 1.0 over a corpus that could not support anything
else, the book grew: five offers and two customers, chosen so every market/vertical scope
ships at least three active offers and two personas reach the whole scope. The bars are 1.0
now because the failures are intolerable, and the rubrics say which of the two reasons
applies to each.

One label moved as a result. `au-banking` expected `au-bank-offset` and now expects
`au-bank-term-deposit`, because the book gained a third AU banking offer that dominates the
offset on both inputs (propensity 0.4833 against 0.4733, value 200 against 140). The label
follows the book's own dominance rule, not the engine's output.

## What this gate does not measure

Named here and printed by the demo, because an audience shown a table of green numbers will
otherwise assume the list is empty.

- **Whether an offer should exist for a customer at all.** `ranking_completeness` checks the
  catalogue is fully accounted for. It cannot check the catalogue is the right one.
- **The ranking weights.** Four of the thirteen adjacent pairs have propensity and value
  disagreeing; the book cannot decide those, so `ranking_order` stays silent and `0.6/0.4`
  goes unexamined here.
- **Whether the propensity model is any good.** The scores are read from the book, the book's
  formula is recorded in `scripts/render_demo_book.py` and is fictional, and a real deployment
  gates its model separately.
- **The explanation text.** It is generated after the ranking is fixed, and nothing here reads
  it except for citations and PII.
- **Anything that needs the deployment.** Live model calls, hosted identity, managed
  durability, CMEK/VPC-SC enforcement. The promotion gate covers what it covers; this page
  makes no claim about any of it.

## Running it

```
make eval          # render-check the book, then the scored run
make gate          # the whole pre-merge gate, eval included
make evals-doc     # regenerate the derived sections of this page
```

The demo runs the same scorers live as its closing act, shows each one going red on its own
defect, and prints the list above. `scripts/demo_selftest.py` fails the build if a metric is
put on that slide without being shown failing.
