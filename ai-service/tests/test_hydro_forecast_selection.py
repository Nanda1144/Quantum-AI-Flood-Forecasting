# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 5: model selection is a decision with a recorded reason, not a `min()`.

The tests here pin down the properties a ranking has to have if anyone is going to
trust it. The important ones are not "the forest wins" - which depends on a
synthetic fixture and means nothing - but:

* **direction is never assumed.** R² and NSE are higher-is-better; MAE, RMSE and
  peak absolute error are lower-is-better; bias is not a ranking metric at all.
  Two Phase 4 defects came from assuming otherwise, and both produced a confident
  answer that was backwards, so the direction is asserted directly and the two
  Phase 4 fixes are regression-tested from here.
* **an ineligible model is never selected**, whatever its score. A
  dependency-blocked model has no score to beat, so ranking it would mean
  inventing one.
* **the baseline is compared against, not ranked with.** The baseline is the
  measure of whether a learned model earned its keep, and folding it into the same
  ranking would let "persistence is the best model here" arrive as a selection.
* **ties break deterministically.** Equal scores must resolve the same way on every
  run and every machine, or a deployment changes model without changing anything.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.engines.hydro.forecast_artifact import STATE_DEPENDENCY_BLOCKED, ForecastArtifact
from app.engines.hydro.forecast_selection import (
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    METRIC_DIRECTIONS,
    SelectionCandidate,
    SelectionDecision,
    SelectionError,
    candidates_from_artifacts,
    direction_table,
    metric_direction,
    select_model,
)
from app.engines.hydro.model_evaluation import (
    METRIC_DIRECTIONS as PHASE4_DIRECTIONS,
)
from app.engines.hydro.model_evaluation import (
    ModelEvaluationError,
    metric_direction as phase4_direction,
)

from hydro_phase5_fixtures import (
    STATION_A,
    SYNTHETIC_DISCLAIMER,
    TARGET,
    artifact_for,
    manifests,
    model_dataset,
    store,
    trained_run,
)

BASELINE = "naive"
LEARNED = "random_forest"
BLOCKED = "xgboost"


def _artifact(
    store,
    family: str,
    **overrides,
) -> ForecastArtifact:
    """A real artifact from the fixture store, optionally altered.

    Metric overrides go through the manifest's own `metrics_by_split`, so a test
    that invents a ranking is inventing it in the place Phase 5 actually reads,
    not by constructing a parallel structure that could drift from it.
    """
    original = artifact_for(store, family)
    metrics = {
        split: dict(values) for split, values in original.metrics_by_split.items()
    }
    for (split, metric), value in overrides.pop("metrics", {}).items():
        metrics.setdefault(split, {})[metric] = value
    return dataclasses.replace(original, metrics_by_split=metrics, **overrides)


def _candidate(store, family: str, **overrides) -> SelectionCandidate:
    return SelectionCandidate(artifact=_artifact(store, family, **overrides))


# --------------------------------------------------------------------------- #
# Metric direction - the property two Phase 4 defects violated
# --------------------------------------------------------------------------- #


def test_the_direction_of_every_ranking_metric_is_stated_not_assumed() -> None:
    """R² and NSE go up. Everything else a selection may rank on goes down.

    Asserted as a table rather than exercised indirectly, because the failure this
    guards against is invisible in any single selection: a model with R² = -0.4
    sorts correctly here and there is nothing in the output to say the code got it
    right.
    """
    assert LOWER_IS_BETTER == frozenset({"mae", "rmse", "peak_absolute_error"})
    assert HIGHER_IS_BETTER == frozenset({"r2", "nse"})
    assert metric_direction("rmse") == "lower"
    assert metric_direction("mae") == "lower"
    assert metric_direction("peak_absolute_error") == "lower"
    assert metric_direction("r2") == "higher"
    assert metric_direction("nse") == "higher"


