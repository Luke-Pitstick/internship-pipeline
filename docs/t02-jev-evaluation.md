# T02 — Jev eligibility and scoring evaluation

Measured October 6, 2026 using pinned `jev-1.13.0`, Python 3.12.7 on macOS 26.6.2 arm64. T02's bounded experiment is complete; **automatic rejection is not validated**. Use model judgments for inspectable review and exploratory ranking, keeping rejection reversible. No production matching behavior was changed.

## Reproduction and artifacts

`evaluation/jev/evaluator.py` uses existing httpx/Pydantic dependencies; no SDK or new package is required. `cases.json` contains 8 tuning and 34 frozen evaluation cases, synthetic candidate facts, criterion labels, and ordinal relevance judgments. `rubric.json` records outcomes, dimensions, weights, policy and release thresholds. Reports retain typed distributions, evidence IDs, exact comparisons, model/rubric/profile/job revisions, latency and token usage. No credential or private candidate data is included.

Offline verification:

```sh
rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_jev_evaluation.py
rtk proxy .venv/bin/ruff check evaluation/jev/evaluator.py tests/test_jev_evaluation.py
```

For a new explicitly budgeted live experiment, choose a fresh output directory and a separately reviewed corpus. The runtime reads only `JEV_API_KEY` directly from the environment or ignored root `.env`; never source/print that file. A directory shares a persistent **60-attempt / 1,000,000 reserved-token cap** across invocations. Failed attempts count, and responses are not retried automatically. Existing report paths cannot be overwritten. The October 6 completion audit added a guard that rejects held-out evaluation when any actual model request duplicates a tuning input, before loading credentials or writing a ledger. The historical default corpus intentionally fails that guard; its original data and reports remain unchanged. Pass a new corpus with `--cases` for future evaluation; merely dropping the six duplicates does not make this already-inspected dataset fresh or human-adjudicated. Example commands for a reviewed new corpus (not authorization to run them):

```sh
rtk proxy .venv/bin/python evaluation/jev/evaluator.py --split tuning --limit 1 --max-requests 1 --max-tokens 20000 --output /tmp/jev-t02-new/smoke.json
rtk proxy .venv/bin/python evaluation/jev/evaluator.py --cases /path/to/reviewed-new-cases.json --split tuning --max-requests 8 --max-tokens 150000 --output /tmp/jev-t02-new/tuning.json
rtk proxy .venv/bin/python evaluation/jev/evaluator.py --cases /path/to/reviewed-new-cases.json --split heldout --max-requests 34 --max-tokens 600000 --output /tmp/jev-t02-new/heldout.json
```

Original outputs are in `evaluation/jev/reports/`: `smoke.json`, `tuning-partial.json`, `contract-diagnostic.json`, `tuning.json`, `heldout.json`, `summary.json`, and `usage-ledger.json`. The summary pins hashes of the fixture and rubric. The first two discarded typed responses failed over-strict validation of rounded probabilities; before the evaluation run, validation was corrected for observed two-decimal probabilities (sum tolerance 0.021, score-mean tolerance 0.041). Neither rubric nor thresholds changed. One sandbox transport attempt did not reach the API. The ledger records 50 paid attempts, 835,604 reserved tokens, and **140,930 known input / 27,026 known output tokens**. Two early discarded responses have unknown exact usage, so those totals are lower bounds, not a complete billing total. No further live requests followed the held-out run.

Verification passed: **167 tests** (18 evaluator safety/regression tests plus 149 existing matching tests), focused Ruff, and `git diff --check`. The existing matching import requires `PYTHONPATH=src` in this checkout.

Completion-audit follow-up: **21 evaluator tests passed**, including three new tests for the six historical overlaps, metadata/exact-check differences that do not change actual model inputs, and rejection before secret access/report creation even when a request limit selects only one case. Focused Ruff passed. No paid request was made for this fix. T06 owns the successor production matching regressions; the former `tests/test_matching.py` is no longer the evaluator's reproduction command.

The independent [split-integrity follow-up](t02-followup.md) reproduces the actual request duplicates and historical unseen-subset metrics, extends offline preflight coverage, and records the exact untouched human-adjudicated T21 gate. It closes the bounded engineering assignment; it supplies no new quality or automatic-rejection validation.

## Results and independence

| Measure | Frozen evaluation split | Unseen model inputs only |
| --- | ---: | ---: |
| Cases | 34 | 28 |
| Eligible cases | 15 | 13 |
| False rejection among eligible | 0/15 (0%) | 0/13 (0%) |
| Experimental rejection precision | 4/4 (100%) | 2/2 (100%) |
| Experimental review rate | 23/34 (67.6%) | 21/28 (75%) |
| Expected-review recall | 7/7 (100%) | 5/5 (100%) |
| Criterion agreement | 151/170 (88.8%) | 121/140 (86.4%) |
| Correct ordinal ranking pairs | 6/6 (100%) | 3/3 (100%) |
| Median / maximum latency | 132.85 / 261.04 ms | 128.32 / 261.04 ms |
| Input / output tokens | 100,156 / 19,158 | 82,384 / 15,780 |

