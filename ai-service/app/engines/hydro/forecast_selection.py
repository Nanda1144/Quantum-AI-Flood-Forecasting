# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Choosing which trained model answers a request, out of the ones that exist.

Selection here is three questions asked in order, and it refuses to answer any of
them by guessing:

1. **Is this model allowed to be selected?** A dependency-blocked model, an
   artifact that was never written, one that never fitted, one that was never
   scored - each is excluded here with a reason naming the state. A model that
   cannot produce a forecast cannot be chosen to produce one.
2. **Which direction is better for the configured metric?** Resolved through
   Phase 4's `metric_direction`, never inferred. This is the question that is
   easiest to get wrong and hardest to notice: ranking R-squared ascending returns
   the *worst* model that produced a number, and the table still looks populated.
3. **How is a tie broken?** On `model_id`, lexicographically. Two models that
   score identically must not produce different answers on different runs, so the
   tie-break is part of the contract and is reported in the decision.

**The baseline is not a candidate.** The persistence baseline is the yardstick, so
it is excluded from being selected - a run that picks it has learned that nothing
beat "assume no change", which is a finding to state rather than a winner to
announce. Its value is still recorded, and the decision always says whether the
winner actually beat it.

**No model is described as better without a comparison on the same rows.** The
baseline delta this module reports comes from Phase 4's comparison table, which
scored every model on an identical row set. Nothing here recomputes a metric or
compares against a number from a different split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .forecast_artifact import STATE_AVAILABLE, ForecastArtifact
from .model_evaluation import (
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    METRIC_DIRECTIONS,
    metric_direction,
)


