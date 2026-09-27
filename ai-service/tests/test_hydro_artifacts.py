# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.artifacts`.

An artifact is the thing that outlives the run that produced it, so the tests
focus on it being self-describing and hard to misread: a synthetic model can
never be promoted to production-ready, a tampered file fails its checksum, and
nothing is written where nobody asked.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.engines.hydro.artifacts import (
    ARTIFACT_FORMAT_VERSION,
    ArtifactError,
    ArtifactStore,
    dataset_checksum_or_none,
)
from app.engines.hydro.models import build_model
from app.engines.hydro.provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
    ProvenanceRecord,
    SplitBoundaries,
)


def _boundaries() -> SplitBoundaries:
    return SplitBoundaries(
        train_start="2024-01-01T00:00:00Z",
        train_end="2024-01-10T00:00:00Z",
        validation_start="2024-01-10T00:00:00Z",
        validation_end="2024-01-15T00:00:00Z",
        test_start="2024-01-15T00:00:00Z",
        test_end="2024-01-20T00:00:00Z",
        train_rows=100,
        validation_rows=50,
        test_rows=50,
    )


def _provenance(dataset_type: str = DATASET_TYPE_SYNTHETIC) -> ProvenanceRecord:
    return ProvenanceRecord(
        dataset_reference="synthetic://unit-test/hydro",
        dataset_type=dataset_type,
        # A synthetic dataset has no licence to record, so `dataset_license`
        # stays None and the record is legitimately incomplete.
        dataset_license=None if dataset_type == DATASET_TYPE_SYNTHETIC else "CC-BY-4.0",
        dataset_checksum="a" * 64,
        sampling_interval="1h",
        target="water_level",
        target_units="m (demo assumption — NOT datum verified)",
        forecast_horizon="6h",
        station_reference="SYNTHETIC-STATION-0001",
        split=_boundaries(),
        model_name="Ridge Regression (L2 regularised)",
        model_version="ridge-v1",
    )


def _estimator():
    x = np.linspace(0.0, 1.0, 40)[:, None]
    return build_model("ridge", {"alpha": 1.0}).fit(x, 2.0 * x[:, 0] + 1.0)


def _save(store: ArtifactStore, **overrides):
    kwargs = {
        "reference": "demo",
        "estimator": _estimator(),
        "model_version": "ridge-v1",
        "provenance": _provenance(),
        "feature_list": ("water_level_lag1", "water_level_roll3_mean"),
        "evaluation_metrics": {"rmse": 0.31, "mae": 0.24},
    }
    kwargs.update(overrides)
    return store.save(**kwargs)


# --- store configuration -----------------------------------------------------


def test_an_unconfigured_store_refuses_to_save():
    store = ArtifactStore(directory=None)
    assert store.is_configured is False
    with pytest.raises(ArtifactError):
        _save(store)


def test_require_directory_reports_the_configured_path(tmp_path):
    target = tmp_path / "nested" / "artifacts"
    store = ArtifactStore(directory=str(target))
    resolved = store.require_directory()
    assert resolved == str(target)
    # It is a path assertion only: nothing is created until a save, so a
    # misconfigured directory cannot create an empty tree on a read-only path.
    assert not target.exists()


def test_saving_creates_the_directory(tmp_path):
    target = tmp_path / "nested" / "artifacts"
    _save(ArtifactStore(directory=str(target)))
    assert target.is_dir()


# --- saving and loading ------------------------------------------------------


