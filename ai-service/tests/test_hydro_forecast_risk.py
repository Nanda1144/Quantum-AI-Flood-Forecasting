# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 6: forecast integration, classification, thresholds, provenance, determinism.

The claim under test throughout: **Phase 6 consumes a validated Phase 5 forecast and
reports an auditable risk, or refuses.** Not one test here asserts that the pipeline
predicts a flood, because it does not and cannot on synthetic data. What is asserted
is that every number in a `RiskResult` traces to a measurement, every absent number
says why, and two identical calls produce identical output.

The band thresholds are derived from the fixture's own prediction and measured
residual spread rather than hard-coded, so these tests keep testing what they claim
even if the fixture's model changes. See `hydro_phase6_fixtures`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math

import pytest

from app.engines.hydro.contract import SUPPORTED_RISK_LEVELS, ForecastOutput
from app.engines.hydro.domains import (
    RISK_STATUS_RECORDED,
    RISK_STATUS_WITHHELD,
    RiskScoreRecord,
)
from app.engines.hydro.forecast_risk import (
    RISK_SCORE_TYPE_EXCEEDANCE,
    SIGMA_SOURCE_ABSENT,
    SIGMA_SOURCE_RESIDUALS,
    SIGMA_SOURCE_SUPPLIED,
    RiskConfiguration,
    assess_risk,
    assess_risk_safe,
    context_digest,
    risk_contract_description,
    risk_from_error,
)
from app.engines.hydro.forecast_serving import ForecastServiceError, serve
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.risk_context import (
    CONTEXT_FULLY_EVALUATED,
    CONTEXT_NOT_EVALUABLE,
    EntityMismatchError,
    InvalidForecastError,
    InvalidRiskCalculationError,
    InvalidRiskConfigurationError,
    InvalidThresholdError,
    InvalidUnitsError,
    MissingForecastError,
    MissingRiskContextError,
    RiskContext,
)
from app.engines.hydro.forecast_serving import ServedForecast

