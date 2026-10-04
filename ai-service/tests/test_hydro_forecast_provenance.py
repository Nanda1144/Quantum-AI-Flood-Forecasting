# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Provenance, data status, and the synthetic-data disclaimer, end to end.

Phase 1 built one `ProvenanceRecord` and one mandatory disclaimer sentence, and
Phase 5 has to carry both through a serving boundary without inventing a second
system to do it. So the questions here are narrow and specific:

* **does the record survive?** The artifact must carry the training run's record,
  not a summary of it, and the forecast must carry the artifact's.
* **is there exactly one provenance system?** A parallel Phase 5 record would give
  two answers to "what produced this number", and only one of them would be the one
  the platform audits.
* **does the disclaimer reach every surface?** Artifact, forecast, served payload,
  handoff, and the machine-readable contract - each one a place it could be dropped
  while the code still passed.
* **does anything claim production readiness?** Nothing may, on this data, and the
  field that would carry such a claim is asserted false at every layer.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from app.engines.hydro.forecast_selection import candidates_from_artifacts
from app.engines.hydro.forecast_serving import serve, serving_contract_description
from app.engines.hydro.model_handoff import HANDOFF_CONTRACT_VERSION
from app.engines.hydro.provenance import (
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
    SYNTHETIC_METRIC_DISCLAIMER,
    ProvenanceRecord,
)

from hydro_phase5_fixtures import (
    STATION_A,
    SYNTHETIC_DISCLAIMER,
    TARGET,
    artifact,
    artifact_for,
    baseline_artifact,
    estimators,
    family_request,
    manifest_payload,
    manifests,
    model_dataset,
    origin,
    request_for,
    serving_input,
    store,
    trained_run,
)


# --------------------------------------------------------------------------- #
# Reading the Phase 1 record back out of an artifact
# --------------------------------------------------------------------------- #


def _record_from(provenance: dict) -> ProvenanceRecord:
    """Rebuild Phase 1's `ProvenanceRecord` from the mapping an artifact carries.

    Written out rather than delegated, so each test reads as a claim about the
    record's contents. `ProvenanceRecord` has no `from_dict`, so the round trip goes
    through `SplitBoundaries` explicitly - which is the honest thing to assert about
    anyway: the artifact's `provenance` really is deserialisable into Phase 1's own
    type, not merely similar to it.
    """
    from app.engines.hydro.model_dataset import SplitBoundaries

    return ProvenanceRecord(
        dataset_reference=provenance.get("dataset_reference"),
        dataset_type=provenance.get("dataset_type", "unknown"),
        dataset_license=provenance.get("dataset_license"),
        dataset_checksum=provenance.get("dataset_checksum"),
        sampling_interval=provenance.get("sampling_interval"),
        target=provenance.get("target"),
        target_units=provenance.get("target_units"),
        forecast_horizon=provenance.get("forecast_horizon"),
        station_reference=provenance.get("station_reference"),
        feature_list=tuple(provenance.get("feature_list") or ()),
        split=SplitBoundaries(**provenance["split"]),
        model_name=provenance.get("model_name"),
        model_version=provenance.get("model_version"),
        artifact_reference=provenance.get("artifact_reference"),
        created_at=provenance["created_at"],
        software_environment=provenance.get("software_environment") or {},
        disclaimer=provenance.get("disclaimer"),
        evaluation_metrics=provenance.get("evaluation_metrics"),
    )


# --------------------------------------------------------------------------- #
# The record itself is reused, not replaced
# --------------------------------------------------------------------------- #


def test_the_artifact_carries_the_training_runs_own_provenance_record(artifact) -> None:
    """Carried whole, not summarised.

    The record is Phase 1's, with every field it was built with - including the ones
    that are inconvenient, like `missing_fields` and `dataset_checksum: None`. A
    Phase 5 subset would be easier to keep honest only by dropping what it could not
    represent, and the dropped parts are the parts a reviewer needs.
    """
    provenance = artifact.provenance
    assert provenance, "the artifact has no provenance record at all"
    record = _record_from(provenance)
    assert record.dataset_type == DATASET_TYPE_SYNTHETIC
    assert record.target == TARGET
    assert record.target_units == artifact.target_units
    assert record.forecast_horizon == artifact.horizon
    assert record.station_reference == STATION_A
    assert tuple(record.feature_list) == tuple(artifact.feature_names)
    assert record.model_name == artifact.model_family
    assert record.model_version == artifact.model_version
    assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    # The incompleteness is preserved too.
    assert record.is_complete is False
    assert "dataset_checksum" in record.missing_fields()
    assert record.software_environment["random_seed"] == "20240917"