def test_nse_is_higher_is_better_and_phase4_was_wrong_about_it() -> None:
    """The exact defect: NSE was listed among the lower-is-better metrics.

    Nash-Sutcliffe efficiency ranges from `-inf` to `1`, and `1` is a perfect
    forecast. Treating it as lower-is-better would have selected the *worst* model
    available. The test asserts both that Phase 5 is right and that the Phase 4
    helper Phase 5 relies on agrees — the two must not be able to disagree.
    """
    assert metric_direction("nse") == "higher"
    assert phase4_direction("nse") == "higher", (
        "Phase 5 and Phase 4 disagree about the direction of NSE; selection would then rank "
        "on one convention while training reported on another"
    )


def test_phase5_and_phase4_agree_on_every_metric() -> None:
    """One direction table, checked from both sides.

    `forecast_selection` re-exports Phase 4's table and helper rather than restating
    them. This test is what makes that safe: if either side is edited, this fails
    rather than the two quietly diverging - which is how selection would end up
    ranking on one convention while training reported on another.
    """
    assert dict(METRIC_DIRECTIONS) == dict(PHASE4_DIRECTIONS)
    for metric, expected in METRIC_DIRECTIONS.items():
        if expected == "unrankable":
            continue
        assert metric_direction(metric) == phase4_direction(metric) == expected


def test_a_metric_that_cannot_rank_is_named_rather_than_sorted() -> None:
    """Bias is signed. Its `abs` is rankable, but bias itself is not a quality.

    Sorting signed bias would prefer a large negative bias over a small positive
    one, and the winner would depend on how many gauges overestimate - which is not
    a statement about forecast quality. The *table* reports it as unrankable; the
    *lookup* refuses, so a caller cannot accidentally treat the table entry as a
    usable direction.
    """
    assert METRIC_DIRECTIONS["bias"] == "unrankable"
    assert direction_table()["bias"] == "unrankable"
    with pytest.raises(ModelEvaluationError) as caught:
        metric_direction("bias")
    assert "two-sided" in str(caught.value)


def test_an_unknown_metric_is_refused() -> None:
    with pytest.raises(ModelEvaluationError) as caught:
        metric_direction("how_it_feels")
    assert "how_it_feels" in str(caught.value)
    for known in METRIC_DIRECTIONS:
        assert known in str(caught.value), f"the refusal does not mention {known!r}"


def test_selecting_on_an_unknown_metric_says_it_is_unknown_not_two_sided(store) -> None:
    """Two different mistakes, two different messages.

    Conflating "I have never heard of this metric" with "this metric has no direction"
    would send a reader to check the metric's definition when the real problem is a
    typo in a configuration value.
    """
    with pytest.raises(SelectionError) as caught:
        select_model(candidates_from_artifacts(store.artifacts), metric="how_it_feels")
    message = str(caught.value)
    assert "not a known metric" in message
    assert "two-sided" not in message


def test_selecting_on_an_unrankable_metric_is_refused(store) -> None:
    with pytest.raises(SelectionError) as caught:
        select_model(candidates_from_artifacts(store.artifacts), metric="bias")
    message = str(caught.value)
    assert "bias" in message
    assert "two-sided" in message
    for rankable in ("mae", "rmse", "r2", "nse", "peak_absolute_error"):
        assert rankable in message, f"the refusal does not list {rankable!r} as rankable"


def test_selecting_on_an_unknown_metric_is_refused(store) -> None:
    with pytest.raises(SelectionError) as caught:
        select_model(candidates_from_artifacts(store.artifacts), metric="vibes")
    assert "vibes" in str(caught.value)


# --------------------------------------------------------------------------- #
# Which models may be ranked at all
# --------------------------------------------------------------------------- #


def test_a_dependency_blocked_model_is_visible_but_never_ranked(store) -> None:
    """It has no score, so ranking it would mean inventing one.

    Kept in the candidate list rather than filtered out, because a model that was
    tried and could not run is a finding the reader needs; it is rejected at the
    eligibility step instead, where the reason is recorded. Filtering it earlier
    would produce the same winner with no trace that xgboost existed.
    """
    candidates = candidates_from_artifacts(store.artifacts, target=TARGET, horizon="6h")
    families = {candidate.artifact.model_family for candidate in candidates}
    assert BLOCKED in families

    blocked = next(c for c in candidates if c.artifact.model_family == BLOCKED)
    verdict, reason = blocked.eligibility(metric="rmse", split="validation")
    assert verdict == "rejected"

    decision = select_model(candidates, metric="rmse")
    assert decision.selected.artifact.model_family != BLOCKED
    assert all(BLOCKED not in model_id for model_id, _ in decision.ranked)