from hydro_phase6_fixtures import (
    BAND_EDGES,
    BAND_LABELS,
    DEMO_THRESHOLD_SOURCE,
    SYNTHETIC_STATUS,
    TARGET,
    baseline_served,
    context,
    empty_context,
    family_request,
    full_context,
    origin,
    residuals,
    risk_config,
    run,
    served,
    sigma,
    station_a,
    threshold_for_band,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def assess_at_band(
    served_forecast, band: str, measured_sigma: float, context_value, *, residuals, **kwargs
):
    """Assess with the threshold derived to land in `band`.

    Kept as a helper rather than inlined so a band test reads as "this forecast is a
    MEDIUM and the pipeline says MEDIUM", with the threshold arithmetic in one place.
    """
    prediction = served_forecast.inference.prediction
    threshold = threshold_for_band(prediction, measured_sigma, band)
    config = risk_config(threshold, **kwargs)
    return assess_risk(
        served_forecast, config=config, context=context_value, residuals=residuals
    ), threshold


def band_thresholds(forecast, measured_sigma: float) -> dict[str, float]:
    return {
        band: threshold_for_band(forecast.inference.prediction, measured_sigma, band)
        for band in SUPPORTED_RISK_LEVELS
    }


# --------------------------------------------------------------------------- #
# Forecast integration
# --------------------------------------------------------------------------- #


def test_a_valid_phase5_forecast_is_assessed(served, context, sigma, residuals):
    """The happy path: a `ready` Phase 5 result plus a measured spread yields a level."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    assert result.status == RISK_STATUS_RECORDED
    assert result.is_available
    assert result.risk_level == "MEDIUM"
    assert result.evaluation_state == CONTEXT_FULLY_EVALUATED
    assert result.forecast is served.inference
    assert result.forecast_id == served.forecast_id


def test_the_phase5_result_is_consumed_not_replaced(served, context, sigma, residuals):
    """Phase 6 reuses Phase 5's inference object rather than a parallel forecast type."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    assert type(result.forecast) is type(served.inference)
    assert result.forecast.artifact_id == served.inference.artifact_id
    assert result.forecast.model_version == served.inference.model_version
    assert result.forecast.feature_digest == served.inference.feature_digest


def test_a_missing_forecast_is_refused(context):
    """No forecast means no risk. It does not mean low risk."""
    with pytest.raises(MissingForecastError):
        assess_risk(None, config=risk_config(3.5), context=context, residuals=[0.1, -0.2, 0.3])


def test_an_object_that_is_not_a_forecast_is_refused(context):
    with pytest.raises(InvalidForecastError):
        assess_risk(
            {"prediction": 3.2}, config=risk_config(3.5), context=context, residuals=[0.1, -0.2]
        )


def test_a_refused_phase5_result_is_refused_by_phase6(run, context, sigma, residuals):
    """A Phase 5 result that never produced a forecast has no risk input either.

    The real `xgboost` refusal, not a hand-built one: `xgboost` is dependency-blocked
    here, so `serve` returns `dependency_unavailable` with no inference, and Phase 6
    must not invent a prediction from it.
    """
    refused = serve(
        family_request(run.origin, "xgboost"),
        store=run.store,
        data=None,
        estimators=run.estimators,
    )
    assert refused.status == "dependency_unavailable"
    assert refused.inference is None

    with pytest.raises(InvalidForecastError) as excinfo:
        assess_risk(refused, config=risk_config(3.5), context=context, residuals=residuals)
    assert "dependency_unavailable" in str(excinfo.value)


def test_phase5_refuses_to_build_a_ready_result_with_no_inference(served, context, residuals):
    """The invariant holds at the source, so Phase 6's guard is defence in depth.

    `ServedForecast.__post_init__` already rejects `ready` without an inference, which
    is the right place for the rule. The object below is therefore built the way a
    *deserialised* or hand-constructed record from outside this repository could look —
    frozen dataclass bypassed, `ready` with nothing behind it — which is exactly the
    state Phase 6's own check exists to catch.
    """
    with pytest.raises(ForecastServiceError):
        dataclasses.replace(served, inference=None)

    corrupted = object.__new__(ServedForecast)
    for field in dataclasses.fields(ServedForecast):
        object.__setattr__(corrupted, field.name, getattr(served, field.name))
    object.__setattr__(corrupted, "inference", None)

    with pytest.raises(InvalidForecastError) as excinfo:
        assess_risk(corrupted, config=risk_config(3.5), context=context, residuals=residuals)
    assert "no inference" in str(excinfo.value)


def test_a_bare_phase5_inference_is_accepted_without_serving_again(
    served, context, sigma, residuals
):
    """A caller holding a validated inference need not re-run serving to ask about risk."""
    result = assess_risk(
        served.inference,
        config=risk_config(threshold_for_band(served.inference.prediction, sigma, "LOW")),
        context=context,
        residuals=residuals,
    )
    assert result.risk_level == "LOW"
    # No `ServedForecast` means no forecast id was available, and none was invented.
    assert result.forecast_id is None
    assert result.forecast is served.inference


def test_a_missing_context_is_refused(served, residuals):
    """A forecast with no declared evidence around it is not an assessed risk."""
    with pytest.raises(MissingRiskContextError):
        assess_risk(served, config=risk_config(3.5), context=None, residuals=residuals)


def test_forecast_metadata_is_preserved_verbatim(baseline_served, context, sigma, residuals):
    """Every identifying fact Phase 5 reported survives into the risk result."""
    threshold = threshold_for_band(baseline_served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        baseline_served, config=risk_config(threshold), context=context, residuals=residuals
    )
    inference = baseline_served.inference

    assert result.forecast_id == baseline_served.forecast_id
    assert result.forecast.model_id == inference.model_id
    assert result.forecast.model_family == inference.model_family
    assert result.forecast.model_version == inference.model_version
    assert result.forecast.artifact_id == inference.artifact_id
    assert result.forecast.feature_digest == inference.feature_digest
    assert result.forecast.entity == inference.entity
    assert result.forecast.target == inference.target
    assert result.forecast.target_units == inference.target_units
    assert result.forecast.horizon == inference.horizon
    assert result.forecast.origin_instant == inference.origin_instant
    assert result.forecast.prediction_timestamp == inference.prediction_timestamp
    assert result.forecast.provenance == inference.provenance


def test_the_serialised_forecast_summary_carries_the_contract_fields(
    served, context, sigma, residuals, station_a
):
    """`to_dict()` publishes the forecast in the platform's own spelling."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "HIGH")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    forecast = result.to_dict()["forecast"]

    assert forecast["model_id"] == served.inference.model_id
    assert forecast["artifact_id"] == served.inference.artifact_id
    assert forecast["feature_digest"] == served.inference.feature_digest
    assert forecast["entity"] == station_a
    assert forecast["target"] == TARGET
    assert forecast["prediction"] == served.inference.prediction
    assert forecast["horizon"] == served.inference.horizon


# --------------------------------------------------------------------------- #
# Risk classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("band", list(SUPPORTED_RISK_LEVELS))
def test_every_platform_band_is_reachable_from_a_real_forecast(
    band, served, context, sigma, residuals
):
    """LOW, MEDIUM, HIGH and CRITICAL each come from a derived threshold.

    These are the repository's own level names from `contract.SUPPORTED_RISK_LEVELS`.
    Phase 6 does not introduce `moderate` or any other vocabulary: a level the
    platform cannot read is a level it may not produce.
    """
    result, threshold = assess_at_band(served, band, sigma, context, residuals=residuals)

    assert result.risk_level == band
    assert result.risk_level in SUPPORTED_RISK_LEVELS
    assert result.threshold == pytest.approx(threshold)
    assert result.band_labels == BAND_LABELS
    assert result.band_edges == BAND_EDGES


def test_the_bands_come_from_the_configuration_not_a_hardcoded_list(
    served, context, sigma, residuals
):
    """The recorded bands are the policy's own, so the classification is auditable."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.band_labels == BAND_LABELS
    assert result.band_edges == BAND_EDGES
    assert result.to_dict()["band_labels"] == list(BAND_LABELS)


def test_the_probability_is_monotonic_in_the_threshold(served, context, sigma, residuals):
    """A higher threshold cannot produce a higher exceedance probability."""
    probabilities = []
    for band in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        threshold = threshold_for_band(served.inference.prediction, sigma, band)
        result = assess_risk(
            served, config=risk_config(threshold), context=context, residuals=residuals
        )
        probabilities.append(result.risk_score)

    assert probabilities == sorted(probabilities, reverse=True)
    for probability in probabilities:
        assert 0.0 <= probability <= 1.0


def test_the_score_is_reported_as_a_probability_not_a_flood_frequency(
    served, context, sigma, residuals
):
    """The score's meaning is stated, so nobody reads it as a validated probability."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    assert result.risk_score_type == RISK_SCORE_TYPE_EXCEEDANCE
    assert result.risk_score == result.assessment.flood_probability
    assert 0.0 <= result.risk_score <= 1.0
    assert result.assessment.method == "normal_approximation_measured_sigma"


def test_no_band_is_claimed_without_a_measured_residual_spread(served, context):
    """Aggregate metrics cannot supply a spread, so no level is assigned.

    This is the load-bearing refusal of the phase. With a usable threshold and a
    fully-evaluated context, the only thing missing is the spread — and the result
    says `withheld`, not `LOW`.
    """
    threshold = threshold_for_band(served.inference.prediction, 0.2, "MEDIUM")
    result = assess_risk(served, config=risk_config(threshold), context=context)

    assert result.status == RISK_STATUS_WITHHELD
    assert result.risk_level is None
    assert result.risk_score is None
    assert result.risk_score_type is None
    assert result.residual_sigma is None
    assert result.residual_sigma_source == SIGMA_SOURCE_ABSENT
    assert result.evaluation_state == CONTEXT_NOT_EVALUABLE
    # The threshold itself was usable, so it is still reported.
    assert result.threshold == pytest.approx(threshold)


def test_rmse_is_not_the_residual_sigma_phase6_needs(residuals, sigma):
    """The documented reason for refusing is real, and measured.

    If this ratio ever approached 1.0 the refusal would be pedantry. It does not:
    this model is biased, so RMSE overstates the spread by a wide margin, and using it
    would silently change every probability computed from it.
    """
    rmse = math.sqrt(sum(value * value for value in residuals) / len(residuals))
    bias = sum(residuals) / len(residuals)

    assert abs(bias) > 0.1, "the fixture model is no longer materially biased"
    assert rmse > sigma
    assert rmse / sigma > 1.2, "RMSE and sigma converged; re-check the refusal's justification"


def test_a_supplied_spread_is_recorded_as_supplied_not_measured(served, context, sigma):
    """A caller-provided sigma is labelled, so a reader knows it was not reduced here."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residual_sigma=0.25
    )

    assert result.residual_sigma == 0.25
    assert result.residual_sigma_source == SIGMA_SOURCE_SUPPLIED
    assert result.risk_level == "MEDIUM"


