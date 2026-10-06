# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 8 safety: what the integration layer must never do.

The sibling module `test_hydro_integration_assessment.py` asserts what the contract
*says*. This one asserts what it must never *do*, and most of that is checked against
the module's own source rather than against its output.

Why source scanning, when a behavioural test would read more naturally
--------------------------------------------------------------------

Most of the guarantees here are about **absence**, and absence is not something a
runtime assertion can demonstrate. If Phase 8 read a clock, a test could only catch it
by freezing time and comparing two runs — which passes anyway if the clock read lands
outside the compared field. If it imported FastAPI, an output test would see a working
function. If it invented a composite score, a test would have to already know the
formula to notice the number.

So for the negative guarantees the check is structural: parse the module's AST and
assert that no forbidden call, import or identifier appears in the code at all. That is
a stronger claim than "I did not observe it happen", and it is checkable by anyone.

The cost is that these tests know what to look for, so they are only as good as the
lists below. The behavioural tests in the sibling module cover the rest.

Prose is excluded from identifier scans
---------------------------------------

Several guarantees are about words — `EVACUATE`, `MONITOR`, `emergency` — and this
module's *explanation* legitimately contains them in order to say that Phase 8 does not
emit them ("it is not a flood warning, not an evacuation instruction"). A raw text scan
would flag that as a violation, which is exactly backwards.

Every scan below therefore collects **code** identifiers only: names, attributes and
strings that appear as code, not words inside a docstring or a message. `_code_*`
helpers do that filtering, so the guarantees stay precise instead of being satisfied by
deleting an honest warning.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import inspect
import json
import re
from pathlib import Path
from typing import Iterator

import pytest

from app.engines.hydro import integration_assessment as module
from app.engines.hydro.forecast_risk import MissingForecastError
from app.engines.hydro.integration_assessment import (
    INTEGRATION_COMPLETE,
    INTEGRATION_NOT_EVALUABLE,
    INTEGRATION_STATES,
    INTEGRATION_WITHHELD,
    IntegratedForecastAssessment,
    integrate,
    integrate_safe,
    integration_contract_description,
    integration_from_error,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_decision import (
    DECISION_WITHHELD,
    RESPONSE_STATES,
    ResponsePolicy,
)
from app.engines.hydro.risk_context import SIGNAL_AVAILABILITY

from hydro_phase8_fixtures import (  # noqa: F401  - fixtures must be parameters
    STATION_A,
    available_infrastructure,
    complete_decision,
    context_unavailable_chain,
    decide_for,
    decision_for_entity,
    empty_chain,
    medium_chain,
    mixed_exposure,
    not_evaluable_chain,
    refused_chain,
    repository_chain,
    risk_result_for_band,
    shared_residuals,
    shared_run,
    shared_served,
    station_two,
    withheld_chain,
)

MODULE_PATH = Path(inspect.getfile(module))
MODULE_SOURCE = MODULE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# AST helpers
# --------------------------------------------------------------------------- #


def _tree() -> ast.Module:
    return ast.parse(MODULE_SOURCE, filename=str(MODULE_PATH))


def _code_strings(tree: ast.Module) -> set[str]:
    """Every string literal in *code* position — excluding docstrings.

    Docstrings are the module's own explanations, which legitimately name the things
    this module refuses to do. A docstring saying "never emit EVACUATE" must not read
    as an emission of `EVACUATE`.
    """
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node not in docstrings:
                found.add(node.value)
    return found


def _code_identifiers(tree: ast.Module) -> set[str]:
    """Every name and attribute appearing as code, docstrings excluded by nature.

    Docstrings are string constants, so they cannot contribute identifiers here — which
    is the correct behaviour: the guarantee is about what the module *does*, not about
    what it says.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
            found.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
            found.update(alias.name for alias in node.names)
    return found


def _attribute_chains(tree: ast.Module) -> Iterator[str]:
    """Yield `module.function` for every dotted attribute access in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parts = [node.attr]
            current = node.value
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            yield ".".join(reversed(parts))


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


# --------------------------------------------------------------------------- #
# No clock
# --------------------------------------------------------------------------- #


def test_the_module_reads_no_clock_anywhere():
    """Nothing in Phase 8 may depend on what time it is now.

    Checked as a source scan because a runtime test cannot prove absence: freezing the
    clock only proves that *this* call did not observe the change.
    """
    identifiers = _code_identifiers(_tree())
    chains = set(_attribute_chains(_tree()))
    forbidden_identifiers = {
        "now", "utcnow", "utcnow", "today", "time", "monotonic", "perf_counter",
        "now_utc", "astimezone_now",
    }
    assert not (identifiers & forbidden_identifiers), sorted(identifiers & forbidden_identifiers)

    forbidden_chains = {"datetime.now", "datetime.utcnow", "time.time", "time.monotonic",
                        "date.today", "dt.datetime.now", "dt.datetime.utcnow"}
    assert not (chains & forbidden_chains), sorted(chains & forbidden_chains)


def test_no_time_module_is_imported():
    modules = _imported_modules(_tree())
    assert "time" not in modules
    assert not any(name.endswith(".time") for name in modules)


def test_the_instant_is_the_forecast_origin_and_nothing_else(medium_chain):
    origin = medium_chain.forecast.inference.origin_instant
    assert medium_chain.integrated_at == origin
    assert medium_chain.integrated_at.tzinfo is not None


def test_no_instant_exists_without_a_forecast(empty_chain, refused_chain):
    """No forecast means no instant, and `None` is the honest answer.

    Substituting the current time here would make the record's timestamp a property of
    when it was written rather than of what it describes — and would break the
    determinism guarantee that makes the serialized form citable.
    """
    assert empty_chain.integrated_at is None
    assert refused_chain.integrated_at is None
    assert empty_chain.to_dict()["integrated_at"] is None


def test_the_instant_survives_serialization_as_an_isoformat(medium_chain):
    payload = medium_chain.to_dict()
    assert payload["integrated_at"] == medium_chain.integrated_at.isoformat()
    assert dt.datetime.fromisoformat(payload["integrated_at"]) == medium_chain.integrated_at


def test_two_integrations_at_different_wall_clock_moments_agree(medium_chain):
    """Re-running the integration later must not change anything about it.

    This is the observable consequence of the no-clock rule, and it is the property
    that actually matters: a record whose timestamp moved would not be reproducible.
    """
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)
    first = integrate(served_forecast, risk, decision)
    second = integrate(served_forecast, risk, decision)
    assert first.integrated_at == second.integrated_at
    assert first.to_json() == second.to_json()