class SelectionError(ValueError):
    """Selection could not be carried out at all - as opposed to finding no winner."""


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SelectionCandidate:
    """One model offered for selection, with everything needed to rule it in or out.

    Built from a `ForecastArtifact` rather than from a bare metrics dictionary, so
    eligibility is decided from the same validated artifact the serving path will
    load. Two different views of "which models are there" is how a serving path
    ends up selecting a model it then cannot load.
    """

    artifact: ForecastArtifact

    @property
    def model_id(self) -> str:
        return self.artifact.model_id

    @property
    def model_family(self) -> str:
        return self.artifact.model_family

    @property
    def artifact_id(self) -> str:
        return self.artifact.artifact_id

    @property
    def target(self) -> str:
        return self.artifact.target

    @property
    def horizon(self) -> str:
        return self.artifact.horizon

    @property
    def state(self) -> str:
        return self.artifact.state

    @property
    def is_baseline(self) -> bool:
        return self.artifact.role == "baseline"

    def metric_on(self, metric: str, split: str) -> float | None:
        """The recorded value of `metric` on `split`, or `None` if it was never scored.

        `None` means "does not exist", never "zero". A model that produced no
        number must not be ranked as though it had produced a perfect one.
        """
        return (self.artifact.metrics_by_split.get(split) or {}).get(metric)

    def scored_splits(self) -> tuple[str, ...]:
        return tuple(sorted(self.artifact.metrics_by_split))

    def eligibility(self, *, metric: str, split: str) -> tuple[str, str | None]:
        """`(verdict, reason)`: whether this candidate may be selected, and why not.

        The order is deliberate. Availability comes before evaluability, because a
        model that cannot forecast should be described as such even if it also
        happens to lack a score - "the reason it was excluded" is the first thing a
        reader acts on.
        """
        artifact = self.artifact
        if artifact.state != STATE_AVAILABLE:
            return "rejected", (
                f"artifact state is {artifact.state!r}"
                + (f": {artifact.reason}" if artifact.reason else "")
                + "; a model that cannot produce a forecast cannot be selected to produce one"
            )
        if not artifact.selectable:
            return "rejected", (
                "the artifact records no evaluation metrics, so there is nothing to rank it on; "
                "an unscored model is not a worse model, it is an unmeasured one"
            )
        if metric not in METRIC_DIRECTIONS:
            return "rejected", (
                f"metric {metric!r} is not rankable ({METRIC_DIRECTIONS.get(metric, 'unknown')})"
            )
        if split not in self.artifact.metrics_by_split:
            return "rejected", (
                f"no {split!r} evaluation was recorded; this candidate was scored on "
                f"{list(self.scored_splits()) or 'nothing'} and ranking across a split it was "
                "never scored on would compare two different questions"
            )
        if self.metric_on(metric, split) is None:
            return "rejected", (
                f"{metric!r} is not present in the recorded {split!r} metrics "
                f"{sorted(self.artifact.metrics_by_split.get(split) or {})}"
            )
        if self.is_baseline:
            return "rejected", (
                "this is the persistence baseline, which is the yardstick rather than a candidate; "
                "a run that selected it has learned that nothing beat 'assume no change'"
            )
        return "eligible", None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "artifact_id": self.artifact_id,
            "target": self.target,
            "horizon": self.horizon,
            "state": self.state,
            "role": self.artifact.role,
            "is_baseline": self.is_baseline,
            "synthetic_demo": self.artifact.synthetic_demo,
            "data_status": self.artifact.data_status,
            "metrics_by_split": {
                split: dict(sorted(values.items()))
                for split, values in sorted(self.artifact.metrics_by_split.items())
            },
        }


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SelectionDecision:
    """What was selected, what was not, and why - in one object.

    Every field here is a fact a reader might need. The rejections matter as much
    as the winner: a run where three of four families were dependency-blocked and
    one was selected is a different finding from a run where four were eligible and
    one won, and only the rejections distinguish them.
    """

    selected: SelectionCandidate | None
    metric: str
    split: str
    direction: str
    reason: str
    ranked: tuple[tuple[str, float], ...] = ()
    rejected: Mapping[str, str] = field(default_factory=dict)
    considered: tuple[str, ...] = ()
    tied_model_ids: tuple[str, ...] = ()
    baseline_model_id: str | None = None
    baseline_value: float | None = None
    selected_value: float | None = None
    baseline_comparison: str | None = None
    target: str | None = None
    horizon: str | None = None
    synthetic_demo: bool = True
    data_status: str = "unknown"
    disclaimer: str | None = None

    @property
    def selected_model_id(self) -> str | None:
        return self.selected.model_id if self.selected is not None else None

    @property
    def found(self) -> bool:
        """True when a model was chosen. Distinct from "no eligible candidates"."""
        return self.selected is not None

    @property
    def beats_baseline(self) -> bool | None:
        """Whether the winner improved on the baseline, or `None` if unknowable.

        `None` is a real answer and not a missing one: with no baseline score, or
        with a metric where the comparison does not apply, the honest statement is
        that nothing can be said.
        """
        if self.baseline_value is None or self.selected_value is None:
            return None
        if self.direction == "lower":
            return self.selected_value < self.baseline_value
        return self.selected_value > self.baseline_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_model_id": self.selected_model_id,
            "selected_artifact_id": self.selected.artifact_id if self.selected else None,
            "selected_family": self.selected.model_family if self.selected else None,
            "metric": self.metric,
            "split": self.split,
            "direction": self.direction,
            "reason": self.reason,
            "ranked": [{"model_id": model_id, "value": value} for model_id, value in self.ranked],
            "rejected": dict(sorted(self.rejected.items())),
            "considered": list(self.considered),
            "tied_model_ids": list(self.tied_model_ids),
            "baseline_model_id": self.baseline_model_id,
            "baseline_value": self.baseline_value,
            "selected_value": self.selected_value,
            "baseline_comparison": self.baseline_comparison,
            "beats_baseline": self.beats_baseline,
            "target": self.target,
            "horizon": self.horizon,
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
        }

    def describe(self) -> str:
        lines = [
            f"Model selection on {self.metric} ({self.direction} is better) over the "
            f"{self.split} split",
        ]
        if self.target:
            lines.append(f"  target / horizon : {self.target} @ {self.horizon}")
        lines.append(f"  candidates       : {list(self.considered) or '(none)'}")
        if self.selected is None:
            lines.append(f"  selected         : none - {self.reason}")
        else:
            lines.append(
                f"  selected         : {self.selected.model_id} "
                f"({self.selected.model_family}) {self.selected_value!r}"
            )
            if self.tied_model_ids:
                lines.append(
                    f"  tie broken on    : model_id, from {list(self.tied_model_ids)}"
                )
        if self.ranked:
            lines.append("  ranking          :")
            for position, (model_id, value) in enumerate(self.ranked, start=1):
                lines.append(f"    {position}. {model_id:<48} {value:.6g}")
        if self.rejected:
            lines.append("  excluded         :")
            for model_id in sorted(self.rejected):
                lines.append(f"    {model_id:<48} {self.rejected[model_id]}")
        if self.baseline_model_id:
            lines.append(
                f"  baseline         : {self.baseline_model_id} = {self.baseline_value!r} "
                f"({self.split})"
            )
            if self.baseline_comparison:
                lines.append(f"  comparison       : {self.baseline_comparison}")
        lines.append(f"  why              : {self.reason}")
        if self.synthetic_demo and self.disclaimer:
            # The exact platform sentence, not a paraphrase. `describe()` is the form a
            # person reads in a log or a ticket, and a paraphrase here is a paraphrase
            # that can drift away from the sentence the pipeline is required to carry.
            lines.append(f"  data status      : {self.disclaimer}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def candidates_from_artifacts(
    artifacts: Iterable[ForecastArtifact],
    *,
    target: str | None = None,
    horizon: str | None = None,
) -> tuple[SelectionCandidate, ...]:
    """Candidates from loaded artifacts, filtered to one target/horizon if asked.

    Sorted by `model_id` so the input order cannot decide the outcome. The filter
    is not applied silently: a caller who asked for one target and got zero
    candidates learns it from the empty list, not from a winner belonging to a
    different question.
    """
    chosen = [
        SelectionCandidate(artifact=artifact)
        for artifact in artifacts
        if (target is None or artifact.target == target)
        and (horizon is None or artifact.horizon == horizon)
    ]
    return tuple(sorted(chosen, key=lambda candidate: candidate.model_id))


