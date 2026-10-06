"""Offline safety/regression checks for the isolated synthetic experiment."""

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

MODULE = Path(__file__).resolve().parents[1] / "evaluation/jev/evaluator.py"
spec = importlib.util.spec_from_file_location("jev_evaluator", MODULE)
assert spec and spec.loader
jev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = jev
spec.loader.exec_module(jev)
CASES = json.loads((MODULE.parent / "cases.json").read_text())


def response_for(case, overrides=None):
    answers = {}
    for criterion in jev.RUBRIC["criteria"]:
        choice = (overrides or {}).get(criterion, "satisfied")
        answers[criterion] = {
            "type": "choice",
            "choice": choice,
            "confidence": 1,
            "probabilities": {k: float(k == choice) for k in jev.RUBRIC["outcomes"]},
        }
        answers[criterion + "_evidence"] = {
            "type": "choice",
            "choice": "j1",
            "confidence": 1,
            "probabilities": {k: float(k == "j1") for k in ["none", *case["posting"]]},
        }
    for dimension in jev.RUBRIC["dimensions"]:
        answers[dimension] = {
            "type": "score",
            "score": 3,
            "confidence": 1,
            "probabilities": {str(k): float(k == 3) for k in range(4)},
        }
    return jev.Response(
        model="jev-1.13.0", answers=answers, usage={"input_tokens": 100, "output_tokens": 50}
    )


def test_splits_are_distinct_and_cover_required_regressions():
    tuning = {c["id"] for c in CASES if c["split"] == "tuning"}
    heldout = {c["id"] for c in CASES if c["split"] == "heldout"}
    assert len(tuning) == 8 and len(heldout) == 34 and not tuning & heldout
    assert len({json.dumps(c["posting"], sort_keys=True) for c in CASES}) >= 30
    assert all(c["candidate"]["id"] == "synthetic-candidate-v1" for c in CASES)
    assert any("hostile" in c["id"] for c in CASES)
    assert all(c["label"] in {"eligible", "ineligible", "review"} for c in CASES)


def test_historical_overlap_is_detected_without_rewriting_evidence():
    # Compare complete serialized request bodies independently of the guard and IDs.
    bodies = {
        case["id"]: json.dumps(
            jev.request_body(case, "jev-1.13.0"), sort_keys=True, separators=(",", ":")
        ).encode()
        for case in CASES
    }
    duplicates = {
        heldout["id"]: {
            tuning["id"]
            for tuning in CASES
            if tuning["split"] == "tuning" and bodies[tuning["id"]] == bodies[heldout["id"]]
        }
        for heldout in CASES
        if heldout["split"] == "heldout"
    }
    duplicates = {case_id: tuning_ids for case_id, tuning_ids in duplicates.items() if tuning_ids}
    assert duplicates == {
        "h-required-rust-unknown": {"t08-required-missing"},
        **{
            case_id: {"t01-baseline", "t07-conflicting-dates"}
            for case_id in (
                "h-date-boundary",
                "h-date-conflict",
                "h-date-outside",
                "h-years-exact",
                "h-rank-strong",
            )
        },
    }
    overlaps = jev.overlapping_model_inputs(CASES, "jev-1.13.0")
    assert set(overlaps) == set(duplicates)
    independent = [case for case in CASES if case["id"] not in overlaps]
    assert sum(case["split"] == "heldout" for case in independent) == 28
    assert jev.overlapping_model_inputs(independent, "jev-1.13.0") == []


def test_unseen_historical_metrics_are_reproducible_from_saved_rows():
    tuning_bodies = {
        json.dumps(jev.request_body(case, "jev-1.13.0"), sort_keys=True)
        for case in CASES
        if case["split"] == "tuning"
    }
    unseen_ids = {
        case["id"]
        for case in CASES
        if case["split"] == "heldout"
        and json.dumps(jev.request_body(case, "jev-1.13.0"), sort_keys=True) not in tuning_bodies
    }
    report = json.loads((MODULE.parent / "reports/heldout.json").read_text())
    metrics = jev.summarize([row for row in report["rows"] if row["case_id"] in unseen_ids])
    assert metrics["n"] == 28
    assert metrics["eligible_n"] == 13
    assert metrics["false_rejection_count"] == 0
    assert metrics["rejected_n"] == 2
    assert metrics["expected_review_n"] == 5
    assert metrics["expected_review_recall"] == 1
    assert metrics["ranking_pair_n"] == 3
    assert metrics["criterion_accuracy"] == pytest.approx(121 / 140)
    assert (metrics["input_tokens"], metrics["output_tokens"]) == (82384, 15780)