def test_save_returns_a_record_with_a_checksum(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    record = _save(store)
    assert record.reference == "demo"
    assert record.format_version == ARTIFACT_FORMAT_VERSION
    assert len(record.artifact_checksum) == 64
    assert record.model_key == "ridge"
    assert record.pickle_used is False


def test_round_trip_reproduces_the_predictions(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    original = _estimator()
    _save(store, estimator=original)
    restored, record = store.load("demo")
    x = np.linspace(0.0, 1.0, 10)[:, None]
    assert np.allclose(restored.predict(x), original.predict(x))
    assert record["model_key"] == "ridge"
    assert record["target"] == "water_level"


def test_saved_file_is_valid_json_with_a_record_and_parameters(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    _save(store)
    payload = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert "record" in payload
    assert "parameters" in payload
    assert payload["record"]["model_key"] == "ridge"


def test_loading_an_unknown_reference_raises(tmp_path):
    with pytest.raises(ArtifactError, match="not found"):
        ArtifactStore(directory=str(tmp_path)).load("does-not-exist")


def test_a_tampered_artifact_fails_its_checksum(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    _save(store)
    path = tmp_path / "demo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["record"]["model_version"] = "ridge-v999-tampered"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(ArtifactError, match="checksum"):
        store.load("demo")


def test_checksum_verification_can_be_waived_explicitly(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    _save(store)
    path = tmp_path / "demo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["record"]["model_version"] = "edited"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    # Bypassing the checksum is a deliberate, named choice, not the default.
    _, record = store.load("demo", verify_checksum=False)
    assert record["model_version"] == "edited"


def test_a_truncated_artifact_fails_to_parse(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    _save(store)
    (tmp_path / "demo.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactError):
        store.load("demo")


def test_an_artifact_from_an_unknown_format_version_is_refused(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    _save(store)
    path = tmp_path / "demo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["record"]["format_version"] = "navya-artifact/v999"
    payload["record"]["artifact_checksum"] = None
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(ArtifactError, match="format version"):
        store.load("demo", verify_checksum=False)


def test_the_checksum_changes_when_the_model_changes(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    first = _save(store, reference="a", model_version="ridge-v1")
    second = _save(store, reference="b", model_version="ridge-v2")
    assert first.artifact_checksum != second.artifact_checksum


# --- the production-readiness refusal ----------------------------------------


def test_a_synthetic_artifact_cannot_be_marked_production_ready(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    with pytest.raises(ArtifactError, match="synthetic"):
        _save(store, mark_production_ready=True)


def test_an_incomplete_provenance_cannot_be_marked_production_ready(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    incomplete = ProvenanceRecord(dataset_type=DATASET_TYPE_REAL, dataset_reference="station-42")
    with pytest.raises(ArtifactError, match="incomplete"):
        _save(store, provenance=incomplete, mark_production_ready=True)


def test_a_real_complete_artifact_can_be_marked_production_ready(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    record = _save(store, provenance=_provenance(DATASET_TYPE_REAL), mark_production_ready=True)
    assert record.production_ready is True
    assert record.disclaimer is None


def test_an_unmarked_real_artifact_is_not_production_ready(tmp_path):
    record = _save(ArtifactStore(directory=str(tmp_path)), provenance=_provenance(DATASET_TYPE_REAL))
    assert record.production_ready is False


# --- labelling ---------------------------------------------------------------


def test_a_synthetic_artifact_carries_the_disclaimer(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    record = _save(store)
    assert SYNTHETIC_DATA_DISCLAIMER in (record.disclaimer or "")
    assert SYNTHETIC_DATA_DISCLAIMER in json.dumps(record.to_dict())


def test_a_real_complete_artifact_carries_no_disclaimer(tmp_path):
    """The label is not decorative: a real, complete artifact gets none."""
    record = _save(
        ArtifactStore(directory=str(tmp_path)),
        provenance=_provenance(DATASET_TYPE_REAL),
        mark_production_ready=True,
    )
    assert record.disclaimer is None


def test_a_synthetic_artifact_notes_its_incomplete_provenance(tmp_path):
    """A synthetic dataset has no licence to cite, so the record is also
    incomplete. Both notices are reported, neither is dropped."""
    record = _save(ArtifactStore(directory=str(tmp_path)))
    assert "INCOMPLETE PROVENANCE" in (record.disclaimer or "")
    assert "dataset_license" in (record.disclaimer or "")


def test_evaluation_metrics_are_carried_into_the_record(tmp_path):
    record = _save(ArtifactStore(directory=str(tmp_path)))
    assert record.evaluation_metrics["rmse"] == pytest.approx(0.31)


def test_record_to_json_is_valid_json(tmp_path):
    record = _save(ArtifactStore(directory=str(tmp_path)))
    assert json.loads(record.to_json())["reference"] == "demo"


def test_describe_summarises_a_stored_artifact(tmp_path):
    store = ArtifactStore(directory=str(tmp_path))
    _save(store)
    text = store.describe("demo")
    assert "ridge" in text
    assert "format" in text.lower()


# --- the optional pickle path ------------------------------------------------


def test_a_sklearn_model_requires_the_pickle_opt_in(tmp_path):
    from app.engines.hydro.models import registry_keys

    if "random_forest" not in registry_keys(available_only=True):
        pytest.skip("scikit-learn is not installed in this environment")
    x = np.linspace(0.0, 1.0, 40)[:, None]
    estimator = build_model("random_forest").fit(x, 2.0 * x[:, 0])
    with pytest.raises(ArtifactError, match="pickle"):
        _save(ArtifactStore(directory=str(tmp_path)), estimator=estimator)


def test_nothing_but_json_is_written_by_default(tmp_path):
    _save(ArtifactStore(directory=str(tmp_path)))
    assert [p.name for p in tmp_path.iterdir()] == ["demo.json"]


# --- the checksum helper -----------------------------------------------------


def test_helper_returns_none_for_an_absent_dataset():
    assert dataset_checksum_or_none(None) is None
    assert dataset_checksum_or_none("/definitely/not/a/file.csv") is None


def test_helper_checksums_a_real_file(tmp_path):
    target = tmp_path / "data.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    assert len(dataset_checksum_or_none(str(target))) == 64