def select_model(
    candidates: Sequence[SelectionCandidate],
    *,
    metric: str = "rmse",
    split: str = "validation",
    baseline_family: str | None = "naive",
) -> SelectionDecision:
    """Choose the best eligible candidate, deterministically, or explain why not.

    `metric` must be rankable. An unrankable metric - `bias`, whose goal is zero
    rather than either end - raises `SelectionError` rather than being ranked,
    because "the smallest bias" would select whichever model under-predicts hardest
    and report it as the best.
    """
    # The guard tests the *direction*, not merely whether the name is known. `bias` is
    # a known, reportable metric, so a membership check lets it through and the
    # lookup below raises Phase 4's error instead - which means the explanation a
    # caller gets depends on which of two error types happened to fire first, and the
    # careful message written just below is unreachable for the metric it was written
    # for.
    direction = METRIC_DIRECTIONS.get(metric)
    if direction not in ("lower", "higher"):
        raise SelectionError(
            f"selection metric {metric!r} is not rankable; rankable metrics are "
            f"{sorted(m for m, d in METRIC_DIRECTIONS.items() if d != 'unrankable')}, and "
            f"{sorted(m for m, d in METRIC_DIRECTIONS.items() if d == 'unrankable')} is "
            "two-sided (zero is the goal, not either end)"
            if metric in METRIC_DIRECTIONS
            else f"selection metric {metric!r} is not a known metric; known metrics are "
            f"{sorted(METRIC_DIRECTIONS)}"
        )

    considered = tuple(candidate.model_id for candidate in candidates)
    eligible: list[tuple[SelectionCandidate, float]] = []
    rejected: dict[str, str] = {}

    for candidate in sorted(candidates, key=lambda item: item.model_id):
        verdict, why = candidate.eligibility(metric=metric, split=split)
        if verdict == "eligible":
            value = candidate.metric_on(metric, split)
            # `eligibility` already guaranteed this is not None; the assert-free
            # fallback keeps the type honest without inventing a value.
            eligible.append((candidate, float(value) if value is not None else float("nan")))
        else:
            rejected[candidate.model_id] = why or "rejected"

    baseline_candidate = _baseline_of(candidates, baseline_family)
    baseline_value = (
        baseline_candidate.metric_on(metric, split) if baseline_candidate is not None else None
    )

    if not eligible:
        return SelectionDecision(
            selected=None,
            metric=metric,
            split=split,
            direction=direction,
            reason=(
                f"no candidate was eligible on {metric!r} over the {split!r} split. "
                + (
                    f"{len(rejected)} candidate(s) were considered and every one was excluded; the "
                    "reasons are recorded. This is a finding, not an error: it usually means the "
                    "run produced models but no comparable scores."
                    if rejected
                    else "no candidates were supplied at all."
                )
            ),
            rejected=rejected,
            considered=considered,
            baseline_model_id=baseline_candidate.model_id if baseline_candidate else None,
            baseline_value=baseline_value,
            target=candidates[0].target if candidates else None,
            horizon=candidates[0].horizon if candidates else None,
            synthetic_demo=_synthetic_demo_of(candidates),
            data_status=_data_status_of(candidates),
            disclaimer=_disclaimer_of(candidates),
        )

    # Sort so that the best model comes first, then read the winner off the front.
    #
    # The multiplier negates the value for *higher*-is-better metrics, so that
    # ascending order puts the larger score first. Negating for *lower*-is-better
    # instead - which reads at a glance like the symmetric thing to do - inverts the
    # whole ranking: ascending on `-value` puts the *worst* model first, and the
    # winner is then taken from the front of the list. That failure is silent in the
    # sense that matters most: `select_model` returns a model, a metric value and a
    # confident reason, all of which are individually well formed and jointly wrong.
    # `_rank_key` is the single place the direction is applied, so there is one line
    # to get right and one place to look when it is not.
    eligible.sort(key=lambda item: _rank_key(item, direction))
    ranked = tuple((candidate.model_id, value) for candidate, value in eligible)
    winner, winner_value = eligible[0]
    # The models that *shared* the winner's score, excluding the winner. Excluding it
    # is what makes an empty tuple mean "no tie": a clean win then leaves this empty,
    # and every caller can use plain truthiness to ask whether a tie happened. Had the
    # winner's own id been included, a field that was non-empty for every selection
    # would have made `if tied_model_ids:` report a tie on every clean win.
    tied = tuple(
        candidate.model_id
        for candidate, value in eligible
        if value == winner_value and candidate.model_id != winner.model_id
    )

    reason = _selection_reason(
        winner,
        metric,
        split,
        direction,
        winner_value,
        len(eligible),
        tied_model_ids=tied,
    )
    comparison = _baseline_comparison(winner_value, baseline_value, metric, direction, baseline_candidate)

    return SelectionDecision(
        selected=winner,
        metric=metric,
        split=split,
        direction=direction,
        reason=reason,
        ranked=ranked,
        rejected=rejected,
        considered=considered,
        tied_model_ids=tied,
        baseline_model_id=baseline_candidate.model_id if baseline_candidate else None,
        baseline_value=baseline_value,
        selected_value=winner_value,
        baseline_comparison=comparison,
        target=winner.target,
        horizon=winner.horizon,
        synthetic_demo=_synthetic_demo_of(candidates),
        data_status=_data_status_of(candidates),
        disclaimer=_disclaimer_of(candidates),
    )