All cases and labels were authored before live calls; tuning and evaluation IDs are separate. The overlap audit found six evaluation cases reuse a tuning model input verbatim: required-Rust unknown, graduation boundary/conflict/outside, years comparison, and strong ranking baseline. Exact-check variants differ in code inputs, but their Jev state is shared. The second column excludes those six and is the relevant estimate for previously unseen model inputs. Full results remain available for arithmetic/regression checks. Neither subset is a representative, independently human-adjudicated sample; the author supplied synthetic ground truth. No held-out result was used to tune this version.

Zero observed errors in 13 unseen eligible examples still gives a one-sided 95% false-rejection upper bound of **20.6%** under an IID binomial assumption. Shared synthetic scaffolding makes even that assumption optimistic. Ranking pairs are dependent comparisons within one four-job group (only three pairs survive the overlap audit), not six independent user queries.

## Rubric and policy

Five atomic Choice criteria cover role/internship, authorization, education, location, and required skills. Every criterion uses `satisfied`, `violated`, `not_stated`, or `ambiguous`, and an independent closed-set evidence-ID Choice; code resolves IDs to the synthetic original text. Four Score dimensions cover skill overlap, project relevance, duties and career preferences, weighted 35/30/25/10%. Code normalizes each 0–3 score to 0–100 and combines weights. A fit score describes rubric position, not interview probability; score distributions/confidence remain separate from eligibility.

Experimental rejection requires violation probability ≥0.95, confidence ≥0.80 and a non-`none` evidence-ID probability ≥0.95, or an explicit exact-check violation. Missing/ambiguous evidence and low certainty route to review. A high fit never overrides a mandatory violation. **Release policy maps every experimental rejection to review** while the gate is unmet. Selecting an evidence ID is not proof that its excerpt logically supports the answer; the report makes the excerpt inspectable but does not claim validated explanations.

Exact graduation bounds and experience comparisons use Python dates/numbers over manually validated synthetic fixture fields. Equal boundaries pass, outside values fail, and conflicting values route to review. This tests arithmetic policy, not production extraction accuracy. Posting salary arithmetic is not evaluated here. Candidate unknowns remain explicit, and missing preferred skills cannot be a mandatory violation in the rubric.

The gate is frozen: at least 300 independently labeled eligible examples with zero false rejection (a zero-error 95% upper bound below 1%), at least 30 rejection examples and ≥98% precision, ≥95% expected-review recall, and at least 20 ranking comparisons with ≥80% agreement. Require representative human adjudication, including each troublesome criterion and hostile text. The present run fails sample-size and provenance requirements. The 0.95/0.80/0.95 action thresholds are conservative experiment settings, **not empirically calibrated safe defaults**. Increasing automation coverage should use new tuning cases followed by a new untouched evaluation set.

## Failure analysis and next release decision

The project-management internship was classified as an allowed role with confidence 0.95 despite explicit disallowance. The student-developer role was `not_stated` rather than violated. A master's-only posting incorrectly yielded a required-skills violation; sponsorship and location requirements also contaminated unrelated skill decisions. An unspecified remote jurisdiction was treated as satisfied with confidence 0.67, which policy correctly routed to review. High confidence does not establish correctness, and evidence gating often reduced unsafe actions at the cost of substantial review.

The hostile eligible case passed, and hostile ineligible/senior cases stayed reviewable; this small adversarial set does not prove injection resistance. Required Java/Rust, preferred graduate degrees, compound negation, conflicting education, sponsorship missing/unknown, title cohorts, location restrictions, and all ten existing role regressions are covered. Fit ordering separated the strong backend/data role from medium data, weak product and unrelated finance examples, but real candidate diversity and multiple ranking groups remain untested.

For T06, retain these inspectable raw decisions and reuse the regression corpus, while keeping automatic rejection disabled. A future tuning version should narrow criterion context to reduce cross-criterion leakage and add targeted role tests, then pass a new representative held-out gate before changing policy. Changes based on these results must not claim this set as independent validation again.

## Official API contract checked

Context7 was unavailable; official docs were checked directly. The evaluator sends shared state and typed Choice/Score questions to the bearer-authenticated [HTTP evaluation endpoint](https://docs.typesafe.ai/api), stores returned model identity and usage, and pins the evaluated version from [models](https://docs.typesafe.ai/models). Questions are independent; downstream policy runs in Python. [Score](https://docs.typesafe.ai/primitives/score) is a distribution-weighted rubric position. [Confidence](https://docs.typesafe.ai/confidence) describes distribution certainty, while [Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) motivate separate exact comparisons and hostile-input tests. Jev does not generate explanation or résumé prose.