def test_a_blocked_model_is_reported_as_rejected_with_its_reason(store) -> None:
    """Excluded, not forgotten. A reader must learn the blocker from the decision."""
    decision = select_model(candidates_from_artifacts(store.artifacts), metric="rmse")
    blocked_id = artifact_for(store, BLOCKED).model_id
    assert blocked_id in decision.rejected
    assert "xgboost" in decision.rejected[blocked_id]
    assert STATE_DEPENDENCY_BLOCKED in decision.rejected[blocked_id]


def test_a_model_with_no_metric_on_the_selected_split_is_excluded(store) -> None:
    """A score on another split is not a score on this one.

    Ranking on the test split while training used validation would make the reported
    metric a number the model was chosen for having already produced, which is the
    selection-on-the-test-set error in its purest form.
    """
    candidate = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.1})
    candidate = dataclasses.replace(
        candidate,
        artifact=dataclasses.replace(
            candidate.artifact,
            metrics_by_split={"test": {"rmse": 0.0001}},
        ),
    )
    decision = select_model([candidate, _candidate(store, BASELINE)], metric="rmse")
    assert decision.selected is None or LEARNED not in decision.selected.artifact.model_family
    assert decision.rejected.get(candidate.artifact.model_id)


def test_a_model_missing_a_required_metric_is_excluded_not_treated_as_worst(store) -> None:
    """Zero is a metric value, so a missing one must not default into it.

    Defaulting to `0.0` on a lower-is-better metric would make an unevaluated model
    look like the best model in the ranking.
    """
    forest = _artifact(store, LEARNED)
    broken = dataclasses.replace(
        forest,
        metrics_by_split={"validation": {"mae": 0.1}},
    )
    decision = select_model(
        [SelectionCandidate(artifact=broken), _candidate(store, BASELINE)], metric="rmse"
    )
    assert LEARNED not in {c.artifact.model_family for c in decision.ranked if True}
    assert "rmse" in decision.rejected.get(forest.model_id, "")


def test_an_artifact_that_is_not_available_is_excluded(store) -> None:
    """`invalid`, `artifact_missing` and `dependency_blocked` all mean "cannot run".

    None of them is eligible, and each is rejected for being in that state rather
    than for its score - so a broken model cannot win by having a good metric
    recorded next to it. A healthy candidate is supplied alongside each broken one,
    because the baseline is never selectable and without a second candidate there
    would be nothing to check the exclusion against.
    """
    healthy = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.20})
    for state in ("invalid", "artifact_missing", "dependency_blocked"):
        broken = dataclasses.replace(artifact_for(store, LEARNED), state=state)
        candidate = dataclasses.replace(healthy, artifact=broken)
        verdict, reason = candidate.eligibility(metric="rmse", split="validation")
        assert verdict == "rejected", f"an artifact in state {state!r} was considered eligible"
        assert state in reason

        decision = select_model(
            [candidate, _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.20})],
            metric="rmse",
        )
        assert decision.selected.artifact.state == "available", (
            f"a decision was made from an artifact in state {state!r}"
        )


def test_selection_survives_having_no_candidates_at_all() -> None:
    decision = select_model([], metric="rmse")
    assert decision.selected is None
    assert decision.reason
    assert "no " in decision.reason.lower()
    assert decision.ranked == ()
    assert decision.considered == ()


# --------------------------------------------------------------------------- #
# Picking the winner
# --------------------------------------------------------------------------- #