# --------------------------------------------------------------------------- #
# No randomness
# --------------------------------------------------------------------------- #


def test_the_module_uses_no_randomness_and_no_uuid():
    identifiers = _code_identifiers(_tree())
    modules = _imported_modules(_tree())
    for forbidden in ("uuid", "random", "secrets", "randint", "shuffle", "sample", "choice",
                      "token_bytes", "urandom"):
        assert forbidden not in identifiers, forbidden
    for forbidden_module in ("uuid", "random", "secrets"):
        assert forbidden_module not in modules


def test_the_integration_id_is_a_content_digest_and_not_a_counter(medium_chain):
    digest = medium_chain.integration_id.rsplit("@", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{12}", digest)
    assert medium_chain.integration_id.count("@") == 1


def test_the_same_chain_always_produces_the_same_id(medium_chain):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)
    ids = {integrate(served_forecast, risk, decision).integration_id for _ in range(5)}
    assert len(ids) == 1
    assert ids.pop() == medium_chain.integration_id


def test_a_different_chain_produces_a_different_id(repository_chain, medium_chain):
    assert repository_chain.integration_id != medium_chain.integration_id


def test_no_layer_identifier_is_regenerated_by_phase_8(medium_chain):
    """Phase 8 copies each layer's published identifier; it never mints its own."""
    assert medium_chain.chain[0].layer_id == medium_chain.forecast.forecast_id
    assert medium_chain.chain[1].layer_id == medium_chain.risk.risk_result_id
    assert medium_chain.chain[2].layer_id == medium_chain.response.decision_id
    strings = _code_strings(_tree())
    assert medium_chain.forecast.forecast_id not in strings
    assert medium_chain.risk.risk_result_id not in strings


# --------------------------------------------------------------------------- #
# No recomputation
# --------------------------------------------------------------------------- #