def test_phase_5_defines_no_provenance_type_of_its_own() -> None:
    """One provenance system, so there is one answer to "what produced this".

    Checked by reading the phase's modules rather than by convention, because a
    dataclass carrying `dataset_type` and `software_environment` would be a second
    system and it would be the one a new caller found first.

    The checked set is the fields that describe *the dataset and its evaluation* -
    the ones only a provenance record may own. `target`, `model_version` and
    `disclaimer` are deliberately excluded: they are also required on the artifact
    contract itself, and a field can be part of two contracts without being a second
    source of truth.
    """
    import inspect

    from app.engines.hydro import (
        forecast_artifact,
        forecast_inference,
        forecast_selection,
        forecast_serving,
    )

    record_owned = {
        "dataset_reference",
        "dataset_type",
        "dataset_license",
        "dataset_checksum",
        "sampling_interval",
        "software_environment",
        "evaluation_metrics",
        "metrics_label",
        "is_complete",
        "missing_fields",
        "is_synthetic",
    }
    for module in (forecast_artifact, forecast_inference, forecast_selection, forecast_serving):
        for name, value in vars(module).items():
            if (
                not inspect.isclass(value)
                or value.__module__ != module.__name__
                or not dataclasses.is_dataclass(value)
            ):
                continue
            fields = {field.name for field in dataclasses.fields(value)}
            overlap = fields & record_owned
            assert not overlap, (
                f"{module.__name__}.{name} re-declares provenance field(s) {sorted(overlap)}; "
                "Phase 5 must carry the Phase 1 record rather than keep a parallel one"
            )


def test_the_artifact_stores_the_record_as_a_mapping_and_rebuilds_it_exactly(
    artifact,
) -> None:
    """Round-tripped, so `provenance` on the artifact is the record and not a copy.

    `ForecastArtifact.provenance` is a plain mapping because it has to survive JSON
    serialisation to disk. Rebuilding it through `ProvenanceRecord` and comparing
    `to_dict()` is what shows the mapping is the record rather than a lookalike.
    """
    rebuilt = _record_from(artifact.provenance).to_dict()
    assert rebuilt == artifact.provenance, (
        "the artifact's provenance mapping is not what ProvenanceRecord produces from it"
    )


def test_the_record_survives_the_json_round_trip_byte_for_byte(
    store, manifests, tmp_path
) -> None:
    """Written to disk and read back, it is the same record.

    A deployment reads artifacts from files, so a field that is dropped in
    serialisation is a field no deployment will ever have.
    """
    from app.engines.hydro.forecast_artifact import load_artifact_directory
    from app.engines.hydro.model_artifacts import INDEX_FILENAME, write_manifests

    # `write_manifests` takes Phase 4's manifest bundle, which is what is on disk -
    # the store is a Phase 5 view of it, not the thing that gets serialised.
    written = write_manifests(manifests, tmp_path)
    assert written, "nothing was written to compare"
    assert (tmp_path / INDEX_FILENAME).exists(), "the artifact index was not written"

    reloaded = load_artifact_directory(tmp_path)
    original = {a.model_id: a for a in store.artifacts}
    assert len(reloaded) == len(original)
    for found in reloaded:
        before = original[found.model_id]
        assert found.provenance == before.provenance, (
            f"{found.model_id}: the provenance record changed on the way through disk"
        )


# --------------------------------------------------------------------------- #
# The disclaimer reaches every surface
# --------------------------------------------------------------------------- #


def test_the_disclaimer_is_the_platform_sentence_and_not_a_paraphrase() -> None:
    """The platform README requires the wording, so the wording is asserted here.

    Byte-for-byte, against the constant Phase 1 defined. A paraphrase keeps the
    meaning and loses the requirement, and the loss is invisible until someone
    checks.
    """
    assert SYNTHETIC_DISCLAIMER == SYNTHETIC_DISCLAIMER.strip()
    assert (
        SYNTHETIC_DISCLAIMER
        == "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
        "HYDROLOGICAL OBSERVATION DATA."
    )
    assert SYNTHETIC_DISCLAIMER == SYNTHETIC_DISCLAIMER.upper()
    assert SYNTHETIC_DISCLAIMER.isupper()


@pytest.mark.parametrize("family", ["naive", "random_forest", "xgboost"])
def test_every_artifact_including_a_blocked_one_carries_the_disclaimer(
    store, family: str
) -> None:
    """Including the ones that cannot run.

    A dependency-blocked artifact is the one most likely to be dropped from a report
    as noise, and it is exactly the one whose absence of metrics could otherwise be
    read as an absence of caveats.
    """
    found = artifact_for(store, family)
    assert found.synthetic_demo is True
    assert found.data_status == "synthetic_demo"
    assert found.disclaimer == SYNTHETIC_DISCLAIMER