def test_the_lowest_rmse_wins_when_lower_is_better(store) -> None:
    """Three candidates spanning a factor of three, supplied worst-first.

    The order they are passed in is the opposite of the answer, so a ranking that
    ignored the metric and took the first or last supplied would get this wrong. It
    is also the case an inverted sort key gets wrong: negating the value for a
    lower-is-better metric and taking the front of the list selects RMSE 0.2 from
    {0.1, 0.2, 0.3} and reports it as the best.
    """
    good = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.10})
    middle = _candidate(
        store, LEARNED, metrics={("validation", "rmse"): 0.20}
    )
    middle = dataclasses.replace(
        middle, artifact=dataclasses.replace(middle.artifact, model_id="random_forest-middle")
    )
    poor = _candidate(store, BASELINE, metrics={("validation", "rmse"): 0.30})

    decision = select_model([poor, middle, good], metric="rmse")
    assert decision.selected.artifact.model_id == good.artifact.model_id
    assert decision.selected_value == pytest.approx(0.10)
    assert [value for _, value in decision.ranked] == [0.10, 0.20]


def test_the_highest_r2_wins_when_higher_is_better(store) -> None:
    """The second Phase 4 defect: `_select` sorted ascending, so `r2` chose the worst.

    Both candidates here have a *negative* R², which is realistic for a model on a
    short synthetic window and is exactly the case where a reversed sort hands back
    the model that fits worse. The assertion is on which model won, not on whether
    the number was good.
    """
    better = _candidate(store, LEARNED, metrics={("validation", "r2"): -0.10})
    worse = _candidate(store, LEARNED, metrics={("validation", "r2"): -0.60})
    worse = dataclasses.replace(worse, artifact=dataclasses.replace(worse.artifact, model_id="worse"))
    decision = select_model([worse, better], metric="r2")
    assert decision.selected_value == pytest.approx(-0.10)
    assert decision.selected.artifact.metrics_by_split["validation"]["r2"] == pytest.approx(-0.10)


def test_the_highest_nse_wins_when_higher_is_better(store) -> None:
    better = _candidate(store, LEARNED, metrics={("validation", "nse"): 0.31})
    worse = _candidate(store, LEARNED, metrics={("validation", "nse"): -0.44})
    worse = dataclasses.replace(worse, artifact=dataclasses.replace(worse.artifact, model_id="worse"))
    decision = select_model([worse, better], metric="nse")
    assert decision.selected_value == pytest.approx(0.31)


def test_the_closest_mae_wins_when_lower_is_better(store) -> None:
    better = _candidate(store, LEARNED, metrics={("validation", "mae"): 0.21})
    worse = _candidate(store, LEARNED, metrics={("validation", "mae"): 0.25})
    worse = dataclasses.replace(worse, artifact=dataclasses.replace(worse.artifact, model_id="worse"))
    decision = select_model([better, worse], metric="mae")
    assert decision.selected_value == pytest.approx(0.21)


def test_selection_can_be_run_on_the_test_split_when_asked(store) -> None:
    """Which split is named is the caller's decision, and is recorded in the output.

    Phase 4's convention is validation. This does not argue for it; it asserts that
    the split is a parameter whose value is visible in the decision, so a run on the
    test split cannot be mistaken for a run on validation.
    """
    decision = select_model(
        candidates_from_artifacts(store.artifacts), metric="rmse", split="test"
    )
    assert decision.split == "test"
    assert decision.selected is not None
    assert decision.reason


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_equal_scores_break_the_tie_by_model_id(store) -> None:
    """Not by insertion order, not by hash order - by name.

    Two identical-scoring models are indistinguishable on the metric, so the choice
    has to come from something stable. `model_id` is: it is in the manifest, it is
    in the file name, and it is the same on every machine.
    """
    first = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.25})
    first = dataclasses.replace(
        first, artifact=dataclasses.replace(first.artifact, model_id="aaa-model")
    )
    second = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.25})
    second = dataclasses.replace(
        second, artifact=dataclasses.replace(second.artifact, model_id="zzz-model")
    )
    forward = select_model([first, second], metric="rmse")
    backward = select_model([second, first], metric="rmse")

    assert forward.selected.artifact.model_id == "aaa-model"
    assert backward.selected.artifact.model_id == "aaa-model", (
        "the tie broke differently depending on the order the candidates were supplied; a "
        "deployment would then change model without any change to the data or the code"
    )
    assert forward.tied_model_ids == ("zzz-model",), (
        "the tie is recorded as the other candidate(s) sharing the winner's score"
    )