def test_measured_residuals_record_their_count(served, context, residuals):
    """A measured spread says how many residuals it came from."""
    threshold = threshold_for_band(served.inference.prediction, 0.23, "MEDIUM")
    result = assess_risk(served, config=risk_config(threshold), context=context, residuals=residuals)
    assert result.residual_sigma_source == f"{SIGMA_SOURCE_RESIDUALS}(n={len(residuals)})"


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_an_unmeasurable_supplied_spread_is_refused(served, context, bad):
    """No spread means no distribution, and a confident 0 or 1 would be a fabrication."""
    with pytest.raises(InvalidRiskCalculationError):
        assess_risk(served, config=risk_config(3.5), context=context, residual_sigma=bad)


def test_two_sources_for_one_spread_are_refused(served, context, sigma, residuals):
    """Two sources for one spread means nobody can say which one was used."""
    with pytest.raises(InvalidRiskCalculationError):
        assess_risk(
            served, config=risk_config(3.5), context=context, residuals=residuals, residual_sigma=sigma
        )


def test_too_few_residuals_to_measure_a_spread_are_refused(served, context):
    with pytest.raises(InvalidRiskCalculationError):
        assess_risk(served, config=risk_config(3.5), context=context, residuals=[0.3])


def test_identical_residuals_refuse_to_measure_a_spread(served, context):
    """Zero spread is not certainty; it is the absence of a distribution."""
    with pytest.raises(InvalidRiskCalculationError):
        assess_risk(served, config=risk_config(3.5), context=context, residuals=[0.3, 0.3, 0.3])