def test_different_labels_and_exact_checks_do_not_make_model_inputs_independent():
    tuning = copy.deepcopy(CASES[0])
    tuning["split"] = "tuning"
    heldout = copy.deepcopy(tuning)
    heldout.update(id="new-id", split="heldout", label="review", exact={"changed": True})
    heldout.update(expected={"role": "violated"}, ranking_group="changed", relevance=0)
    heldout["candidate"] = dict(reversed(list(heldout["candidate"].items())))
    heldout["candidate"]["facts"] = dict(reversed(list(heldout["candidate"]["facts"].items())))
    heldout["posting"] = dict(reversed(list(heldout["posting"].items())))
    heldout = dict(reversed(list(heldout.items())))
    assert jev.overlapping_model_inputs([tuning, heldout], "jev-1.13.0") == ["new-id"]


def test_overlap_blocks_before_secret_access_or_report_creation(monkeypatch, tmp_path):
    def secret_access():
        raise AssertionError("Must not load credentials for contaminated held-out evaluation")

    monkeypatch.setattr(jev, "key_from_environment", secret_access)
    output = tmp_path / "results.json"
    args = argparse.Namespace(
        cases=MODULE.parent / "cases.json",
        split="heldout",
        limit=1,
        max_requests=40,
        max_tokens=600000,
        model="jev-1.13.0",
        output=str(output),
    )
    with pytest.raises(ValueError, match="overlap tuning"):
        jev.run(args)
    assert not output.exists()
    assert not (tmp_path / "usage-ledger.json").exists()


@pytest.mark.parametrize("contaminated", [False, True])
def test_custom_corpus_preflight_checks_beyond_request_limit(monkeypatch, tmp_path, contaminated):
    tuning = copy.deepcopy(CASES[0])
    disjoint = copy.deepcopy(tuning)
    disjoint.update(id="synthetic-disjoint", split="heldout")
    disjoint["posting"]["j1"] = "Synthetic independent internship: use SQL for quality analysis."
    duplicate = copy.deepcopy(tuning)
    duplicate.update(id="synthetic-duplicate-after-limit", split="heldout", label="review")
    corpus = [tuning, disjoint, duplicate] if contaminated else [tuning, disjoint]
    path = tmp_path / "synthetic-cases.json"
    path.write_text(json.dumps(corpus))
    output = tmp_path / "must-not-be-created" / "results.json"

    class OfflinePreflightReached(Exception):
        """Stop before reading any real credential or constructing a network client."""

    secret_calls = []

    def credential_boundary():
        secret_calls.append(True)
        raise OfflinePreflightReached

    def forbidden_client(*args, **kwargs):
        raise AssertionError("Offline preflight must not construct an HTTP client")

    monkeypatch.setattr(jev, "key_from_environment", credential_boundary)
    monkeypatch.setattr(jev.httpx, "Client", forbidden_client)
    args = argparse.Namespace(
        cases=path,
        split="heldout",
        limit=1,
        max_requests=1,
        max_tokens=20000,
        model="jev-1.13.0",
        output=str(output),
    )
    if contaminated:
        with pytest.raises(ValueError, match="overlap tuning"):
            jev.run(args)
        assert secret_calls == []
    else:
        assert jev.overlapping_model_inputs(corpus, args.model) == []
        with pytest.raises(OfflinePreflightReached):
            jev.run(args)
        assert secret_calls == [True]
    assert not output.parent.exists()


@pytest.mark.parametrize(
    "case_id,expected",
    [
        ("h-date-boundary", "satisfied"),
        ("h-date-outside", "violated"),
        ("h-date-conflict", "ambiguous"),
        ("h-years-exact", "violated"),
    ],
)
def test_exact_comparisons(case_id, expected):
    case = next(c for c in CASES if c["id"] == case_id)
    assert set(jev.exact_checks(case).values()) == {expected}


