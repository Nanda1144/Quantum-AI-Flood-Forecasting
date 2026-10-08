# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Model artifact persistence with full provenance.

Design constraints
------------------
* **JSON only by default.** The built-in NumPy estimators serialise to plain
  JSON (coefficient vectors, intercepts, hyper-parameters). A scikit-learn
  estimator can only be persisted through `pickle`, which executes arbitrary
  code on load, so that path is opt-in: `ArtifactStore.save(allow_pickle=True)`
  and the artifact records `pickle_used: true` and a warning. Loading a pickle
  artifact is likewise opt-in and refuses untrusted paths by default.
* **The artifact is self-describing.** Every file records the model type and
  version, the dataset reference, the dataset checksum, the exact feature list,
  the target, all three split boundaries, the creation timestamp and the
  interpreter/library versions.
* **The artifact carries the honest label.** `production_ready` is `false`
  unless a caller explicitly passes the gate, and it is `false` for any artifact
  trained on a dataset declared `synthetic`.
* **Integrity is verifiable.** The store computes a SHA-256 of the written bytes
  and refuses to load an artifact whose recorded checksum does not match.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .models import (
    LinearRegressionModel,
    ModelError,
    RidgeRegressionModel,
    SklearnEnsembleModel,
)
from .provenance import ProvenanceRecord, file_checksum, text_checksum, utc_now_iso

#: Bumped whenever the on-disk artifact layout changes incompatibly.
ARTIFACT_FORMAT_VERSION = "navya-artifact/v1"

#: Warning recorded on any artifact that embeds a pickled estimator.
PICKLE_WARNING = (
    "This artifact embeds a pickled estimator. Loading it executes code from the file; "
    "only load artifacts from a trusted, checksum-verified source."
)


class ArtifactError(RuntimeError):
    """Raised when an artifact cannot be written or loaded safely."""