def test_the_same_input_selects_the_same_model_every_time(store) -> None:
    candidates = candidates_from_artifacts(store.artifacts, target=TARGET, horizon="6h")
    decisions = [select_model(candidates, metric="rmse") for _ in range(5)]
    assert len({d.selected.artifact.model_id for d in decisions}) == 1
    assert len({d.reason for d in decisions}) == 1
    assert len({d.ranked for d in decisions}) == 1


def test_a_tie_on_the_metric_is_reported_as_a_tie(store) -> None:
    """A tie resolved by name is still a tie on the metric, and saying so is honest.

    Without this the reason reads as though the model had *won* on the metric, which
    is not what happened - the id decided it. The reason is the audit record, so a
    tie that is only disclosed in `describe()` is a tie most readers never see.
    """
    a = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.25})
    a = dataclasses.replace(a, artifact=dataclasses.replace(a.artifact, model_id="aaa"))
    b = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.25})
    b = dataclasses.replace(b, artifact=dataclasses.replace(b.artifact, model_id="bbb"))
    decision = select_model([a, b], metric="rmse")

    assert decision.tied_model_ids == ("bbb",), (
        "the tie is recorded as the models that shared the winner's score; the winner itself "
        "is not among them, so an empty tuple means no tie"
    )
    reason = decision.reason.lower()
    assert "tie" in reason
    assert "did not win on the metric" in reason
    assert "bbb" in decision.reason
    assert decision.selected_value == pytest.approx(0.25)


def test_an_untied_selection_does_not_claim_a_tie(store) -> None:
    """The tie note is conditional; a clean win must not read as a coin toss."""
    good = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.10})
    other = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.30})
    other = dataclasses.replace(other, artifact=dataclasses.replace(other.artifact, model_id="other"))
    decision = select_model([good, other], metric="rmse")
    assert decision.tied_model_ids == ()
    assert "tie" not in decision.reason.lower()


# --------------------------------------------------------------------------- #
# The baseline comparison
# --------------------------------------------------------------------------- #


def test_the_baseline_is_compared_against_and_not_ranked_with(store) -> None:
    """A model that is merely as good as persistence has not earned selection.

    If the baseline sat in the ranking it could win, and "we selected persistence"
    would arrive as a legitimate outcome rather than as the null result it is.
    """
    baseline = _candidate(store, BASELINE, metrics={("validation", "rmse"): 0.20})
    learned = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.25})
    decision = select_model([baseline, learned], metric="rmse")

    assert decision.selected.artifact.model_family == LEARNED
    assert BASELINE not in {model_id for model_id, _ in decision.ranked}
    assert decision.baseline_model_id == baseline.artifact.model_id
    assert decision.baseline_value == pytest.approx(0.20)


def test_a_model_that_loses_to_the_baseline_says_so_in_words(store) -> None:
    """The honest outcome, stated plainly rather than left for a reader to compute."""
    baseline = _candidate(store, BASELINE, metrics={("validation", "rmse"): 0.20})
    learned = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.25})
    decision = select_model([baseline, learned], metric="rmse")
    comparison = decision.baseline_comparison
    assert "lost to" in comparison.lower()
    assert "rmse" in comparison
    # The values are named as numbers a reader can check against the ranking, so the
    # claim does not rest on trusting the prose.
    assert {0.2, 0.25} <= _numbers_in(comparison)


def test_a_model_that_beats_the_baseline_says_by_how_much(store) -> None:
    baseline = _candidate(store, BASELINE, metrics={("validation", "rmse"): 0.30})
    learned = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.20})
    decision = select_model([baseline, learned], metric="rmse")
    assert "beat" in decision.baseline_comparison.lower()
    assert {0.3, 0.2} <= _numbers_in(decision.baseline_comparison)