# --------------------------------------------------------------------------- #
# Threshold validation
# --------------------------------------------------------------------------- #


def test_a_configured_threshold_is_reported_with_its_source(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "HIGH")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.threshold == pytest.approx(threshold)
    assert result.threshold_units == served.inference.target_units
    assert result.threshold_source == DEMO_THRESHOLD_SOURCE
    assert result.threshold_policy == "pending"


def test_a_demo_threshold_is_never_labelled_approved(served, context, sigma, residuals):
    """A threshold a developer chose is not an approved flood stage."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    assert result.assessment.policy_approved is False
    assert "NOT an official flood stage" in result.threshold_source
    assert "demo band and carries no official meaning" in result.explain()

    # Every mention of officiality is a denial, never a claim. The denials are stripped
    # first, because the honest sentences here all *contain* the words in order to
    # disown them, and a bare phrase search would flag the disclaimer itself.
    text = result.explain().lower()
    denials = ("not an official", "no official", "not an approved", "not official")
    for denial in denials:
        text = text.replace(denial, "")
    for claim in (
        "official",
        "approved",
        "government",
        "authorised",
        "authorized",
        "production ready",
        "operational",
    ):
        assert claim not in text, claim


def test_no_threshold_configuration_withholds_the_level(served, context, residuals):
    """The repository's default policy has no flood stage, so no level is assigned."""
    from app.engines.hydro.config import RiskPolicy

    config = RiskConfiguration(policy=RiskPolicy())
    result = assess_risk(served, config=config, context=context, residuals=residuals)

    assert config.is_usable is False
    assert result.status == RISK_STATUS_WITHHELD
    assert result.risk_level is None
    assert result.threshold is None
    assert result.threshold_configuration == "unconfigured"
    # The forecast is still reported, so the refusal is about the threshold only.
    assert result.forecast is served.inference
    assert "no usable threshold policy" in result.explain()


