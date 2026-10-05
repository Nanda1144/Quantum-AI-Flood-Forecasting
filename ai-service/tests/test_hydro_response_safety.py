# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 7 leakage and safety tests: what this layer must be unable to do.

The decision tests in `test_hydro_response_decision.py` cover what Phase 7
decides. This module covers what it must be *incapable* of, which is the harder
half and the reason the phase exists as a boundary rather than a function.

The claims grouped here:

* **Temporal** - no future observation, no post-origin context, no clock.
* **Entity** - no evidence from one station attached to another.
* **Compositional** - no model retrained, selected, or refitted.
* **Invariance** - the inputs Phase 7 is not allowed to read cannot reach it.
* **Determinism** - identical input, identical serialised output.
* **Disclosure** - the synthetic-data disclaimer on every path.

Two of these are asserted structurally rather than behaviourally. `test_no_composite_score_field_exists`
and `test_the_decision_module_reads_no_clock_or_randomness` read the module source
and the dataclass fields. That is deliberate: a behavioural test would only prove
that the current inputs do not trigger the behaviour, and the whole point of these
claims is that a *future edit* must not be able to introduce it either.

No test here asserts a hydrological result.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import inspect
import json
import pathlib

import pytest

from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_context import (
    NOT_AVAILABLE,
    RESPONSE_AVAILABILITY,
    ExposureAvailability,
    FutureContextError,
    InvalidResponseContextError,
    ResponseContext,
)
from app.engines.hydro.response_decision import (
    DECISION_MONITOR,
    DECISION_WITHHELD,
    RESPONSE_STATES,
    ResponsePolicy,
    ResponseRule,
    decide_response,
    decide_response_safe,
)
from hydro_phase7_fixtures import (  # noqa: F401  - fixtures must be parameters
    context_unavailable_risk_result,
    context_with_exposure,
    demo_context,
    demo_policy,
    demo_response_policy,
    demo_rule,
    low_risk,
    medium_risk,
    risk_context_unavailable,
    risk_result_for_band,
    risk_withheld,
    run_result,
    served_forecast,
    shared_residual_values,
    station_a,
    station_b,
    unavailable_population,
)

_APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app" / "engines" / "hydro"
_DECISION_SOURCE = (_APP_ROOT / "response_decision.py").read_text(encoding="utf-8")
_CONTEXT_SOURCE = (_APP_ROOT / "response_context.py").read_text(encoding="utf-8")


def _code_identifiers(source: str) -> set[str]:
    """Every identifier and import that appears in *executable* code.

    Docstrings and comments are excluded, which is the whole point. A raw substring
    scan over module source fails these modules on their own prose: `response_decision`
    discusses elevation thresholds, QUBO, weighted composites and `exceedance_probability`
    precisely to record that it does none of them, and a test that cannot tell the
    difference between a name in a comment and a name in a call is not testing a
    boundary.

    What remains is the set of names the module can actually evaluate: attribute
    accesses, imported modules and symbols, local names, and definitions.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
            names.update(alias.asname for alias in node.names if alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.add(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and not isinstance(node.value, str):
            names.add(repr(node.value))
    return {name for name in names if name}


# --------------------------------------------------------------------------- #
# Temporal safety
# --------------------------------------------------------------------------- #


def test_decided_at_defaults_to_the_forecast_origin(demo_context):
    """No clock is read, so the decision instant is the forecast origin.

    Phase 6 made the same choice for `assessed_at`. If this read the wall clock,
    two decisions over identical evidence would differ, and an auditor comparing
    them would see a change that no input explains.
    """
    assert demo_context.decided_at is None
    assert demo_context.resolved_decided_at == demo_context.forecast_origin


def test_decided_at_never_precedes_the_forecast_origin(medium_risk):
    """A decision cannot be attributed to a moment before its forecast exists."""
    with pytest.raises(FutureContextError) as caught:
        ResponseContext.from_risk_result(
            medium_risk,
            decided_at=medium_risk.forecast.origin_instant - dt.timedelta(hours=1),
        )

    assert "precedes the forecast origin" in str(caught.value)


def test_an_explicit_earlier_decided_at_is_refused_not_ignored(medium_risk):
    """Silently clamping to the origin would hide the caller's mistake."""
    with pytest.raises(FutureContextError):
        ResponseContext.from_risk_result(
            medium_risk, decided_at=dt.datetime(1999, 1, 1, tzinfo=dt.timezone.utc)
        )