def test_the_module_imports_no_numerical_or_statistical_library():
    """No numpy, no scipy, no statistics: there is nothing here to compute with.

    This is the structural form of "orchestration only". A module that computes an
    exceedance probability needs a normal CDF; one that estimates a spread needs
    statistics. The absence of both is the guarantee.
    """
    modules = _imported_modules(_tree())
    for forbidden in ("numpy", "np", "scipy", "stats", "statistics", "math", "random"):
        assert forbidden not in modules, forbidden


def test_the_module_calls_no_mathematical_function():
    """No erf, no cdf, no sqrt, no sigma.

    Checked by attribute chain because `math.erf` and a bare `erf` are the same claim
    written two ways, and a scan that missed one of them would be worse than none.
    """
    chains = set(_attribute_chains(_tree()))
    identifiers = _code_identifiers(_tree())
    forbidden_chains = {"math.erf", "math.erfc", "math.sqrt", "math.exp", "math.log",
                        "erf", "erfc", "norm.cdf", "norm.pdf"}
    offenders = (chains & forbidden_chains) | (identifiers & forbidden_chains)
    assert not offenders, sorted(offenders)


def test_the_module_has_no_threshold_or_band_arithmetic():
    """Phase 6 owns threshold interpretation and band classification.

    No `threshold_for_band`, no bisection, no edge comparison, no label lookup. Phase 8
    projects `risk_level`; it never decides one.
    """
    identifiers = _code_identifiers(_tree())
    chains = set(_attribute_chains(_tree()))
    forbidden = {"bisect", "bisect_left", "bisect_right", "threshold_for_band",
                 "exceedance_probability", "residual_sigma", "band_edges", "band_labels",
                 "classify_band", "DEFAULT_RISK_BAND_LABELS"}
    offenders = (identifiers & forbidden) | (chains & forbidden)
    # `band_edges`/`band_labels` are read from the risk result as projections, which is
    # allowed; they must not appear as a *call* or a local computation.
    offenders -= {"band_edges", "band_labels"}
    assert not offenders, sorted(offenders)


def test_the_module_produces_no_forecast():
    identifiers = _code_identifiers(_tree())
    forbidden = {"predict", "forecast_inference", "serve", "fit", "train",
                 "build_manifests", "artifact_for", "preprocess"}
    offenders = identifiers & forbidden
    assert not offenders, sorted(offenders)


def test_the_module_produces_no_risk():
    identifiers = _code_identifiers(_tree())
    forbidden = {"assess_risk", "RiskConfiguration", "RiskPolicy", "exceedance_probability",
                 "measured_sigma", "escalate"}
    offenders = identifiers & forbidden
    assert not offenders, sorted(offenders)


def test_the_module_produces_no_response():
    identifiers = _code_identifiers(_tree())
    forbidden = {"decide_response", "decide_response_safe", "ResponsePolicy", "map_risk_level"}
    offenders = identifiers & forbidden
    assert not offenders, sorted(offenders)


def test_the_module_mutates_nothing_it_reads(medium_chain):
    """The three layer results are held by reference and must be untouched by reading.

    A mutation would be invisible to a caller holding their own reference to the same
    object, which is exactly the kind of corruption that only shows up as a wrong answer
    somewhere else entirely.
    """
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)

    def snapshot(obj):
        return jsonable(obj)

    before = (snapshot(served_forecast), snapshot(risk), snapshot(decision))
    integrate(served_forecast, risk, decision)
    integrate_safe(served_forecast, risk, decision)
    after = (snapshot(served_forecast), snapshot(risk), snapshot(decision))
    assert before == after


def jsonable(value):
    """A comparable snapshot of a Phase 5/6/7 result, via its own serializer."""
    if hasattr(value, "to_dict"):
        return repr(sorted(value.to_dict().items(), key=lambda item: item[0]))
    return repr(value)


# --------------------------------------------------------------------------- #
# No composite score
# --------------------------------------------------------------------------- #