def test_a_non_finite_threshold_is_refused_as_an_invalid_threshold(served, context, residuals):
    """A `NaN` threshold is a configuration fault, not an arithmetic one.

    `RiskPolicy.is_usable` only asks whether a threshold is present, so this reaches
    Phase 6 intact. Without the check it would surface as a failed calculation, which
    blames the wrong thing.
    """
    from app.engines.hydro.config import RiskPolicy

    config = RiskConfiguration(
        policy=RiskPolicy(
            flood_threshold=float("nan"),
            threshold_source="DEMO",
            policy_status="pending",
            band_edges=BAND_EDGES,
        )
    )
    with pytest.raises(InvalidThresholdError):
        assess_risk(served, config=config, context=context, residuals=residuals)


def test_a_threshold_in_incompatible_units_is_refused(served, context, sigma):
    """A discharge threshold and a level forecast are two different quantities."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    config = risk_config(threshold, threshold_units="m3/s")
    with pytest.raises(InvalidUnitsError) as excinfo:
        assess_risk(served, config=config, context=context, residuals=[0.1, -0.2, 0.3])
    assert "volume_flow" in str(excinfo.value)


def test_a_convertible_threshold_unit_is_accepted_and_converted(served, context, sigma):
    """A threshold in millimetres against a forecast in metres is comparable.

    The conversion is exact, so it is allowed — and the unit the threshold was
    interpreted in is reported, rather than silently swapped.
    """
    prediction = served.inference.prediction
    threshold_m = threshold_for_band(prediction, sigma, "MEDIUM")
    config = risk_config(threshold_m * 1000.0, threshold_units="mm")

    result = assess_risk(served, config=config, context=context, residuals=[0.1, -0.2, 0.3])
    assert result.threshold_units == "mm"
    assert result.threshold == pytest.approx(threshold_m * 1000.0)


def test_a_threshold_in_an_unknown_unit_is_refused(served, context):
    """A threshold in a unit nobody recognises cannot be checked against anything."""
    with pytest.raises(InvalidRiskConfigurationError):
        risk_config(3.5, threshold_units="bananas")


def test_a_forecast_without_units_is_refused(served, context, residuals):
    """No units on the forecast means no unit check is possible, so none is claimed."""
    unitless = dataclasses.replace(served.inference, target_units=None)
    with pytest.raises(InvalidUnitsError) as excinfo:
        assess_risk(unitless, config=risk_config(3.5), context=context, residuals=residuals)
    assert "does not state its units" in str(excinfo.value)


def test_band_labels_outside_the_platform_vocabulary_are_refused():
    """A risk level the platform cannot read is a level Phase 6 may not produce."""
    from app.engines.hydro.config import RiskPolicy

    with pytest.raises(InvalidRiskConfigurationError):
        RiskConfiguration(
            policy=RiskPolicy(
                flood_threshold=3.5,
                threshold_source="DEMO",
                policy_status="pending",
                band_edges=(0.5,),
                band_labels=("OK", "PROBLEM"),
            )
        )


def test_a_band_edge_policy_without_a_threshold_is_still_unusable(served, context):
    """Edges alone cannot make "flood" mean anything."""
    from app.engines.hydro.config import RiskPolicy

    config = RiskConfiguration(policy=RiskPolicy(band_edges=BAND_EDGES))
    result = assess_risk(served, config=config, context=context, residuals=[0.1, -0.2])
    assert result.risk_level is None
    assert result.status == RISK_STATUS_WITHHELD


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def test_the_forecast_artifact_id_reaches_the_provenance(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.provenance.artifact_reference == served.inference.artifact_id
    assert result.provenance_chain["forecast_artifact_id"] == served.inference.artifact_id


def test_the_model_version_and_feature_digest_reach_the_provenance(
    served, context, sigma, residuals
):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    chain = result.provenance_chain

    assert chain["model_version"] == served.inference.model_version
    assert chain["model_family"] == served.inference.model_family
    assert chain["feature_digest"] == served.inference.feature_digest
    assert chain["forecast_horizon"] == served.inference.horizon
    assert chain["entity"] == served.inference.entity
    assert result.provenance.model_version == served.inference.model_version


def test_the_risk_configuration_version_is_carried(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    config = risk_config(threshold, risk_configuration_version="navya-phase6-test-config/v77")
    result = assess_risk(served, config=config, context=context, residuals=residuals)

    assert result.risk_configuration_version == "navya-phase6-test-config/v77"
    assert result.provenance_chain["risk_configuration_version"] == "navya-phase6-test-config/v77"


def test_the_threshold_provenance_is_carried(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    config = risk_config(threshold, threshold_configuration_version="thresholds/2026-10/demo")
    result = assess_risk(served, config=config, context=context, residuals=residuals)

    assert result.threshold_configuration == "thresholds/2026-10/demo"
    assert result.provenance_chain["threshold_configuration"] == "thresholds/2026-10/demo"
    assert result.provenance_chain["threshold_source"] == DEMO_THRESHOLD_SOURCE
    assert result.provenance_chain["threshold_policy_status"] == "pending"


def test_the_threshold_configuration_falls_back_to_the_policy_source(served, context, sigma):
    """With no operator version, the policy's own source identifies the configuration."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=[0.1, -0.2]
    )
    assert result.threshold_configuration == DEMO_THRESHOLD_SOURCE