def test_fit_cannot_override_supported_mandatory_violation():
    case = CASES[0]
    row = jev.assess(case, response_for(case, {"role": "violated"}))
    assert row["normalized_fit"] == 100
    assert row["experimental_decision"] == "reject"
    assert row["release_decision"] == "review"


def test_low_confidence_violation_routes_to_review():
    case = CASES[0]
    result = response_for(case, {"role": "violated"})
    result.answers["role"].confidence = 0.79
    assert jev.assess(case, result)["experimental_decision"] == "review"


def test_unsupported_evidence_cannot_reject():
    case = CASES[0]
    result = response_for(case, {"education": "violated"})
    result.answers["education_evidence"].choice = "none"
    result.answers["education_evidence"].probabilities = {
        k: float(k == "none") for k in ["none", *case["posting"]]
    }
    assert jev.assess(case, result)["experimental_decision"] == "review"


@pytest.mark.parametrize("outcome", ["ambiguous", "not_stated"])
def test_unknown_facts_route_to_review(outcome):
    case = CASES[0]
    assert (
        jev.assess(case, response_for(case, {"authorization": outcome}))["experimental_decision"]
        == "review"
    )


def test_evidence_ids_are_closed_set():
    case = CASES[0]
    result = response_for(case)
    result.answers["role_evidence"].probabilities["invented"] = 0
    with pytest.raises(ValueError, match="evidence"):
        jev.assess(case, result)


def test_invalid_probabilities_fail_closed():
    with pytest.raises(ValidationError):
        jev.Answer(
            type="choice",
            choice="satisfied",
            confidence=1,
            probabilities={"satisfied": float("nan")},
        )
    with pytest.raises(ValidationError):
        jev.Answer(
            type="score", score=3, confidence=1, probabilities={"0": 1, "1": 0, "2": 0, "3": 0}
        )


def test_probability_rounding_matches_observed_api_contract():
    jev.Answer(
        type="score",
        score=0.30,
        confidence=0.7,
        probabilities={"0": 0.71, "1": 0.29, "2": 0, "3": 0},
    )


def test_missing_answers_fail_closed():
    case = CASES[0]
    result = response_for(case)
    del result.answers["skills"]
    with pytest.raises(ValueError, match="Missing"):
        jev.assess(case, result)


def test_request_labels_and_numeric_comparisons_are_not_sent():
    case = next(c for c in CASES if c["id"] == "h-date-outside")
    body = jev.request_body(case, "jev-1.13.0")
    assert set(body) == {"model", "state", "questions"}
    assert set(body["state"]) == {"candidate", "posting"}
    assert all(q["type"] in {"choice", "score"} for q in body["questions"].values())


def test_metrics_count_false_rejection_and_ranking_ties():
    a, b = CASES[0], CASES[4]
    rows = [jev.assess(a, response_for(a, {"role": "violated"})), jev.assess(b, response_for(b))]
    for row in rows:
        row["latency_ms"] = 100
    metrics = jev.summarize(rows)
    assert metrics["false_rejection_rate"] == 1
    assert metrics["rejection_precision"] == 0
    assert metrics["ranking_pair_accuracy"] == 0.5


def test_release_gate_requires_independent_human_labels_even_with_good_metrics():
    metrics = {
        "eligible_n": 500,
        "rejected_n": 100,
        "rejection_precision": 1,
        "expected_review_recall": 1,
        "ranking_pair_n": 50,
        "ranking_pair_accuracy": 1,
        "false_rejection_count": 0,
    }
    assert jev.release_gate(metrics) == [
        "Representative independent human adjudication is required"
    ]


def test_budget_blocks_before_loading_secret(monkeypatch, tmp_path):
    def secret_access():
        raise AssertionError("Must not access secret when request count invalid")

    monkeypatch.setattr(jev, "key_from_environment", secret_access)
    args = argparse.Namespace(
        cases=MODULE.parent / "cases.json",
        split="tuning",
        limit=8,
        max_requests=1,
        max_tokens=1000,
        model="jev-1.13.0",
        output=str(tmp_path / "results.json"),
    )
    with pytest.raises(ValueError, match="request budget"):
        jev.run(args)