def _baseline_of(
    candidates: Sequence[SelectionCandidate], baseline_family: str | None
) -> SelectionCandidate | None:
    """The baseline candidate, by declared role or by family name.

    Role first, family second. The role is what Phase 4's registry declared, and it
    is the more honest signal; the family name is the fallback so a caller who only
    knows "the baseline was the naive one" still gets the comparison.
    """
    if not candidates:
        return None
    for candidate in sorted(candidates, key=lambda item: item.model_id):
        if candidate.is_baseline:
            return candidate
    if baseline_family:
        for candidate in sorted(candidates, key=lambda item: item.model_id):
            if candidate.model_family == baseline_family:
                return candidate
    return None


def _rank_key(
    item: tuple[SelectionCandidate, float], direction: str
) -> tuple[float, str]:
    """`(sort key)` putting the best-scoring candidate first, ties broken by id.

    The value is negated only for *higher*-is-better metrics, so that ascending order
    puts the larger score in front. `model_id` is the tie-break rather than
    discovery order: two candidates with identical scores are indistinguishable on
    the metric, so the choice has to come from something recorded in the manifest
    and identical on every machine.
    """
    candidate, value = item
    return (value if direction == "lower" else -value, candidate.model_id)


def _selection_reason(
    winner: SelectionCandidate,
    metric: str,
    split: str,
    direction: str,
    value: float,
    eligible_count: int,
    *,
    tied_model_ids: tuple[str, ...] = (),
) -> str:
    tie_note = (
        ""
        if not tied_model_ids
        else (
            f" It tied on {metric} with {len(tied_model_ids)} other candidate(s) "
            f"({', '.join(tied_model_ids)}) and was chosen by model_id, not by score: it did not "
            "win on the metric."
        )
    )
    if eligible_count == 1:
        # The direction is stated even here, though nothing was compared. A reader who
        # has only this line should still be able to tell which way the number had to
        # move to be an improvement - and a reason that omitted it is what let an
        # inverted ranking read as a confident selection.
        return (
            f"{winner.model_id} was the only eligible candidate, so it was selected on "
            f"{metric}={value:.6g} ({direction} is better) over the {split} split. Being the only "
            "option is not evidence that it is any good; read its scores, not the fact of its "
            "selection. This is a ranking on synthetic/demo data and supports no claim about any "
            "real river."
        )
    return (
        f"{winner.model_id} has the best {metric} ({value:.6g}, {direction} is better) among "
        f"{eligible_count} eligible candidate(s) scored on the {split} split.{tie_note} This is a "
        "ranking on synthetic/demo data: it orders these models on these rows and supports no claim "
        "about any real river."
    )