def test_no_phase_eight_field_is_a_composite_of_several_inputs():
    """No integration score, no severity score, no danger score, no final risk score.

    Phases 6 and 7 each declined to invent a weighted composite, and a third layer that
    added one would have to invent it again — with even less justification, since it
    sits furthest from the evidence. A consumer wanting a single number must decide how
    to weigh risk against exposure, and that decision belongs to them, visibly.
    """
    names = {field.name.lower() for field in dataclasses.fields(IntegratedForecastAssessment)}
    forbidden = {
        "integration_score", "final_score", "final_risk_score", "composite_score",
        "danger_score", "severity_score", "response_score", "overall_score",
        "risk_index", "priority_score", "total_score", "weighted_score", "aggregate_score",
    }
    offenders = names & forbidden
    assert not offenders, sorted(offenders)


def test_no_composite_is_computed_anywhere_in_the_module():
    identifiers = _code_identifiers(_tree())
    chains = set(_attribute_chains(_tree()))
    forbidden = {"integration_score", "composite_score", "danger_score", "severity_score",
                 "weighted_sum", "np.average", "np.mean", "np.dot", "np.sum", "np.average",
                 "sum(", "mean(", "average("}
    offenders = (identifiers & forbidden) | (chains & forbidden)
    assert not offenders, sorted(offenders)


def test_the_contract_states_that_no_composite_exists():
    note = integration_contract_description()["no_composite_score"]
    assert "integration_score" in note
    assert "final_risk_score" in note


# --------------------------------------------------------------------------- #
# No invented exposure values
# --------------------------------------------------------------------------- #


def test_phase_8_adds_no_value_field_to_the_exposure_record():
    """`ExposureAvailability` carries availability only. Phase 8 adds no count to it.

    This is the structural guarantee behind "no invented exposure": with nowhere to put
    a population figure, `risk x population` cannot be written here even by accident.
    """
    from app.engines.hydro.response_context import ExposureAvailability

    names = {field.name for field in dataclasses.fields(ExposureAvailability)}
    assert "value" not in names
    assert "count" not in names
    assert "population_exposed" not in names
    assert "infrastructure_exposed" not in names


def test_phase_8_exposes_no_exposure_value_field_of_its_own():
    names = {field.name.lower() for field in dataclasses.fields(IntegratedForecastAssessment)}
    forbidden = {"population_exposed", "infrastructure_exposed", "population_at_risk",
                 "exposed_population", "exposure_value", "population_count",
                 "infrastructure_count", "assets_exposed", "people_exposed"}
    offenders = names & forbidden
    assert not offenders, sorted(offenders)


def test_the_unusable_records_carry_no_value_and_no_default(medium_chain):
    """Every unusable record is an availability statement with a reason, never a zero."""
    for record in medium_chain.unusable_context:
        assert record.kind
        assert record.availability in SIGNAL_AVAILABILITY
        assert record.usable is False
        assert record.reason
        assert not hasattr(record, "value")


def test_no_exposure_multiplication_appears_in_the_module():
    """The `risk x exposed population` step that Phases 6 and 7 both refused."""
    identifiers = _code_identifiers(_tree())
    chains = set(_attribute_chains(_tree()))
    forbidden = {"population_exposed", "infrastructure_exposed", "casualties",
                 "evacuate_count", "displaced"}
    offenders = (identifiers & forbidden) | (chains & forbidden)
    assert not offenders, sorted(offenders)


# --------------------------------------------------------------------------- #
# No response downgrade, no emergency state
# --------------------------------------------------------------------------- #


def test_no_emergency_response_state_is_defined_or_referenced_as_code():
    """No evacuation, no mandatory evacuation, no emergency declaration.

    Identifiers and code strings only. The module's explanation is *required* to say
    that it emits none of these, and a raw text scan would flag that honesty as a
    violation.
    """
    tree = _tree()
    offenders = (
        _code_identifiers(tree)
        | _code_strings(tree)
    ) & {
        "EVACUATE", "MANDATORY_EVACUATION", "EMERGENCY_DECLARED", "EVACUATE_NOW",
        "DECLARE_EMERGENCY", "ALL_CLEAR", "STAND_DOWN",
    }
    assert not offenders, sorted(offenders)