def test_the_forecast_carries_the_disclaimer_and_the_data_status(
    store, model_dataset, origin, estimators
) -> None:
    """Forwarded from the artifact rather than looked up again at serving time.

    Serving does not know what data the model was trained on - only the artifact
    does - so re-deriving the status at inference time would be a guess about
    provenance made by the layer with the least access to it.
    """
    for family in ("naive", "random_forest"):
        served = serve(
            family_request(origin, family),
            store=store,
            data=serving_input(model_dataset, origin),
            estimators=estimators,
        )
        assert served.status == "ready"
        inference = served.inference
        assert inference.synthetic_demo is True
        assert inference.data_status == "synthetic_demo"
        assert inference.disclaimer == SYNTHETIC_DISCLAIMER
        assert inference.describe().endswith(SYNTHETIC_DISCLAIMER), (
            "the human-readable form dropped the sentence the machine-readable form carries"
        )


def test_the_served_payload_carries_the_disclaimer(store, model_dataset, origin) -> None:
    served = serve(
        family_request(origin),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    payload = served.to_dict()
    assert payload["forecast"]["disclaimer"] == SYNTHETIC_DISCLAIMER
    assert payload["forecast"]["synthetic_demo"] is True
    assert SYNTHETIC_DISCLAIMER in served.describe()


def test_a_refusal_names_the_data_status_of_the_models_it_could_not_use(
    store, model_dataset, origin
) -> None:
    """The refusal is where a reader asks "what kind of model is this deployment
    running?", and the answer is in the store the request was refused against.

    A refusal that carried no caveat would make the synthetic-data warning appear
    only once a forecast existed - the opposite of when it matters, because the
    refusal is what sends someone to look at the deployment.
    """
    served = serve(
        request_for(origin, model_id=artifact_for(store, "random_forest").model_id),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.status == "artifact_unavailable"
    assert served.artifact is not None
    assert served.artifact.synthetic_demo is True
    assert served.artifact.disclaimer == SYNTHETIC_DISCLAIMER
    assert SYNTHETIC_DISCLAIMER in served.describe()


def test_the_contract_states_the_data_status_including_its_exact_sentence() -> None:
    """An integrator reading the contract learns this before reading a forecast."""
    statement = serving_contract_description()["data_status_statement"]
    assert SYNTHETIC_DISCLAIMER in statement
    assert "synthetic" in statement.lower()
    assert "production-ready" in statement


def test_the_metrics_carry_their_own_qualification(artifact) -> None:
    """Metrics on synthetic data are qualified separately from the data itself.

    The data disclaimer says the inputs are not real. The metrics disclaimer says the
    *numbers describing the model* are not results either - a different claim, and a
    reader comparing two models needs it. So it travels in the record next to the
    metrics rather than being left for the reader to infer from the data warning.
    """
    record = _record_from(artifact.provenance)
    assert record.evaluation_metrics
    assert record.is_synthetic is True
    assert record.metrics_label == SYNTHETIC_METRIC_DISCLAIMER
    assert record.to_dict()["metrics_label"] == SYNTHETIC_METRIC_DISCLAIMER
    assert record.to_dict()["is_synthetic"] is True

    # The label is derived from the record's own data status, so it cannot drift away
    # from it: real data would say `measured evaluation` from the same code path.
    from app.engines.hydro.provenance import DATASET_TYPE_UNKNOWN, ProvenanceRecord as PR

    unknown = PR(dataset_type=DATASET_TYPE_UNKNOWN)
    assert unknown.metrics_label == "measured evaluation"
    assert unknown.is_synthetic is False


# --------------------------------------------------------------------------- #
# Nothing claims production readiness
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("family", ["naive", "random_forest", "xgboost"])
def test_no_artifact_claims_production_readiness(store, family: str) -> None:
    """The field exists so the claim can be made deliberately. On this data it is not.

    `production_ready_claimed` is pinned `False` on every artifact regardless of
    state, family or metrics, because the only thing that could make it `True` is a
    real gauge network and an approved threshold policy - neither of which exists on
    this branch.
    """
    for found in store.artifacts:
        assert found.production_ready_claimed is False
        assert found.to_dict()["production_ready_claimed"] is False


def test_a_manifest_cannot_claim_production_readiness_however_it_is_written(
    artifact,
) -> None:
    """A hostile or careless manifest cannot flip the claim on.

    Asserted by writing the flag into the manifest payload, because a field that is
    read from untrusted input and trusted afterwards is the exact shape of this bug.
    """
    from app.engines.hydro.forecast_artifact import parse_artifact

    payload = manifest_payload(
        artifact,
        production_ready_claimed=True,
        synthetic_demo=False,
        data_status="measured",
    )
    parsed = parse_artifact(payload)
    assert parsed.production_ready_claimed is False, (
        "the artifact took a production-readiness claim from the manifest it was parsing"
    )
    # The data status is likewise derived from the provenance record, not trusted: the
    # manifest claimed `measured`, and the record says synthetic.
    assert parsed.synthetic_demo is True
    assert parsed.data_status == "synthetic_demo"


def test_a_data_status_the_platform_does_not_define_is_refused(artifact) -> None:
    """An unrecognised status is a malformed manifest, not a fallback to `unknown`.

    Checked on a manifest with no provenance record, because that is the only case in
    which the manifest's own `data_status` is used. When a record *is* present the
    value is overridden rather than validated - the record wins either way, so an
    invented status cannot reach the artifact as anything but a contradiction.

    Defaulting would let a typo - `mesasured` - become a real-looking claim, and a
    reader would have no way to tell it from a deliberate one.
    """
    from app.engines.hydro.forecast_artifact import ArtifactMalformedError, parse_artifact

    recordless = manifest_payload(artifact, data_status="real")
    recordless["provenance"] = None
    with pytest.raises(ArtifactMalformedError) as caught:
        parse_artifact(recordless)
    assert "data_status" in str(caught.value)
    assert "synthetic_demo" in str(caught.value), (
        "the refusal should list the statuses it accepts, so the wrong one can be corrected"
    )

    # ...and with a record present the same manifest parses, to what the record says.
    overridden = parse_artifact(manifest_payload(artifact, data_status="real"))
    assert overridden.data_status == "synthetic_demo"
    assert overridden.synthetic_demo is True


def test_a_forecast_never_claims_production_readiness(store, model_dataset, origin) -> None:
    served = serve(
        family_request(origin),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.inference.production_ready_claimed is False
    assert served.to_dict()["forecast"]["production_ready_claimed"] is False


def test_the_handoff_repeats_the_data_status_and_the_weight_policy(
    store, model_dataset, origin, estimators, trained_run
) -> None:
    """The handoff is what the platform persists, so its caveats are the durable ones."""
    from app.engines.hydro.model_artifacts import build_manifests

    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
        run_result=trained_run,
        manifests=build_manifests(trained_run),
    )
    handoff = served.handoff
    assert handoff is not None
    assert handoff.status == "ready"
    assert handoff.synthetic_demo is True
    assert handoff.disclaimer == SYNTHETIC_DISCLAIMER
    assert handoff.data_status == "synthetic_demo"
    assert handoff.production_ready_claimed is False
    assert handoff.weight_storage_policy
    assert handoff.artifact_manifest_version
    assert handoff.provenance
    assert _record_from(handoff.provenance).dataset_type == DATASET_TYPE_SYNTHETIC
    # The platform's own `ForecastOutput` has no readiness field to fill in, which is
    # itself the right outcome: there is nothing on that contract claiming this
    # forecast is fit to act on. What it does carry is the disclaimer.
    assert served.output.disclaimer == SYNTHETIC_DISCLAIMER
    assert not hasattr(served.output, "production_ready_claimed")
    assert served.output.threshold_policy
    assert "PENDING" in served.output.threshold_policy.upper(), (
        "a threshold policy on synthetic data must read as pending, whatever it says"
    )


def test_the_contract_versions_are_the_ones_the_platform_already_uses() -> None:
    """Phase 5 sits between Phase 4's handoff and the platform forecast output.

    So a change to either of those contract versions has to show up in Phase 5's
    published description, or an integrator reading it would plan against a contract
    version the rest of the system does not use.
    """
    described = serving_contract_description()
    assert described["handoff_contract_version"] == HANDOFF_CONTRACT_VERSION
    assert described["downstream_forecast_contract_version"]
    assert described["artifact_schema_version"]


# --------------------------------------------------------------------------- #
# The seed and the determinism information
# --------------------------------------------------------------------------- #


def test_the_seed_is_carried_from_the_manifest_to_the_forecast(
    store, model_dataset, origin, estimators
) -> None:
    """Reproducing a number requires knowing which seed produced it.

    The seed is in the artifact and in the environment block of the provenance
    record, so a forecast can be traced back to the run that would reproduce it.
    """
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    found = artifact_for(store, "random_forest")
    assert served.artifact.random_seed == found.random_seed == 20240917
    assert "seed20240917" in served.artifact.model_version
    environment = _record_from(found.provenance).software_environment
    assert environment["random_seed"] == "20240917"


def test_the_dependency_versions_needed_to_reproduce_are_recorded(store) -> None:
    """Including the ones that are absent, as `not installed` rather than omitted.

    An omitted dependency reads as an unexamined one, and "xgboost was not installed"
    is a finding a reader needs in order to know why a model is missing.
    """
    blocked = artifact_for(store, "xgboost")
    assert blocked.state == "dependency_blocked"
    assert blocked.dependency_versions["xgboost"].startswith("not installed")
    assert "TEAM_INTEGRATION_REQUIREMENTS" in blocked.dependency_versions["xgboost"], (
        "the refusal should point at the recorded integration action, so the missing dependency "
        "has an owner rather than being a dead end"
    )

    served_family = artifact_for(store, "random_forest")
    assert served_family.dependency_versions["sklearn"].startswith("installed")

    # The parameter-free family needs no dependency and does not claim one.
    assert artifact_for(store, "naive").dependency_versions == {}


def test_the_creation_timestamp_is_present_and_iso8601(store) -> None:
    """A record with no timestamp cannot be ordered against other records."""
    for found in store.artifacts:
        assert found.created_at
        parsed = dt.datetime.fromisoformat(found.created_at.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, "a naive timestamp is ambiguous across zones"


# --------------------------------------------------------------------------- #
# Data status is derived, not asserted
# --------------------------------------------------------------------------- #


def test_the_data_status_follows_the_provenance_record_not_a_caller(store, artifact) -> None:
    """One source of truth for "is this data real".

    `synthetic_demo`, `data_status` and `disclaimer` are three views of one fact. If
    they were independent, a caller could produce an artifact with `synthetic_demo
    False` and the disclaimer still attached - or the reverse, which is the dangerous
    one.
    """
    from app.engines.hydro.forecast_artifact import parse_artifact

    for found in store.artifacts:
        record = _record_from(found.provenance)
        expected = (
            "synthetic_demo" if record.dataset_type == DATASET_TYPE_SYNTHETIC else "unknown"
        )
        assert found.data_status == expected, f"{found.model_family}: data status disagrees"
        assert found.synthetic_demo is (record.dataset_type == DATASET_TYPE_SYNTHETIC)
        if found.synthetic_demo:
            assert found.disclaimer == record.disclaimer == SYNTHETIC_DISCLAIMER

    # A payload claiming measured data is corrected to what the record says.
    forged = parse_artifact(manifest_payload(artifact, data_status="measured"))
    assert forged.data_status != "measured"


def test_the_baseline_carries_the_same_caveats_as_the_models_it_is_compared_against(
    store, baseline_artifact
) -> None:
    """The baseline is the fallback everyone reaches for first.

    If it were the one artifact without the caveat, then a deployment that quietly
    served persistence would also quietly stop saying the data is synthetic.
    """
    baseline = baseline_artifact
    model = artifact_for(store, "random_forest")
    assert baseline.synthetic_demo == model.synthetic_demo
    assert baseline.disclaimer == model.disclaimer
    assert baseline.data_status == model.data_status
    assert baseline.provenance["dataset_type"] == model.provenance["dataset_type"]
    assert baseline.production_ready_claimed is model.production_ready_claimed is False


def test_a_selection_decision_repeats_the_caveat_where_it_is_read(
    store, model_dataset, origin, estimators
) -> None:
    """`describe()` is what a reviewer reads, so it has to carry the sentence too.

    The decision's structured fields already carry `synthetic_demo`; this checks the
    rendered form, because a rendered form that omits the caveat is what ends up
    pasted into a ticket.
    """
    from app.engines.hydro.forecast_selection import select_model

    candidates = candidates_from_artifacts(
        store.artifacts, target=TARGET, horizon="6h"
    )
    decision = select_model(candidates, metric="rmse", split="validation")
    text = decision.describe()
    assert SYNTHETIC_DATA_DISCLAIMER in text
    assert decision.to_dict()["synthetic_demo"] is True


def test_a_refused_forecast_names_the_station_and_the_target_it_refused(
    store, model_dataset, origin
) -> None:
    """The refusal is about a specific gauge and a specific target, and says so.

    A refusal that does not name them cannot be matched to the request that caused
    it once it is in a log.
    """
    served = serve(
        request_for(origin, entity=STATION_A, model_id="lstm-anything"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.status != "ready"
    assert STATION_A in served.reason or STATION_A in served.describe()
    assert TARGET in served.describe()
    assert served.request.entity == STATION_A
    assert served.request.target == TARGET