def _baseline_comparison(
    winner_value: float,
    baseline_value: float | None,
    metric: str,
    direction: str,
    baseline: SelectionCandidate | None,
) -> str | None:
    """Say plainly whether the winner beat the yardstick, including when it did not."""
    if baseline is None:
        return "no persistence baseline was among the candidates, so no comparison against it is possible"
    if baseline_value is None:
        return (
            f"the persistence baseline {baseline.model_id} has no {metric} recorded on this split, "
            "so no comparison against it is possible; it was not treated as a zero"
        )
    if direction == "lower":
        difference = baseline_value - winner_value
        verb = "beat" if difference > 0 else ("matched" if difference == 0 else "lost to")
    else:
        difference = winner_value - baseline_value
        verb = "beat" if difference > 0 else ("matched" if difference == 0 else "lost to")
    if difference == 0:
        return (
            f"the selected model exactly matched the persistence baseline on {metric} "
            f"({baseline_value:.6g}); with no difference on this criterion there is no evidence it "
            "earned the extra machinery"
        )
    return (
        f"the selected model {verb} the persistence baseline on {metric} by {abs(difference):.6g} "
        f"(baseline {baseline_value:.6g}, selected {winner_value:.6g}) on this split"
    )


def _synthetic_demo_of(candidates: Sequence[SelectionCandidate]) -> bool:
    if not candidates:
        return True
    # `any` rather than `all`: a mixed set is still not clean, and reporting it as
    # clean because one member happened to be measured would be the wrong default.
    return any(candidate.artifact.synthetic_demo for candidate in candidates)


def _data_status_of(candidates: Sequence[SelectionCandidate]) -> str:
    if not candidates:
        return "unknown"
    statuses = {candidate.artifact.data_status for candidate in candidates}
    return "mixed" if len(statuses) > 1 else next(iter(statuses))


def _disclaimer_of(candidates: Sequence[SelectionCandidate]) -> str | None:
    for candidate in sorted(candidates, key=lambda item: item.model_id):
        if candidate.artifact.disclaimer:
            return candidate.artifact.disclaimer
    return None


def direction_table() -> dict[str, str]:
    """The metric-direction table, re-exported so Phase 5 reads one place.

    Phase 5 delegates to Phase 4's `metric_direction` rather than keeping its own
    copy. Two direction tables in one repository is a coin flip on which one a
    future reader trusts, and this is precisely the question where being wrong is
    invisible in the output.
    """
    return dict(METRIC_DIRECTIONS)


__all__ = [
    "HIGHER_IS_BETTER",
    "LOWER_IS_BETTER",
    "METRIC_DIRECTIONS",
    "SelectionCandidate",
    "SelectionDecision",
    "SelectionError",
    "candidates_from_artifacts",
    "direction_table",
    "metric_direction",
    "select_model",
]