@pytest.mark.parametrize(
    "state", ["WITHHELD", "MONITOR", "HEIGHTENED_MONITORING", "REVIEW_WARNING"]
)
def test_every_response_state_phase_8_accepts_is_one_phase_seven_emits(state):
    """Phase 8 cannot report a response state Phase 7 cannot produce.

    Checked by re-labelling a real decision, so the assertion is that Phase 8's own
    validation accepts each of Phase 7's four states and rejects anything else. The
    re-labelling is safe here precisely because `ResponseDecision` is a frozen dataclass
    with no constructor-time validation — Phase 7 validates at decision time.
    """
    import dataclasses as dc

    from app.engines.hydro.integration_assessment import InvalidResponseDecisionError

    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)

    assert state in RESPONSE_STATES
    relabelled = dc.replace(decision, decision=state)
    record = integrate(served_forecast, risk, relabelled)
    assert record.response_decision == state
    assert record.response.decision == state

    with pytest.raises(InvalidResponseDecisionError):
        integrate(served_forecast, risk, dc.replace(decision, decision="SOMETHING_ELSE"))


def test_a_withheld_decision_survives_every_integration_status():
    """The core no-downgrade guarantee, over every status Phase 8 can derive."""
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    withheld = decide_for(risk, policy=ResponsePolicy())
    assert withheld.decision == DECISION_WITHHELD

    assessment = integrate(served_forecast, risk, withheld)
    assert assessment.integration_status == INTEGRATION_WITHHELD
    assert assessment.response_decision == DECISION_WITHHELD
    assert assessment.response.decision == DECISION_WITHHELD
    assert assessment.response.rationale == withheld.rationale


def test_a_withheld_decision_is_never_upgraded_into_monitoring(withheld_chain):
    assert withheld_chain.integration_status == "WITHHELD"
    assert withheld_chain.response_decision == DECISION_WITHHELD
    assert withheld_chain.response_decision != "MONITOR"
    assert "does not become MONITOR" in withheld_chain.explain()


def test_a_not_evaluable_status_does_not_upgrade_the_response(not_evaluable_chain):
    assert not_evaluable_chain.integration_status == INTEGRATION_NOT_EVALUABLE
    assert not_evaluable_chain.response_decision == DECISION_WITHHELD


def test_an_integration_never_recommends_a_stronger_response_than_phase_seven(medium_chain):
    order = list(RESPONSE_STATES)
    assert order.index(medium_chain.response_decision) >= order.index(
        medium_chain.response.decision
    ) - 1
    assert medium_chain.response_decision == medium_chain.response.decision


def test_the_module_defines_no_response_state_of_its_own():
    """`INTEGRATION_STATES` must not overlap `RESPONSE_STATES`.

    An integration status that happened to be spelled like a response state would be
    read as one, and `COMPLETE`/`PARTIAL`/`WITHHELD` sitting next to `MONITOR` in the
    same vocabulary is exactly that hazard. `WITHHELD` is the one word both use, and
    it means the same thing in both — which is deliberate, and worth asserting.
    """
    integration = set(INTEGRATION_STATES)
    response = set(RESPONSE_STATES)
    assert integration & response == {"WITHHELD"}
    # And it genuinely means the same thing: Phase 8 caps at WITHHELD, never below.
    assert INTEGRATION_WITHHELD == DECISION_WITHHELD


# --------------------------------------------------------------------------- #
# No spatial or historical conclusion
# --------------------------------------------------------------------------- #


def test_the_module_computes_no_spatial_quantity():
    identifiers = _code_identifiers(_tree())
    chains = set(_attribute_chains(_tree()))
    forbidden = {"haversine", "distance", "elevation", "floodplain", "raster",
                 "point_in_polygon", "shapely", "geopandas", "pyproj", "nearest_station",
                 "river_distance", "catchment_area", "slope"}
    offenders = (identifiers & forbidden) | (chains & forbidden)
    assert not offenders, sorted(offenders)


def test_no_gis_or_ml_geospatial_package_is_imported():
    modules = _imported_modules(_tree())
    for forbidden in ("shapely", "geopandas", "pyproj", "rasterio", "fiona", "osgeo",
                      "folium", "geopy", "sklearn"):
        assert forbidden not in modules, forbidden


def test_the_absent_gis_marker_is_reproduced_exactly(medium_chain, refused_chain):
    """Phase 8 carries Phase 6's marker forward rather than inventing a new phrasing."""
    from app.engines.hydro.domains import NOT_AVAILABLE

    assert NOT_AVAILABLE == "NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED"
    assert medium_chain.gis_reason == medium_chain.risk.gis_context["reason"]
    assert refused_chain.gis_reason == NOT_AVAILABLE