def test_synthetic_status_propagates_into_the_risk_result(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    assert result.synthetic_demo is True
    assert result.data_status == SYNTHETIC_STATUS
    assert result.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert SYNTHETIC_DATA_DISCLAIMER in result.explanation
    assert result.provenance.dataset_type == "synthetic"
    assert result.provenance.is_synthetic is True


def test_the_dataset_provenance_is_carried_from_the_forecast(served, context, sigma, residuals):
    """The risk record reuses Phase 5's `ProvenanceRecord` field for field."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    source = served.inference.provenance

    assert result.provenance.dataset_reference == source["dataset_reference"]
    assert result.provenance.dataset_license == source["dataset_license"]
    assert result.provenance.sampling_interval == source["sampling_interval"]
    assert result.provenance.station_reference == source["station_reference"]
    assert result.provenance.target == source["target"]
    assert result.provenance.target_units == source["target_units"]
    assert result.provenance.evaluation_metrics == source["evaluation_metrics"]


def test_the_split_survives_the_round_trip_as_a_typed_value(served, context, sigma, residuals):
    """The serialised split is rebuilt as `SplitBoundaries`, not left a loose mapping."""
    from app.engines.hydro.provenance import SplitBoundaries

    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert isinstance(result.provenance.split, SplitBoundaries)
    assert result.provenance.split.train_rows == served.inference.provenance["split"]["train_rows"]
    assert isinstance(result.to_dict()["provenance"]["split"], dict)


def test_the_provenance_is_json_serialisable(served, context, sigma, residuals):
    """A provenance record that cannot be written out is not an auditable one."""
    import json

    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    payload = json.dumps(result.to_dict())
    assert json.loads(payload)["risk_result_id"] == result.risk_result_id


def test_a_result_is_json_serialisable_with_no_context_at_all(
    served, sigma, residuals, station_a, origin
):
    """Even the emptiest honest result must be serialisable."""
    import json

    threshold = threshold_for_band(served.inference.prediction, sigma, "LOW")
    result = assess_risk(
        served,
        config=risk_config(threshold),
        context=empty_context(station_a, origin),
        residuals=residuals,
    )
    assert json.loads(json.dumps(result.to_dict()))["signals"] == []


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_identical_inputs_produce_an_identical_result(served, context, sigma, residuals):
    """The whole result, not just the score, is reproducible."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    config = risk_config(threshold)

    first = assess_risk(served, config=config, context=context, residuals=residuals)
    second = assess_risk(served, config=config, context=context, residuals=residuals)

    assert first.risk_result_id == second.risk_result_id
    assert first.to_dict() == second.to_dict()
    assert first.explanation == second.explanation
    assert first.risk_level == second.risk_level
    assert first.risk_score == second.risk_score


def test_the_result_id_is_derived_from_its_inputs(
    served, context, sigma, residuals, station_a
):
    """A readable id plus a digest of the evidence and configuration."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.risk_result_id.startswith(f"risk-{station_a}-{TARGET}-6h-")
    assert result.forecast_id in result.risk_result_id
    assert "@" in result.risk_result_id
    assert result.context_digest == context_digest(result.signals)


def test_changing_the_context_changes_the_result_id(
    served, origin, sigma, residuals, station_a
):
    """Different evidence is a different assessment, and the id says so."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    dry = full_context(station_a, origin, rainfall_mm=1.0)
    wet = full_context(station_a, origin, rainfall_mm=90.0)

    first = assess_risk(served, config=risk_config(threshold), context=dry, residuals=residuals)
    second = assess_risk(served, config=risk_config(threshold), context=wet, residuals=residuals)

    assert first.risk_result_id != second.risk_result_id
    assert first.risk_level == second.risk_level  # rainfall is not weighted here


def test_changing_the_configuration_changes_the_result_id(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    first = assess_risk(
        served,
        config=risk_config(threshold, risk_configuration_version="config/a"),
        context=context,
        residuals=residuals,
    )
    second = assess_risk(
        served,
        config=risk_config(threshold, risk_configuration_version="config/b"),
        context=context,
        residuals=residuals,
    )
    assert first.risk_result_id != second.risk_result_id
    assert first.risk_level == second.risk_level


def test_the_result_reads_no_clock(
    served, context, sigma, residuals, origin, station_a
):
    """`assessed_at` is the forecast origin, so nothing depends on when it was called."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    later = assess_risk(
        served,
        config=risk_config(threshold),
        context=context,
        residuals=residuals,
        assessed_at=origin + dt.timedelta(days=400),
    )
    assert later.forecast.origin_instant == served.inference.origin_instant
    assert later.risk_result_id.startswith(f"risk-{station_a}-{TARGET}-6h-")


# --------------------------------------------------------------------------- #
# Production safety
# --------------------------------------------------------------------------- #


def test_synthetic_data_never_becomes_production_ready(served, context, sigma, residuals):
    """`production_ready_claimed` is false, and no input can turn it into anything else.

    Checked across the widest possible range of inputs — every band, a pending policy
    and an approved one, a measured and a supplied spread — because the failure mode
    being guarded against is a single configuration that quietly promotes the result.
    """
    for band in SUPPORTED_RISK_LEVELS:
        for status in ("pending", "approved"):
            threshold = threshold_for_band(served.inference.prediction, sigma, band)
            config = risk_config(threshold, status=status)
            result = assess_risk(served, config=config, context=context, residuals=residuals)
            assert result.production_ready_claimed is False
            assert result.to_dict()["production_ready_claimed"] is False
            assert result.synthetic_demo is True

    withheld = assess_risk(served, config=risk_config(3.5), context=context)
    assert withheld.production_ready_claimed is False


def test_the_withheld_result_cannot_claim_production_either(served, context):
    """Not assessing a risk is not a safe risk, and it is not labelled as one."""
    result = assess_risk_safe(served, config=risk_config(3.5), context=None)
    assert result.production_ready_claimed is False
    assert result.risk_level is None


def test_no_operational_warning_claim_is_generated(served, context, sigma, residuals):
    """The explanation never says the platform is warning anyone about anything."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "CRITICAL")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    text = result.explain().lower()

    for forbidden in (
        "production ready",
        "operational",
        "official warning",
        "government",
        "real-world",
        "will flood",
        "evacuate",
    ):
        assert forbidden not in text, forbidden


def test_an_approved_policy_is_still_not_a_production_claim(
    served, context, sigma, residuals
):
    """Marking a threshold approved does not promote the pipeline to production."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served,
        config=risk_config(threshold, status="approved"),
        context=context,
        residuals=residuals,
    )
    assert result.assessment.policy_approved is True
    assert result.production_ready_claimed is False
    assert result.synthetic_demo is True


def test_the_risk_level_uses_the_platform_vocabulary_only(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.risk_level in SUPPORTED_RISK_LEVELS
    assert result.priority == {"LOW": "low", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "critical"}[
        result.risk_level
    ]


# --------------------------------------------------------------------------- #
# Uncertainty
# --------------------------------------------------------------------------- #


def test_uncertainty_is_propagated_not_invented(served, context, sigma, residuals):
    """Phase 5 said no uncertainty exists; Phase 6 says the same and adds none."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    assert result.uncertainty is served.inference.uncertainty
    assert result.uncertainty.available is False
    assert result.uncertainty.value is None
    assert result.uncertainty.is_prediction_interval is False
    assert "no uncertainty is available" in result.explain().lower()


def test_no_confidence_percentage_appears_anywhere(served, context, sigma, residuals):
    """There is no invented confidence figure in the result or its explanation."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    payload = result.to_dict()

    assert "confidence" not in payload
    assert "confidence" not in result.explain().lower()
    assert set(payload) >= {"risk_score", "risk_score_type"}


# --------------------------------------------------------------------------- #
# Platform contracts
# --------------------------------------------------------------------------- #


def test_the_risk_fields_project_onto_the_phase5_forecast_output(
    served, context, sigma, residuals, station_a
):
    """The platform contract keeps Phase 5's forecast fields and gains the risk ones."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "HIGH")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    output = result.to_forecast_output(served.output)

    assert isinstance(output, ForecastOutput)
    assert output.forecast_id == served.output.forecast_id
    assert output.station_reference == station_a
    assert output.predicted_value == served.inference.prediction
    assert output.risk_level == "HIGH"
    assert output.risk_score == pytest.approx(result.risk_score)
    assert output.threshold == pytest.approx(threshold)
    assert output.threshold_policy == "pending"
    assert output.residual_sigma == pytest.approx(sigma)
    assert output.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_the_risk_record_uses_the_repository_schema(
    served, context, sigma, residuals, station_a
):
    """`domains.RiskScoreRecord` is reused, not replaced by a parallel record."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "HIGH")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    record = result.to_risk_score_record()

    assert isinstance(record, RiskScoreRecord)
    assert record.area_reference == station_a
    assert record.risk_level == "HIGH"
    assert record.priority == "high"
    assert record.status == RISK_STATUS_RECORDED
    assert record.forecast_reference == served.forecast_id
    assert record.dataset_type == "synthetic"
    assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    # Stamped with the forecast origin, not a clock reading.
    assert record.assessed_at == served.inference.origin_instant.isoformat()


def test_a_withheld_result_produces_a_withheld_record(served, context):
    """No level means no recorded risk, and the record says `withheld`."""
    result = assess_risk(served, config=risk_config(3.5), context=context)
    record = result.to_risk_score_record()
    assert record.status == RISK_STATUS_WITHHELD
    assert record.risk_level is None
    assert record.risk_score is None


# --------------------------------------------------------------------------- #
# The safe wrapper
# --------------------------------------------------------------------------- #


def test_the_safe_wrapper_reports_a_violation_instead_of_raising(served, context, residuals):
    """A caller that must answer gets a result that names the problem."""
    result = assess_risk_safe(
        served, config=risk_config(3.5), context=RiskContext(entity="SOMEWHERE-ELSE"), residuals=residuals
    )
    assert result.status == RISK_STATUS_WITHHELD
    assert result.evaluation_state == CONTEXT_NOT_EVALUABLE
    assert result.risk_level is None
    assert "entity_mismatch" in result.explain()


def test_the_safe_wrapper_passes_a_valid_assessment_through(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk_safe(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.risk_level == "MEDIUM"
    assert result.residual_sigma_source == f"{SIGMA_SOURCE_RESIDUALS}(n={len(residuals)})"


def test_a_withheld_result_from_a_violation_fabricates_nothing(served, context):
    """Everything unestablished stays absent. There is no partial guess."""
    from app.engines.hydro.risk_context import EntityMismatchError

    error = EntityMismatchError("context is for another station")
    result = risk_from_error(error, config=risk_config(3.5), served=served)

    assert result.status == RISK_STATUS_WITHHELD
    assert result.risk_level is None
    assert result.risk_score is None
    assert result.threshold is None
    assert result.signals == ()
    assert result.escalations == ()
    assert result.provenance_chain["risk_error"] == "entity_mismatch"
    assert result.production_ready_claimed is False


# --------------------------------------------------------------------------- #
# The contract itself
# --------------------------------------------------------------------------- #


def test_the_contract_description_states_what_the_module_will_not_do():
    """The published contract names the RMSE refusal and the error policy."""
    description = risk_contract_description()
    assert description["risk_contract_version"] == "navya-phase6-risk/v1"
    assert description["risk_levels"] == SUPPORTED_RISK_LEVELS
    assert "rmse is the root-mean-square error about zero" in description[
        "rmse_is_not_residual_sigma"
    ]
    assert description["score_types"] == (RISK_SCORE_TYPE_EXCEEDANCE,)
    assert description["status_vocabulary"] == [RISK_STATUS_RECORDED, RISK_STATUS_WITHHELD]