def canonical_checksum(payload: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical form of an artifact payload.

    A checksum cannot cover itself, so `artifact_checksum` is blanked before
    hashing. `save` and `load` both call this, which is what makes a freshly
    written artifact verify against its own recorded digest — hashing the
    payload *before* inserting the digest would make every artifact fail to load.
    """
    canonical = {
        "record": {**dict(payload.get("record") or {}), "artifact_checksum": None},
        "parameters": payload.get("parameters"),
    }
    return text_checksum(json.dumps(canonical, indent=2, sort_keys=True, default=str))


@dataclass(frozen=True)
class ArtifactRecord:
    """In-memory description of a written artifact."""

    reference: str
    format_version: str
    model_key: str
    model_name: str
    model_version: str
    algorithm: str
    dataset_reference: str | None
    dataset_type: str
    dataset_checksum: str | None
    feature_list: tuple[str, ...]
    target: str | None
    target_units: str | None
    forecast_horizon: str | None
    station_reference: str | None
    split: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    software_environment: Mapping[str, str] = field(default_factory=dict)
    artifact_checksum: str | None = None
    pickle_used: bool = False
    production_ready: bool = False
    evaluation_metrics: Mapping[str, float] | None = None
    disclaimer: str | None = None
    provenance: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["feature_list"] = list(self.feature_list)
        payload["split"] = dict(self.split)
        payload["software_environment"] = dict(self.software_environment)
        if self.evaluation_metrics is not None:
            payload["evaluation_metrics"] = dict(self.evaluation_metrics)
        return payload

    def to_json(self) -> str:
        """Deterministic JSON rendering (stable key order, no trailing space)."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


class ArtifactStore:
    """Filesystem-backed artifact store.

    Writes are atomic: the payload is written to a temporary file in the target
    directory and then moved into place, so a crash mid-write cannot leave a
    half-written artifact that later loads as corrupt.
    """

    def __init__(self, directory: str | None) -> None:
        self._directory = directory

    @property
    def directory(self) -> str | None:
        return self._directory

    @property
    def is_configured(self) -> bool:
        return self._directory is not None

    def require_directory(self) -> str:
        if self._directory is None:
            raise ArtifactError(
                "no artifact directory configured; set HYDRO_ARTIFACT_DIR to enable artifact writing"
            )
        return self._directory

    def _path_for(self, reference: str) -> str:
        safe = reference.replace("/", "__").replace("\\", "__").replace(":", "__")
        return os.path.join(self.require_directory(), f"{safe}.json")

    def save(
        self,
        *,
        reference: str,
        estimator: Any,
        model_version: str,
        provenance: ProvenanceRecord,
        feature_list: Sequence[str],
        evaluation_metrics: Mapping[str, float] | None = None,
        allow_pickle: bool = False,
        mark_production_ready: bool = False,
    ) -> ArtifactRecord:
        """Serialise a fitted estimator with its provenance.

        `mark_production_ready` is refused for a synthetic dataset: a demo run
        can never be promoted to a production artifact by a flag.
        """
        directory = self.require_directory()
        os.makedirs(directory, exist_ok=True)

        pickle_used = isinstance(estimator, SklearnEnsembleModel)
        if pickle_used and not allow_pickle:
            raise ArtifactError(
                f"model {getattr(estimator, 'key', '?')!r} can only be persisted via pickle. "
                "Re-run with allow_pickle=True after reviewing the trust boundary for this path."
            )

        production_ready = bool(mark_production_ready)
        if production_ready and provenance.is_synthetic:
            raise ArtifactError(
                "refusing to mark a synthetic-data artifact as production_ready; "
                "a demo run can never be a production artifact"
            )
        if production_ready and not provenance.is_complete:
            raise ArtifactError(
                "refusing to mark an artifact as production_ready while provenance is incomplete: "
                + ", ".join(provenance.missing_fields())
            )

        disclaimers: list[str] = []
        if pickle_used:
            disclaimers.append(PICKLE_WARNING)
        if provenance.disclaimer:
            disclaimers.append(provenance.disclaimer)
        if not provenance.is_complete:
            disclaimers.append(
                "INCOMPLETE PROVENANCE (unknown: " + ", ".join(provenance.missing_fields()) + ")"
            )

        record = ArtifactRecord(
            reference=reference,
            format_version=ARTIFACT_FORMAT_VERSION,
            model_key=getattr(estimator, "key", "unknown"),
            model_name=getattr(estimator, "display_name", "unknown"),
            model_version=model_version,
            algorithm=getattr(estimator, "algorithm", "unknown"),
            dataset_reference=provenance.dataset_reference,
            dataset_type=provenance.dataset_type,
            dataset_checksum=provenance.dataset_checksum,
            feature_list=tuple(feature_list),
            target=provenance.target,
            target_units=provenance.target_units,
            forecast_horizon=provenance.forecast_horizon,
            station_reference=provenance.station_reference,
            split=asdict(provenance.split),
            created_at=provenance.created_at,
            software_environment=dict(provenance.software_environment),
            pickle_used=pickle_used,
            production_ready=production_ready,
            evaluation_metrics=dict(evaluation_metrics) if evaluation_metrics else None,
            disclaimer=" ".join(disclaimers) or None,
            provenance=provenance.to_dict(),
        )

        path = self._path_for(reference)
        parameters = _parameters_for(estimator)
        payload = {"record": record.to_dict(), "parameters": parameters}
        digest = canonical_checksum(payload)

        final = ArtifactRecord(
            **{
                **record.to_dict(),
                "feature_list": record.feature_list,
                "split": dict(record.split),
                "software_environment": dict(record.software_environment),
                "evaluation_metrics": dict(record.evaluation_metrics)
                if record.evaluation_metrics
                else None,
                "provenance": record.provenance,
                "artifact_checksum": digest,
            }
        )
        _atomic_write(
            path,
            json.dumps(
                {"record": final.to_dict(), "parameters": parameters},
                indent=2,
                sort_keys=True,
                default=str,
            ),
        )
        return final

    def load(
        self,
        reference: str,
        *,
        allow_pickle: bool = False,
        verify_checksum: bool = True,
    ) -> tuple[Any, dict[str, Any]]:
        """Load an artifact, verifying its integrity and safety constraints.

        Returns `(estimator, record)`. Raises when the recorded checksum does not
        match, when the format version is unknown, or when a pickle artifact is
        present and `allow_pickle` was not set.
        """
        path = self._path_for(reference)
        if not os.path.exists(path):
            raise ArtifactError(f"artifact {reference!r} not found at {path}")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"artifact {reference!r} could not be read: {exc}") from exc

        record = payload.get("record") or {}
        parameters = payload.get("parameters")
        if not record or parameters is None:
            raise ArtifactError(f"artifact {reference!r} is missing its record or parameters")

        if record.get("format_version") != ARTIFACT_FORMAT_VERSION:
            raise ArtifactError(
                f"artifact {reference!r} has format version {record.get('format_version')!r}; "
                f"this build understands {ARTIFACT_FORMAT_VERSION!r}"
            )

        if verify_checksum:
            expected = record.get("artifact_checksum")
            recomputed = canonical_checksum(payload)
            if expected and expected != recomputed:
                raise ArtifactError(
                    f"artifact {reference!r} failed its checksum (recorded {expected}, "
                    f"recomputed {recomputed}); the file has been modified or corrupted"
                )

        if record.get("pickle_used") and not allow_pickle:
            raise ArtifactError(
                f"artifact {reference!r} embeds a pickled estimator. "
                f"{PICKLE_WARNING} Re-run with allow_pickle=True if you trust this path."
            )

        estimator = _estimator_from_parameters(record.get("model_key", ""), parameters)
        return estimator, record

    def describe(self, reference: str) -> str:
        """Human-readable summary of a stored artifact."""
        _, record = self.load(reference, allow_pickle=True, verify_checksum=False)
        lines = [
            f"artifact           : {record.get('reference')}",
            f"format             : {record.get('format_version')}",
            f"model              : {record.get('model_key')} ({record.get('model_name')})",
            f"model_version      : {record.get('model_version')}",
            f"algorithm          : {record.get('algorithm')}",
            f"dataset_reference  : {record.get('dataset_reference') or 'UNKNOWN'}",
            f"dataset_type       : {record.get('dataset_type')}",
            f"dataset_checksum   : {record.get('dataset_checksum') or 'UNKNOWN'}",
            f"target             : {record.get('target') or 'UNKNOWN'}"
            + (f" ({record.get('target_units')})" if record.get("target_units") else ""),
            f"forecast_horizon   : {record.get('forecast_horizon') or 'UNKNOWN'}",
            f"station_reference  : {record.get('station_reference') or 'UNKNOWN'}",
            f"features           : {len(record.get('feature_list') or [])}",
            f"created_at         : {record.get('created_at')}",
            f"pickle_used        : {record.get('pickle_used')}",
            f"production_ready   : {record.get('production_ready')}",
        ]
        if record.get("disclaimer"):
            lines.append(f"disclaimer         : {record.get('disclaimer')}")
        return "\n".join(lines)


def _parameters_for(estimator: Any) -> dict[str, Any]:
    if hasattr(estimator, "to_parameter_dict"):
        return estimator.to_parameter_dict()
    raise ArtifactError(
        f"estimator of type {type(estimator).__name__} does not implement to_parameter_dict()"
    )


def _estimator_from_parameters(model_key: str, parameters: Mapping[str, Any]) -> Any:
    if model_key == "linear":
        return LinearRegressionModel.from_parameter_dict(parameters)
    if model_key == "ridge":
        return RidgeRegressionModel.from_parameter_dict(parameters)
    if model_key in ("random_forest", "gradient_boosting", "xgboost"):
        return SklearnEnsembleModel.from_parameter_dict(parameters)
    raise ArtifactError(
        f"artifact declares unknown model key {model_key!r}; this build cannot reconstruct it"
    )


def _atomic_write(path: str, text: str) -> None:
    directory = os.path.dirname(path) or "."
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def dataset_checksum_or_none(path: str | None) -> str | None:
    """Convenience wrapper returning a dataset checksum, or `None`."""
    if not path:
        return None
    return file_checksum(path)