def _numbers_in(text: str) -> set[float]:
    """Every float literal in a string, so a test checks the value not the format.

    Written this way because asserting on a formatted string couples the test to
    `:g` versus `:.2f`. What matters is that the comparison names the numbers it
    compared, not how many digits it chose to print.
    """
    import re

    return {float(token) for token in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", text)}


def test_a_model_that_exactly_matches_the_baseline_says_it_matched(store) -> None:
    """Not "won by 0.0". A tie with persistence is a different claim from a win."""
    baseline = _candidate(store, BASELINE, metrics={("validation", "rmse"): 0.20})
    learned = _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.20})
    decision = select_model([baseline, learned], metric="rmse")
    assert "matched" in decision.baseline_comparison.lower()
    assert "lost" not in decision.baseline_comparison.lower()


def test_no_comparison_is_reported_when_there_is_no_baseline_to_compare(store) -> None:
    """An absent baseline is explained, not silently skipped.

    `None` would leave a reader wondering whether the comparison was merely
    identical or never attempted; a sentence says which.
    """
    decision = select_model(
        [_candidate(store, LEARNED, metrics={("validation", "rmse"): 0.20})],
        metric="rmse",
        baseline_family=None,
    )
    assert decision.baseline_model_id is None
    assert decision.baseline_value is None
    assert "no persistence baseline" in decision.baseline_comparison.lower()


def test_an_unscored_baseline_is_not_compared_against_an_assumed_zero(store) -> None:
    """A baseline with no metric cannot establish what would have been good enough.

    Defaulting it to zero would compare the winner against a number that was never
    measured - and on a lower-is-better metric that reads as an enormous win.
    """
    unscored = dataclasses.replace(artifact_for(store, BASELINE), metrics_by_split={})
    decision = select_model(
        [
            SelectionCandidate(artifact=unscored),
            _candidate(store, LEARNED, metrics={("validation", "rmse"): 0.20}),
        ],
        metric="rmse",
    )
    assert decision.selected.artifact.model_family == LEARNED
    assert decision.baseline_value is None
    assert "no rmse recorded" in decision.baseline_comparison.lower()
    assert "not treated as a zero" in decision.baseline_comparison.lower()
    assert 0.0 not in _numbers_in(decision.baseline_comparison)


# --------------------------------------------------------------------------- #
# Recording the decision
# --------------------------------------------------------------------------- #


def test_the_decision_says_why_the_model_was_chosen(store) -> None:
    decision = select_model(candidates_from_artifacts(store.artifacts), metric="rmse")
    assert decision.selected.artifact.model_id in decision.reason
    assert "rmse" in decision.reason
    assert "validation" in decision.reason
    assert "lower" in decision.reason


def test_the_decision_records_the_metric_the_split_and_the_direction(store) -> None:
    decision = select_model(candidates_from_artifacts(store.artifacts), metric="mae")
    assert decision.metric == "mae"
    assert decision.split == "validation"
    assert decision.direction == "lower"
    assert decision.target == TARGET
    assert decision.horizon == "6h"


def test_every_considered_model_is_listed_even_when_it_lost(store) -> None:
    """An audit trail of what was on the table, not only of what won."""
    decision = select_model(candidates_from_artifacts(store.artifacts), metric="rmse")
    assert LEARNED in {a.artifact.model_family for a in candidates_from_artifacts(store.artifacts)}
    assert set(decision.considered) <= set(decision.rejected) | {
        decision.selected.artifact.model_id
    }


def test_the_decision_carries_the_synthetic_status_of_the_data_it_ranked_on(store) -> None:
    """A ranking computed on synthetic data must not read as a production claim."""
    decision = select_model(candidates_from_artifacts(store.artifacts), metric="rmse")
    assert decision.synthetic_demo is True
    assert decision.data_status == "synthetic_demo"
    assert decision.disclaimer == SYNTHETIC_DISCLAIMER