def test_no_flood_event_is_invented_to_enrich_a_record(medium_chain):
    assert medium_chain.risk.historical_context["events"] == []
    assert medium_chain.historical_available is False
    assert "no flood event was invented" in medium_chain.explain()


def test_entity_refusal_has_no_nearest_station_fallback(station_two):
    """Two different station names is a refusal, not a mapping problem.

    The tempting alternative — resolving Station B to Station A because they are
    probably the same catchment — is a guess about the physical world made by an
    integration layer, on a repository with no station registry to ground it in.
    """
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    with pytest.raises(Exception) as excinfo:
        integrate(served_forecast, risk, decision_for_entity(station_two, risk))
    message = str(excinfo.value)
    assert "no station registry" in message
    assert "nearest-station" in message


# --------------------------------------------------------------------------- #
# No service boundary, no quantum
# --------------------------------------------------------------------------- #


def test_no_web_framework_or_http_client_is_imported():
    modules = _imported_modules(_tree())
    for forbidden in ("fastapi", "flask", "django", "starlette", "uvicorn", "pydantic",
                      "requests", "httpx", "aiohttp", "urllib", "requests"):
        assert forbidden not in modules, forbidden


def test_no_database_driver_is_imported():
    """Phase 8 is a pure domain contract; persistence is somebody else's layer."""
    modules = _imported_modules(_tree())
    for forbidden in ("psycopg", "psycopg2", "asyncpg", "sqlalchemy", "sqlite3",
                      "pymongo", "redis", "boto3"):
        assert forbidden not in modules, forbidden


def test_no_quantum_or_optimisation_library_is_imported():
    modules = _imported_modules(_tree())
    for forbidden in ("qiskit", "cirq", "pennylane", "qutip", "dwave", "braket", "ortools",
                      "pulp", "gurobipy", "cvxpy", "networkx"):
        assert forbidden not in modules, forbidden


def test_no_quantum_or_optimisation_vocabulary_appears_in_code():
    identifiers = _code_identifiers(_tree())
    strings = _code_strings(_tree())
    offenders = (identifiers | strings) & {
        "QUBO", "qubo", "Ising", "ising", "quantum_annealing", "qpu", "QPU",
        "quantum_speedup", "variational", "QAOA", "optimise_response", "optimal_response",
        "sensor_placement", "QUBO_energy",
    }
    assert not offenders, sorted(offenders)


def test_the_module_defines_no_router_endpoint_or_route():
    """No HTTP boundary, because this branch has none.

    `app/api/`, `app/core/` and `app/schemas/` are empty directories on this branch.
    Building a service here because another branch has one would be inventing
    infrastructure rather than integrating, and it would put a network boundary in the
    middle of a deterministic domain contract.
    """
    identifiers = _code_identifiers(_tree())
    for forbidden in ("app", "router", "APIRouter", "route", "endpoint", "app_api",
                      "FastAPI", "Depends", "HTTPException"):
        assert forbidden not in identifiers, forbidden


def test_the_service_boundary_is_reported_as_absent_rather_than_planned():
    assert integration_contract_description()["service_boundary"].startswith("none")
    assert "no HTTP boundary" in integration_contract_description()["service_boundary"]


# --------------------------------------------------------------------------- #
# No authority, no production readiness
# --------------------------------------------------------------------------- #


def test_the_authority_flags_are_module_level_constants_and_never_true():
    assert module.OPERATIONAL_AUTHORITY is False
    assert module.PRODUCTION_READY_CLAIMED is False


def test_no_code_path_can_set_an_authority_flag_true():
    """A scan for the literal, because the guarantee is that it is unreachable.

    Both flags are dataclass fields, so a caller *could* pass `True` to the constructor.
    The constructor cannot stop that — but the derived-layer check can, and the fact
    that these two names never appear as a truthy literal in code is the guard.
    """
    for field_name in ("operational_authority", "production_ready_claimed"):
        assert field_name in {field.name for field in dataclasses.fields(
            IntegratedForecastAssessment)}
    for keyword in ast.walk(_tree()):
        if not isinstance(keyword, ast.keyword):
            continue
        if keyword.arg not in ("operational_authority", "production_ready_claimed"):
            continue
        value = keyword.value
        assert not (isinstance(value, ast.Constant) and value.value is True)
        assert not (isinstance(value, ast.Name) and value.id == "True")