def test_a_later_explicit_decided_at_is_accepted(demo_policy, medium_risk):
    """Stating a later instant explicitly is allowed; only reading one is not."""
    later = medium_risk.forecast.origin_instant + dt.timedelta(hours=2)

    context = ResponseContext.from_risk_result(medium_risk, decided_at=later)
    decision = decide_response(context, policy=demo_policy)

    assert context.resolved_decided_at == later
    assert decision.decided_at == later
    assert decision.forecast_origin == medium_risk.forecast.origin_instant


def test_a_naive_decided_at_is_refused(medium_risk):
    """An instant with no offset cannot be compared against an origin that has one."""
    naive = medium_risk.forecast.origin_instant.replace(tzinfo=None)

    with pytest.raises(FutureContextError) as caught:
        ResponseContext.from_risk_result(medium_risk, decided_at=naive)

    assert "timezone-aware" in str(caught.value)


def test_a_risk_result_without_a_forecast_is_refused(demo_policy):
    """No origin means nothing can be checked against temporal leakage.

    `RiskResult` validates its own forecast, so a result with no forecast cannot be
    built through its constructor at all - Phase 6 refuses it first. This stand-in
    reaches Phase 7's own guard, which is what a caller holding an older or
    hand-assembled record would meet.
    """
    from app.engines.hydro.response_context import InvalidRiskResultError

    class _NoForecast:
        """A `RiskResult`-shaped record with nothing to date the decision against."""

        forecast = None
        risk_result_id = "navya-phase6-risk/undated"

    stand_in = _NoForecast()

    with pytest.raises(InvalidRiskResultError) as caught:
        ResponseContext.from_risk_result(stand_in)

    assert "origin instant" in str(caught.value)
    assert decide_response_safe(stand_in, policy=demo_policy).decision == DECISION_WITHHELD


def test_phase7_cannot_consume_a_post_origin_signal(
    run_result, served_forecast, shared_residual_values, medium_risk
):
    """A signal observed after the forecast origin must not reach the decision.

    Phase 6 refuses such a signal in its own contract. The claim tested here is
    stronger: there is no route by which post-origin information could end up
    inside a `ResponseContext`, because Phase 7 copies only what Phase 6 already
    evaluated and re-reads no signal value at all.
    """
    from app.engines.hydro.forecast_risk import assess_risk
    from hydro_phase7_fixtures import future_context, risk_config

    with pytest.raises(FutureContextError) as caught:
        assess_risk(
            served_forecast,
            config=risk_config(3.5),
            context=future_context(medium_risk.forecast.entity, run_result.origin),
            residuals=list(shared_residual_values),
        )

    assert "after the forecast origin" in str(caught.value)

    context = ResponseContext.from_risk_result(medium_risk)
    decision = decide_response(context, policy=demo_response_policy())

    assert decision.decided_at == context.forecast_origin
    assert all(
        item.value is None for item in decision.evidence if item.name.startswith("phase6_signal:")
    )


def test_a_future_gis_state_cannot_be_supplied_as_available_context(demo_policy, medium_risk):
    """GIS remains a boundary, so a future spatial state has no field to enter."""
    context = ResponseContext.from_risk_result(medium_risk)

    assert not context.gis_available
    assert context.gis_reason == NOT_AVAILABLE
    for record in context.exposure:
        assert record.kind in {"population", "infrastructure"}
        assert "observed_at" not in record.to_dict()


def test_a_future_population_state_cannot_be_supplied(demo_policy, medium_risk):
    """Exposure availability has no timestamp field, so it cannot be dated.

    This is a real limit and it is stated rather than papered over: Phase 7 records
    *whether* exposure was available, not *when*. A caller who needs freshness must
    establish it upstream and express it as `stale`, because this boundary has no
    field in which an observation time could be compared against the origin.
    """
    record = ExposureAvailability(
        kind="population", availability="valid", source="a fixture", reason=""
    )

    assert "observed_at" not in record.to_dict()
    assert "as_of" not in record.to_dict()
    context = context_with_exposure(medium_risk, record)
    decision = decide_response(context, policy=demo_policy)
    baseline = decide_response(medium_risk, policy=demo_policy)
    assert decision.decision == baseline.decision