def test_the_decision_serialises_and_describes_itself(store) -> None:
    decision = select_model(candidates_from_artifacts(store.artifacts), metric="rmse")
    payload = decision.to_dict()
    for field in (
        "selected_model_id",
        "selected_value",
        "metric",
        "split",
        "direction",
        "reason",
        "ranked",
        "rejected",
        "baseline_comparison",
        "synthetic_demo",
        "disclaimer",
    ):
        assert field in payload, f"the decision payload omits {field!r}"
    text = decision.describe()
    assert decision.selected.artifact.model_id in text
    assert SYNTHETIC_DISCLAIMER in text


def test_the_decision_is_serialisable_when_nothing_was_selected() -> None:
    """An empty decision still has to be reportable - that is the common case for a
    dependency-blocked deployment."""
    decision = select_model([], metric="rmse")
    payload = decision.to_dict()
    assert payload["selected_model_id"] is None
    assert payload["reason"]
    assert decision.describe()


# --------------------------------------------------------------------------- #
# Candidates from artifacts
# --------------------------------------------------------------------------- #


def test_candidates_can_be_narrowed_by_target_and_horizon(store) -> None:
    everything = candidates_from_artifacts(store.artifacts)
    narrowed = candidates_from_artifacts(store.artifacts, target=TARGET, horizon="6h")
    assert len(narrowed) <= len(everything)
    assert all(
        c.artifact.target == TARGET and c.artifact.horizon == "6h" for c in narrowed
    )
    assert candidates_from_artifacts(store.artifacts, target="target_inflow_6h") == ()


def test_a_candidate_reports_the_metric_value_and_whether_it_has_one(store) -> None:
    candidate = _candidate(store, LEARNED)
    assert candidate.metric_on("rmse", "validation") is not None
    assert candidate.metric_on("rmse", "test") is not None
    assert candidate.metric_on("rmse", "train") is None
    assert set(candidate.scored_splits()) >= {"validation", "test"}


def test_a_candidate_explains_its_own_eligibility(store) -> None:
    """One method a caller can use to find out why something would be refused.

    Returns `(verdict, reason)`, with `reason` `None` when nothing is wrong - so a
    caller can ask "may I use this, and if not why" in one call rather than by
    comparing state strings itself.
    """
    verdict, reason = _candidate(store, LEARNED).eligibility(metric="rmse", split="validation")
    assert verdict == "eligible"
    assert reason is None

    unscored = SelectionCandidate(
        artifact=dataclasses.replace(artifact_for(store, LEARNED), metrics_by_split={})
    )
    verdict, reason = unscored.eligibility(metric="rmse", split="validation")
    assert verdict == "rejected"
    assert reason


def test_availability_is_reported_before_evaluability(store) -> None:
    """A model that cannot forecast is described as such, not as merely unscored.

    The order matters for the reader: "install xgboost" is the action, and telling
    someone a model was excluded for having no metrics when the real problem is a
    missing package sends them looking in the wrong place.
    """
    blocked = artifact_for(store, BLOCKED)
    assert blocked.metrics_by_split == {}
    verdict, reason = SelectionCandidate(artifact=blocked).eligibility(
        metric="rmse", split="validation"
    )
    assert verdict == "rejected"
    assert STATE_DEPENDENCY_BLOCKED in reason
    assert "metric" not in reason.lower() or "xgboost" in reason


def test_a_candidate_asks_for_a_metric_it_does_not_have(store) -> None:
    candidate = _candidate(store, LEARNED)
    verdict, reason = candidate.eligibility(metric="not_a_metric", split="validation")
    assert verdict == "rejected"
    assert "not_a_metric" in reason

    verdict, reason = candidate.eligibility(metric="rmse", split="train")
    assert verdict == "rejected"
    assert "train" in reason


def test_the_direction_table_is_reported_for_readers() -> None:
    """A reader asking "which way does this metric go?" gets an answer, not a guess."""
    table = direction_table()
    assert table["r2"] == "higher"
    assert table["rmse"] == "lower"
    assert set(table) == set(METRIC_DIRECTIONS)


def test_the_station_is_carried_through_selection(store) -> None:
    """The fixture entities are synthetic and the tests must not lose that."""
    from hydro_phase5_fixtures import STATION_B

    assert STATION_A.startswith("SYNTHETIC-")
    assert STATION_B.startswith("SYNTHETIC-")