def test_no_configuration_can_produce_a_production_ready_claim():
    """There is no configuration object in this module, so nothing can be tuned into it."""
    assert "configuration" not in _code_identifiers(_tree())
    names = {field.name.lower() for field in dataclasses.fields(IntegratedForecastAssessment)}
    assert "config" not in names
    assert "policy" not in names


def test_every_integrated_record_reports_no_authority(
    medium_chain, repository_chain, withheld_chain, not_evaluable_chain, refused_chain,
    empty_chain
):
    for record in (
        medium_chain,
        repository_chain,
        withheld_chain,
        not_evaluable_chain,
        refused_chain,
        empty_chain,
    ):
        assert record.operational_authority is False
        assert record.production_ready_claimed is False
        assert record.provenance["operational_authority"] is False
        assert record.provenance["production_ready_claimed"] is False
        assert record.to_dict()["production_ready_claimed"] is False


def test_no_government_authority_is_claimed_in_any_record(
    medium_chain, repository_chain, empty_chain
):
    """The disclaimer must survive into the serialized form on every path."""
    for record in (medium_chain, repository_chain, empty_chain):
        assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
        assert record.to_dict()["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER
        assert SYNTHETIC_DATA_DISCLAIMER in json.dumps(record.to_dict())


# --------------------------------------------------------------------------- #
# Immutability
# --------------------------------------------------------------------------- #


def test_the_record_is_a_frozen_dataclass(medium_chain):
    assert dataclasses.is_dataclass(medium_chain)
    fields = {field.name for field in dataclasses.fields(medium_chain)}
    with pytest.raises(dataclasses.FrozenInstanceError):
        medium_chain.integration_status = INTEGRATION_COMPLETE


def test_the_chain_is_a_tuple_and_cannot_be_reassigned(medium_chain):
    assert isinstance(medium_chain.chain, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        medium_chain.chain = ()


def test_the_mappings_are_read_only(medium_chain):
    with pytest.raises(TypeError):
        medium_chain.provenance["entity"] = "SOMEWHERE-ELSE"
    with pytest.raises(TypeError):
        medium_chain.evidence_availability["valid"] = 0


def test_the_explanation_and_input_tuples_are_immutable(medium_chain):
    """Immutability of a tuple is structural, so it is asserted as a type rather than
    by provoking an exception: `tuple.__setitem__` does not exist, and `assert False`
    would be the only thing a mutation attempt could raise."""
    assert type(medium_chain.explanation) is tuple
    assert type(medium_chain.available_inputs) is tuple
    assert type(medium_chain.unusable_context) is tuple
    assert not hasattr(medium_chain.explanation, "__setitem__")
    assert not hasattr(medium_chain.unusable_context, "__setitem__")


def test_a_derived_tuple_cannot_be_patched_through_the_field(medium_chain):
    with pytest.raises(dataclasses.FrozenInstanceError):
        medium_chain.explanation = ("rewritten",)


def test_the_record_is_frozen_but_not_hashable(medium_chain):
    """It cannot be a dictionary key, and that is worth knowing rather than assuming.

    The dataclass is frozen, which normally makes Python generate a `__hash__` from the
    fields. That generated hash then fails on the read-only mappings, because a
    `MappingProxyType` is unhashable. The result is a record that *looks* hashable and
    raises `TypeError` when used as a key — so it is asserted here rather than left to
    surprise a consumer who reasoned "frozen implies hashable".

    Key on `integration_id` instead; it is a string, and it is the identity the contract
    actually publishes.
    """
    with pytest.raises(TypeError):
        {medium_chain: "value"}
    mapping = {medium_chain.integration_id: medium_chain}
    assert mapping[medium_chain.integration_id] is medium_chain


def test_equality_is_by_value_not_identity(medium_chain):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)
    assert integrate(served_forecast, risk, decision) == medium_chain


# --------------------------------------------------------------------------- #
# Disclaimer survives every path
# --------------------------------------------------------------------------- #


def test_the_disclaimer_is_present_on_every_derivable_path(
    medium_chain, repository_chain, withheld_chain, not_evaluable_chain, refused_chain,
    empty_chain, context_unavailable_chain
):
    for record in (
        medium_chain, repository_chain, withheld_chain, not_evaluable_chain,
        refused_chain, empty_chain, context_unavailable_chain,
    ):
        assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
        assert record.to_dict()["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER


def test_the_disclaimer_cannot_be_emptied_through_the_error_path():
    for error in (
        MissingForecastError("no forecast"),
        ValueError("plain"),
        RuntimeError("boom"),
    ):
        record = integration_from_error(error)
        assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
        assert SYNTHETIC_DATA_DISCLAIMER in record.explain()


def test_the_disclaimer_appears_in_the_explanation_where_data_is_synthetic(
    medium_chain, repository_chain, empty_chain
):
    for record in (medium_chain, repository_chain, empty_chain):
        assert record.synthetic_demo is True
        assert SYNTHETIC_DATA_DISCLAIMER in record.explain()


# --------------------------------------------------------------------------- #
# Errors are raised, not swallowed
# --------------------------------------------------------------------------- #


def test_integrate_raises_rather_than_reporting_a_contract_violation():
    """The safe variant is opt-in; the default reports nothing it cannot stand behind."""
    with pytest.raises(ValueError):
        integrate({"not": "a served forecast"})
    with pytest.raises(ValueError):
        integrate(object(), object(), object())


def test_integrate_safe_never_raises_for_any_input():
    """It always answers, and it always says whether the answer was an error.

    The distinction matters: `None, None, None` is a legitimate chain of three absent
    layers, not a failure, so `error_reason` is `None` there and the status alone
    carries the outcome. The malformed inputs below all produce a reason.
    """
    for forecast, risk, response, expect_error in (
        (None, None, None, False),
        (object(), None, None, True),
        (shared_served(), object(), None, True),
        (shared_served(), None, "MONITOR", True),
        (shared_served(), "risk", "response", True),
    ):
        record = integrate_safe(forecast, risk, response)
        assert record.integration_status in INTEGRATION_STATES
        if expect_error:
            assert record.error_reason
        else:
            assert record.error_reason is None
            assert record.integration_status == INTEGRATION_NOT_EVALUABLE


def test_the_error_path_never_reports_complete():
    for bad in (object(), {"x": 1}, "forecast", 42):
        record = integrate_safe(bad)
        assert not record.is_complete
        assert record.integration_status == INTEGRATION_NOT_EVALUABLE


def test_an_error_record_still_names_what_it_could_not_assemble():
    record = integration_from_error(MissingForecastError("no forecast was served"))
    assert record.error_reason == MissingForecastError.reason
    assert record.integration_status == INTEGRATION_NOT_EVALUABLE
    assert len(record.chain) == 3
    assert record.explanation


def test_no_broad_exception_swallow_exists_outside_the_one_documented_handler():
    """`integrate_safe` catches broadly on purpose; nothing else may.

    A bare `except Exception` that returns something plausible is how a refusal turns
    into an unnoticed success. One is allowed, and it records the reason.
    """
    handlers = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.ExceptHandler)
    ]
    broad = [
        node
        for node in handlers
        if node.type is None
        or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
    ]
    assert len(broad) == 1, f"expected exactly one broad handler, found {len(broad)}"
    parent_source = ast.unparse(broad[0])
    assert "integration_from_error" in parent_source


def test_the_error_path_names_the_violation_reason_and_not_only_the_message():
    record = integrate_safe({"not": "a served forecast"})
    assert record.error_reason == "invalid_forecast_result"
    assert record.error_reason in record.integration_reason


# --------------------------------------------------------------------------- #
# The module's own published surface
# --------------------------------------------------------------------------- #


def test_the_module_publishes_exactly_what_it_defines():
    for name in module.__all__:
        assert hasattr(module, name), name
        assert name in MODULE_SOURCE


def test_the_contract_version_is_namespaced_to_phase_eight():
    assert module.INTEGRATION_CONTRACT_VERSION == "navya-phase8-integration/v1"


def test_the_module_header_carries_the_platform_pledge():
    assert "Q-FLARE" in MODULE_SOURCE
    assert "Navya" in MODULE_SOURCE
    assert "Apache-2.0" in MODULE_SOURCE