def test_a_future_flood_label_cannot_be_invented_by_phase7(demo_policy, medium_risk):
    """Historical context is carried from Phase 6, never assembled here."""
    context = ResponseContext.from_risk_result(medium_risk)

    assert context.historical_available is False
    assert context.historical_event_count == 0
    assert "events" not in context.to_dict()
    assert "none may be invented" in context.historical_reason
    decision = decide_response(context, policy=demo_policy)
    assert "not evidence that this location has never flooded" in decision.explain()


def test_no_module_in_the_phase7_boundary_reads_a_clock():
    """A source-level check, so a later edit cannot quietly introduce one."""
    for name, source in (("response_decision", _DECISION_SOURCE), ("response_context", _CONTEXT_SOURCE)):
        for forbidden in ("datetime.now", "utcnow", "time.time", "monotonic"):
            assert forbidden not in source, f"{name} references {forbidden}"


def test_no_module_in_the_phase7_boundary_uses_randomness():
    for name, source in (("response_decision", _DECISION_SOURCE), ("response_context", _CONTEXT_SOURCE)):
        for forbidden in ("uuid4", "random.", "secrets.", "randint", "choice("):
            assert forbidden not in source, f"{name} references {forbidden}"


def test_no_module_in_the_phase7_boundary_imports_a_clock_or_uuid():
    for module in ("response_decision", "response_context"):
        tree = ast.parse(pathlib.Path(_APP_ROOT / f"{module}.py").read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "random" not in imported
        assert "uuid" not in imported
        assert "secrets" not in imported
        assert "time" not in imported


# --------------------------------------------------------------------------- #
# Entity safety
# --------------------------------------------------------------------------- #


def test_a_context_claiming_a_different_entity_is_refused(medium_risk):
    """Station A's evidence must not be labelled Station B.

    Phase 7 has no station registry, no mapping table and no nearest-station rule,
    so two different entity names are a refusal rather than something to reconcile.
    """
    with pytest.raises(FutureContextError.__mro__[1]) as caught:
        ResponseContext.from_risk_result(medium_risk, entity="SYNTHETIC-STATION-9999")

    assert "SYNTHETIC-STATION-9999" in str(caught.value)
    assert medium_risk.forecast.entity in str(caught.value)


def test_the_entity_refusal_is_the_phase6_error_class(medium_risk):
    """One taxonomy for one rule, rather than a second entity-mismatch error."""
    from app.engines.hydro.risk_context import EntityMismatchError

    with pytest.raises(EntityMismatchError) as caught:
        ResponseContext.from_risk_result(medium_risk, entity="ANYWHERE-ELSE")

    assert caught.value.reason == "entity_mismatch"


def test_a_matching_entity_is_accepted(medium_risk):
    context = ResponseContext.from_risk_result(medium_risk, entity=medium_risk.forecast.entity)

    assert context.entity == medium_risk.forecast.entity


def test_an_empty_entity_is_refused(medium_risk):
    with pytest.raises(Exception) as caught:
        ResponseContext.from_risk_result(medium_risk, entity="   ")

    assert "not the entity this risk result describes" in str(caught.value)


def test_a_decision_cannot_claim_an_entity_other_than_its_risk_result(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.entity == medium_risk.forecast.entity
    assert decision.provenance["entity"] == medium_risk.forecast.entity
    assert decision.risk_result_id == medium_risk.risk_result_id


def test_two_stations_produce_independent_decisions(
    run_result, served_forecast, shared_residual_values, station_a, station_b
):
    """No cross-station mixing: each decision names only its own station.

    Station B exists in the same dataset and the same Phase 5 run, so its name is a
    realistic thing for a mixing bug to leak. A decision built from Station A's risk
    result must not mention it anywhere.
    """
    assert station_a != station_b

    risk = risk_result_for_band(run_result, served_forecast, shared_residual_values, "HIGH")
    decision = decide_response(risk, policy=demo_response_policy())

    serialised = json.dumps(decision.to_dict())
    assert station_a in serialised
    assert station_b not in serialised


def test_no_geographic_inference_is_available():
    """`ResponseContext` has no distance, elevation or proximity field to reason over."""
    fields = {f.name for f in dataclasses.fields(ResponseContext)}

    for spatial in ("elevation_m", "river_distance_m", "distance_km", "nearest_station"):
        assert spatial not in fields
    assert "gis_available" in fields
    assert "gis_reason" in fields


# --------------------------------------------------------------------------- #
# No second risk engine
# --------------------------------------------------------------------------- #


def test_the_decision_module_imports_no_risk_mathematics():
    """Phase 6 owns the arithmetic; Phase 7 must not even import it.

    `classify_risk_level`, `exceedance_probability` and the `risk` module itself are
    absent from the imports, so a second implementation of either cannot be added
    without deleting an import line. Matched on the last dotted component, so
    `app.engines.hydro.risk_context` is a different module from `...hydro.risk` and
    the check says what it means.
    """

    def tail(name: str) -> str:
        return name.rsplit(".", 1)[-1]

    tree = ast.parse(_DECISION_SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    for forbidden in ("exceedance_probability", "classify_risk_level", "risk", "residual_sigma"):
        assert forbidden not in {tail(name) for name in imported}, (
            f"response_decision imports {forbidden}"
        )


def test_the_decision_module_does_not_reference_phase6_arithmetic():
    """No re-derivation of probability, sigma, or band edges in executable code."""
    code = _code_identifiers(_DECISION_SOURCE)

    for forbidden in (
        "exceedance_probability",
        "classify_risk_level",
        "band_edges",
        "erf",
        "norm",
    ):
        assert forbidden not in code, f"response_decision evaluates {forbidden}"


def test_the_decision_module_does_no_model_work():
    """Phase 5 owns selection, serving and artifacts. Phase 7 touches none of them."""
    code = _code_identifiers(_DECISION_SOURCE)

    for forbidden in (
        "train",
        "fit",
        "predict",
        "estimators",
        "select_model",
        "ArtifactStore",
        "ForecastInference",
        "pickle",
        "joblib",
        "unpickle",
        "np",
        "numpy",
        "pd",
        "pandas",
        "sklearn",
    ):
        assert forbidden not in code, f"response_decision evaluates {forbidden}"


def test_the_decision_module_calls_no_quantum_or_optimisation_code():
    """The optimisation boundary is on the far side of this one."""
    for source in (_DECISION_SOURCE, _CONTEXT_SOURCE):
        code = _code_identifiers(source)
        for forbidden in (
            "quantum",
            "QUBO",
            "qiskit",
            "dwave",
            "optimize",
            "optimizer",
            "sensor_placement",
            "cplex",
            "gurobi",
        ):
            assert forbidden not in code, f"response module evaluates {forbidden}"


def test_the_decision_module_implements_no_gis_calculation():
    code = _code_identifiers(_DECISION_SOURCE)

    for forbidden in (
        "elevation",
        "elevation_m",
        "river_distance",
        "river_distance_m",
        "floodplain",
        "shapefile",
        "geopandas",
        "raster",
        "shapely",
        "pyproj",
        "gdal",
    ):
        assert forbidden not in code, f"response_decision evaluates {forbidden}"


def test_the_decision_module_makes_no_network_call():
    for source in (_DECISION_SOURCE, _CONTEXT_SOURCE):
        code = _code_identifiers(source)
        for forbidden in (
            "requests",
            "httpx",
            "urllib",
            "aiohttp",
            "socket",
            "http",
            "subprocess",
        ):
            assert forbidden not in code


def test_the_decision_module_defines_no_service_app():
    """Phase 7 is a domain layer. A FastAPI app here would be scope creep."""
    tree = ast.parse(_DECISION_SOURCE)
    code = _code_identifiers(_DECISION_SOURCE)

    for forbidden in ("fastapi", "APIRouter", "uvicorn", "pydantic", "BaseModel", "async"):
        assert forbidden not in code
    assert not any(
        isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree)
    ), "response_decision defines an async function; it performs no I/O"


def test_risk_level_is_read_not_recomputed(medium_risk, demo_policy):
    """The level in the decision is byte-identical to the one Phase 6 assigned."""
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.risk_level == medium_risk.risk_level
    assert decision.risk_score == medium_risk.risk_score
    assert decision.risk_score_type == medium_risk.risk_score_type
    assert "did not recompute" in decision.explain()


def test_the_score_type_is_never_relabelled_as_a_flood_probability(medium_risk, demo_policy):
    """`probability_of_flood` is not a claim this repository supports."""
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.risk_score_type == medium_risk.risk_score_type
    assert decision.risk_score_type != "probability_of_flood"
    serialised = json.dumps(decision.to_dict())
    assert "probability_of_flood" not in serialised
    assert "official" not in serialised.lower() or "no official meaning" in serialised


# --------------------------------------------------------------------------- #
# No composite score
# --------------------------------------------------------------------------- #


def test_no_composite_score_field_exists():
    """Structural, so a future edit cannot add one without failing here first."""
    from app.engines.hydro.response_decision import ResponseDecision

    fields = set(ResponseDecision.__dataclass_fields__)
    for forbidden in (
        "response_score",
        "severity_score",
        "danger_score",
        "community_score",
        "composite_score",
        "final_risk_score",
        "weighted_score",
        "priority_score",
    ):
        assert forbidden not in fields


def test_the_decision_module_computes_no_weighted_sum():
    """No weights exist to combine with."""
    code = _code_identifiers(_DECISION_SOURCE)

    for forbidden in (
        "population_weight",
        "infrastructure_weight",
        "weight",
        "weighted",
        "severity",
    ):
        assert forbidden not in code, f"response_decision evaluates {forbidden}"

    tree = ast.parse(_DECISION_SOURCE)
    assert not any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
        for node in ast.walk(tree)
    ), "response_decision multiplies two things together; it has no weights to apply"


def test_the_risk_score_is_never_combined_with_anything(medium_risk, demo_policy):
    """The score is carried and explicitly marked as not deciding anything."""
    decision = decide_response(medium_risk, policy=demo_policy)

    score = next(item for item in decision.evidence if item.name == "risk_score")
    assert score.value == medium_risk.risk_score
    assert score.contributed is False
    assert "not the category" in score.reason


# --------------------------------------------------------------------------- #
# Missing is not zero; unavailable is not safe
# --------------------------------------------------------------------------- #


def test_no_decision_field_defaults_to_zero(risk_withheld, demo_policy):
    """Every numeric-ish field on a withheld decision is `None`, never `0`."""
    decision = decide_response(risk_withheld, policy=demo_policy)

    assert decision.risk_score is None
    assert decision.risk_level is None
    assert decision.priority is None
    assert decision.evidence == ()


def test_unavailable_population_is_not_reported_as_zero_population(medium_risk, demo_policy):
    context = context_with_exposure(medium_risk, unavailable_population())

    decision = decide_response(context, policy=demo_policy)

    record = next(r for r in decision.unavailable_context if r.kind == "population")
    assert record.availability == "unavailable"
    assert "value" not in record.to_dict()

    # No field in the record holds a number at all. `ensure_ascii=False` matters
    # here: the default escaping renders the em dash in the repository's marker as
    # a `\u2014` escape, whose digits would satisfy a plain search for "0" and the
    # test would end up reading its own punctuation.
    assert not any(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in record.to_dict().values()
    )
    serialised = json.dumps(record.to_dict(), ensure_ascii=False)
    assert NOT_AVAILABLE in serialised
    assert "0" not in serialised


def test_a_missing_threshold_does_not_become_a_low_risk(risk_withheld, demo_policy):
    """The state a caller reaches in this repository today.

    `RiskPolicy()` has no threshold, Phase 6 withholds, and Phase 7 withholds. It
    does not resolve the absence to `MONITOR`, which would read as "low risk" - the
    single most dangerous default available here.
    """
    decision = decide_response(risk_withheld, policy=demo_policy)

    assert decision.decision == DECISION_WITHHELD
    assert decision.decision != DECISION_MONITOR
    assert "no response category is recommended" in decision.explain()
    assert "not the same as recommending that nothing be done" in decision.explain()


def test_missing_history_is_not_read_as_no_history(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert "historical flood context was unavailable" in decision.explain()
    assert "never flooded" in decision.explain()
    contributing = [item.name for item in decision.evidence_read]
    assert "historical_context" not in contributing


def test_missing_gis_is_not_read_as_safe_geography(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert "spatial context was unavailable" in decision.explain()
    assert "no elevation, river-distance, floodplain or accessibility conclusion" in (
        decision.explain()
    )
    assert "gis_context" not in [item.name for item in decision.evidence_read]


def test_an_unavailable_signal_never_appears_as_a_contributor(demo_policy, run_result, served_forecast, shared_residual_values):
    """Phase 6's unusable signals stay unusable on this side of the boundary."""
    from hydro_phase7_fixtures import empty_context

    risk = context_unavailable_risk_result(run_result, served_forecast, shared_residual_values)
    decision = decide_response(risk, policy=demo_policy)

    assert decision.decision == DECISION_WITHHELD
    assert decision.evidence == ()
    assert "a decision made from nothing is recorded as such" in decision.explain()


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_identical_input_produces_identical_output(medium_risk, demo_policy):
    first = decide_response(medium_risk, policy=demo_policy)
    second = decide_response(medium_risk, policy=demo_policy)

    assert first.to_dict() == second.to_dict()
    assert first.decision_id == second.decision_id


def test_identical_input_produces_identical_output_with_a_rule(medium_risk, demo_policy):
    rule = demo_rule()

    first = decide_response(medium_risk, policy=demo_policy, rules=[rule])
    second = decide_response(medium_risk, policy=demo_policy, rules=[rule])

    assert first.to_dict() == second.to_dict()


def test_repeated_serialisation_is_stable(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    payloads = [json.dumps(decision.to_dict(), sort_keys=True) for _ in range(5)]

    assert len(set(payloads)) == 1


def test_a_list_rather_than_a_tuple_of_rules_gives_the_same_answer(medium_risk, demo_policy):
    """Rule order is normalised by id, so input container shape cannot reach output."""
    rule = demo_rule()

    as_tuple = decide_response(medium_risk, policy=demo_policy, rules=(rule,))
    as_list = decide_response(medium_risk, policy=demo_policy, rules=[rule])

    assert as_tuple.to_dict() == as_list.to_dict()


def test_determinism_survives_a_fresh_context_build(medium_risk, demo_policy):
    """Two projections of the same risk result agree completely."""
    one = decide_response(ResponseContext.from_risk_result(medium_risk), policy=demo_policy)
    two = decide_response(ResponseContext.from_risk_result(medium_risk), policy=demo_policy)

    assert one.to_dict() == two.to_dict()
    assert one.decision_id == two.decision_id


def test_the_context_digest_is_stable(medium_risk):
    one = ResponseContext.from_risk_result(medium_risk).digest
    two = ResponseContext.from_risk_result(medium_risk).digest

    assert one == two
    assert len(one) == 12


def test_the_context_digest_changes_with_the_evidence(low_risk, medium_risk):
    """It is an integrity handle, so a different result must change it."""
    assert ResponseContext.from_risk_result(low_risk).digest != ResponseContext.from_risk_result(
        medium_risk
    ).digest


def test_the_decision_is_a_frozen_dataclass(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.decision = DECISION_MONITOR  # type: ignore[misc]


def test_the_policy_is_a_frozen_dataclass(demo_policy):
    with pytest.raises(dataclasses.FrozenInstanceError):
        demo_policy.policy_status = "approved"  # type: ignore[misc]


def test_the_policy_mapping_is_not_mutable_through_the_object(demo_policy):
    """Frozen is not deep; the mapping is wrapped so it cannot be edited either."""
    assert isinstance(demo_policy.risk_level_response, type(__import__("types").MappingProxyType({})))
    with pytest.raises(TypeError):
        demo_policy.risk_level_response["LOW"] = "REVIEW_WARNING"  # type: ignore[index]


def test_the_exposure_tuple_is_not_mutable(demo_context):
    assert isinstance(demo_context.exposure, tuple)


# --------------------------------------------------------------------------- #
# Synthetic-data disclosure
# --------------------------------------------------------------------------- #


def test_the_disclaimer_survives_on_every_recommendation(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert SYNTHETIC_DATA_DISCLAIMER in decision.explanation
    assert SYNTHETIC_DATA_DISCLAIMER in json.dumps(decision.to_dict())


def test_the_disclaimer_survives_on_every_withheld_path(
    risk_withheld, risk_context_unavailable, demo_policy
):
    for risk in (risk_withheld, risk_context_unavailable):
        decision = decide_response(risk, policy=demo_policy)
        assert SYNTHETIC_DATA_DISCLAIMER in decision.explanation


def test_the_disclaimer_survives_the_safe_wrapper(demo_policy):
    decision = decide_response_safe(None, policy=demo_policy)

    assert SYNTHETIC_DATA_DISCLAIMER in decision.explanation
    assert decision.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_the_disclaimer_survives_response_from_error(demo_policy):
    from app.engines.hydro.response_decision import response_from_error

    decision = response_from_error(ValueError("x"))

    assert SYNTHETIC_DATA_DISCLAIMER in decision.explanation


def test_the_disclaimer_is_in_the_context_and_the_decision_serialisations(medium_risk, demo_policy):
    context = ResponseContext.from_risk_result(medium_risk)
    decision = decide_response(context, policy=demo_policy)

    assert context.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert context.to_dict()["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER
    assert decision.to_dict()["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER
    assert decision.provenance["response_context_disclaimer"] == SYNTHETIC_DATA_DISCLAIMER


def test_synthetic_status_is_carried_not_derived(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.synthetic_demo is medium_risk.synthetic_demo
    assert decision.data_status == medium_risk.data_status
    assert decision.synthetic_demo is True


def test_no_decision_claims_production_or_operational_status(medium_risk, demo_policy):
    """Both flags are false on the object and in the serialisation.

    Asserted as flags, not as a substring scan. The explanation necessarily
    contains the words "evacuation", "emergency" and "government" - it has to, in
    order to state that this layer does none of those things - so a text scan here
    could only ever be testing the disclaimer. What has to be checked is the flags
    themselves, on the object and through `to_dict`, and the fact that the decision
    is drawn from the closed state vocabulary.
    """
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.production_ready_claimed is False
    assert decision.operational_authority is False

    payload = decision.to_dict()
    assert payload["production_ready_claimed"] is False
    assert payload["operational_authority"] is False
    assert payload["provenance"]["production_ready_claimed"] is False
    assert payload["provenance"]["operational_authority"] is False
    assert payload["response_policy"]["operational_authority"] is False
    assert payload["decision"] in RESPONSE_STATES

    # No reviewer is recorded, because no review happened.
    assert payload["response_policy"]["reviewed_by"] is None
    assert payload["response_policy"]["reviewed_at"] is None
    assert payload["response_policy"]["policy_status"] == "pending"


def test_the_policy_cannot_be_marked_approved_by_phase7(medium_risk, demo_policy):
    """`policy_status` is recorded verbatim; Phase 7 never sets it.

    There is no code path in this phase that writes `'approved'`. A caller may pass
    such a string, and it is recorded as they supplied it - but the decision carries
    `operational_authority=False` regardless, because this repository cannot grant
    authority no matter what a policy file claims.
    """
    claiming = demo_response_policy(status="approved")

    decision = decide_response(medium_risk, policy=claiming)

    assert decision.response_policy["policy_status"] == "approved"
    assert decision.operational_authority is False
    assert decision.production_ready_claimed is False
    assert "no operational or government authority" in decision.explain()


def test_a_naive_review_timestamp_is_refused(demo_policy):
    with pytest.raises(FutureContextError) as caught:
        ResponsePolicy(
            risk_level_response={"LOW": "MONITOR"},
            policy_source="x",
            reviewed_at=dt.datetime(2024, 1, 1),
        )

    assert "timezone-aware" in str(caught.value)


def test_an_aware_review_timestamp_is_accepted():
    policy = ResponsePolicy(
        risk_level_response={"LOW": "MONITOR"},
        policy_source="x",
        reviewed_at=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
    )

    assert policy.reviewed_at is not None
    assert policy.to_dict()["reviewed_at"] == "2024-01-01T00:00:00+00:00"


def test_a_non_datetime_review_timestamp_is_refused():
    with pytest.raises(Exception) as caught:
        ResponsePolicy(
            risk_level_response={"LOW": "MONITOR"}, policy_source="x", reviewed_at="yesterday"
        )

    assert "datetime" in str(caught.value)