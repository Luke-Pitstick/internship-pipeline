# T02 follow-up — evaluation split integrity

October 6, 2026. **Complete engineering verification; T21 human-adjudicated acceptance remains external and unmet.** The existing overlap guard needs no implementation repair: it serializes the complete `request_body` with sorted dictionary keys and checks the entire provided corpus before selection/truncation, credential access, HTTP-client construction, output creation, or usage-ledger writes. No evaluator policy, rubric, threshold, historical fixture, or report was changed. All verification was offline; no environment file, real credential, private candidate data, or provider was accessed.

## Independently reproduced historical evidence

Complete serialized request bytes (`model`, `state`, and `questions`, with sorted dictionary keys) establish the following matches. Case IDs only identify the matches after comparison; they do not establish independence.

| Historical evaluation case | Tuning cases with identical request bodies |
| --- | --- |
| `h-required-rust-unknown` | `t08-required-missing` |
| `h-date-boundary` | `t01-baseline`, `t07-conflicting-dates` |
| `h-date-conflict` | `t01-baseline`, `t07-conflicting-dates` |
| `h-date-outside` | `t01-baseline`, `t07-conflicting-dates` |
| `h-years-exact` | `t01-baseline`, `t07-conflicting-dates` |
| `h-rank-strong` | `t01-baseline`, `t07-conflicting-dates` |

There are six contaminated held-out cases, even though some match two tuning cases. Removing these six from the saved 34-row report gives 28 previously unseen requests: 13 eligible cases, zero false rejections, two experimental rejections with 100% precision, five expected-review cases with 100% recall, 121/140 criterion agreement, and three ranking comparisons with 100% agreement. Saved usage is 82,384 input and 15,780 output tokens. This recomputation uses historical rows, not a new evaluation call or new labels.

The default corpus remains immutable and deliberately fails held-out preflight. Its candidate facts and labels are synthetic and its examples/results have already been inspected. Removing duplicates, changing labels or IDs, or rerunning the 28-request subset cannot establish fresh independent human-adjudicated evidence. All inspected examples are now regression data.

## Offline acceptance

Targeted tests independently compare serialized request bodies; reproduce the six overlaps and saved 28-row metrics; change IDs, labels, exact-comparison metadata, expected outcomes and ranking metadata; and reverse case, posting, candidate and nested fact dictionary order. None of those changes defeats the guard.

A temporary synthetic corpus places a genuine duplicate after an independent first held-out case and runs with `limit=1` and `max_requests=1`. It fails before the replaced credential function is invoked, before an HTTP client is constructed, and before the output directory or ledger can exist. The same corpus without the duplicate passes corpus and request-count checks and reaches a sentinel at the credential boundary; the sentinel stops execution without loading credentials or making a call. This proves acceptance of disjoint inputs by offline preflight, not successful live evaluation.

The guard detects identical current request bodies within the supplied corpus. It does not certify semantic independence, prevent reuse of an already-inspected corpus under changed content, or compare against tuning inputs omitted from a replacement file. T21 must freeze and provide the complete tuning/evaluation manifest and review related-example grouping as well as request fingerprints.

## Untouched T21 gate

Before evaluating an automatic-rejection proposal, obtain a fresh representative dataset with independent human adjudication. Record a versioned manifest with dataset provenance, selection/sampling method, source and collection dates, applicable synthetic/consented candidate-fact provenance, inclusion/exclusion decisions, adjudicator identity or role, adjudication date, disagreement resolution, and a hash of the frozen cases and labels. Keep actual candidate inputs in ignored/private storage and use synthetic facts in committed fixtures. Source publication timestamps, first observation and notification timestamps remain distinct where present.

Humans must label eligibility and every applicable mandatory criterion, expected-review/unknown/conflicting cases, supporting source evidence, exact numeric/date comparisons, and ordinal ranking preferences using supported candidate facts. They must adjudicate independently of model predictions; unresolved evidence belongs in review. Cover role boundaries, authorization/sponsorship, education, location, required versus preferred skills, unknown candidate facts, exact-boundary/conflicting requirements, and hostile posting text across representative candidates and postings. Include multiple ranking groups and document dependent comparisons. No human labels were supplied or invented by this follow-up.

Freeze tuning and evaluation membership before tuning, group related postings/candidate variants to avoid leakage, and keep the evaluation examples and labels untouched by tuning decisions. Freeze the model/version, rubric/instructions, weights, exact-check extraction and decision policy, dataset hashes, and metric definitions before evaluation. Preserve the full tuning manifest in `--cases` so the guard can inspect it before any request limit. Record any intentionally repeated tuning calls as tuning/regression evidence. If evaluation results motivate changes, that set becomes regression data and a subsequent acceptance attempt needs a new untouched set. Budget and authorize paid requests separately; this follow-up authorizes none.

The existing `rubric.json` release gate is unchanged:

| Requirement | Frozen threshold |
| --- | ---: |
| Independently labeled eligible examples | At least 300 |
| Observed false rejections | 0 |
| Experimental rejection examples | At least 30 |
| Experimental rejection precision | At least 98% |
| Expected-review recall | At least 95% |
| Ranking comparisons | At least 20 |
| Ranking agreement | At least 80% |
| Representative independent human adjudication | Required |

No separate numeric minimum for expected-review examples is specified by the existing gate; their coverage and provenance still require adjudication. Missing recall is not a passing metric. The 300 eligible/zero-error requirement corresponds to a one-sided 95% binomial upper bound below 1% under the stated sampling assumption. The existing experimental action thresholds also remain unchanged: violation probability at least 0.95, confidence at least 0.80, evidence probability at least 0.95, or a validated exact-check violation.

`release_gate()` intentionally retains the independent-human-adjudication failure even if numerical metrics pass, and reports always record `release_gate_passed: false`. The evaluator does not implement human-provenance attestation or enable automatic rejection. T21 must supply and independently review the dataset/adjudication evidence and separately authorize any policy change; until then, experimental rejections remain reviewable. A release may retain that limitation without claiming this gate passed.

## Verification and preservation

Commands:

```sh
rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_jev_evaluation.py
rtk proxy .venv/bin/ruff check evaluation/jev/evaluator.py tests/test_jev_evaluation.py
rtk git diff --check
```

Results: **24 evaluator tests passed**; focused Ruff and `git diff --check` passed. The fixture and all seven historical report files were hashed before and after verification to confirm unchanged bytes. The fixture SHA-256 is `bdeac12aa2d62dc3502e97ea147aec7d5941b4b6a70bf1cccdfe4bc3cd32f375`; the held-out report SHA-256 is `08b59f96c44daedfb64676eaa314b14dbfaa02d0d459faf0d667025472791bba`.
