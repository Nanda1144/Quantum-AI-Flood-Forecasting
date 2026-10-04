# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Provenance records for datasets, splits, models and forecasts.

Every number the platform publishes has to be traceable back to a dataset, a
target, a unit, a split and a model version. This module is the single place
those facts are captured, and it is deliberately incapable of inventing any of
them: an unknown value stays `None` and is serialised as JSON `null`.

Two disclaimers are first-class fields rather than comments:

* `dataset_type` — `real`, `synthetic` or `unknown`. Metrics derived from a
  `synthetic` dataset are never reported as production results.
* `disclaimer` — free text that travels with the record (e.g. the synthetic-data
  warning, or the note that a flood-stage policy is still pending).
"""

from __future__ import annotations

import hashlib
import platform
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

#: Value used whenever a fact is genuinely not known. Never substituted with a
#: plausible-looking constant.
UNKNOWN = None

#: Canonical dataset-type values, matching `config.DATASET_TYPES`.
DATASET_TYPE_REAL = "real"
DATASET_TYPE_SYNTHETIC = "synthetic"
DATASET_TYPE_UNKNOWN = "unknown"

#: The mandatory data warning, verbatim. Every artifact, report, payload and log
#: line that references non-real data must carry this exact sentence — the
#: platform README requires the wording, not merely the meaning, so it lives in
#: one constant and a test asserts it byte-for-byte.
SYNTHETIC_DATA_DISCLAIMER = (
    "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
    "HYDROLOGICAL OBSERVATION DATA."
)
SYNTHETIC_METRIC_DISCLAIMER = (
    "synthetic/demo evaluation only — not a production or research result"
)
#: The parallel warning for data whose origin has not been established at all.
#: Unknown is not the same as synthetic — the numbers may well be real — but they
#: cannot be shown as a result until the source is supplied.
UNVERIFIED_DATA_DISCLAIMER = (
    "Dataset source is UNKNOWN. Treat these values as UNVERIFIED: they must not be "
    "presented as a real observation, a measurement, or a result until the dataset "
    "source, licence and provenance are supplied."
)
PENDING_THRESHOLD_DISCLAIMER = (
    "Flood-stage threshold policy is PENDING. Risk bands produced without an "
    "approved threshold are demo values and carry no official meaning."
)

_CHUNK_SIZE = 1 << 20


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a trailing `Z`."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_checksum(path: str) -> str | None:
    """SHA-256 of a file, or `None` when the file cannot be read.

    Returning `None` (rather than a placeholder digest) is deliberate: an absent
    checksum must be visible as absent, not as a value that looks verified.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def text_checksum(text: str) -> str:
    """SHA-256 of a UTF-8 string. Used to fingerprint an in-memory frame."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def software_environment() -> dict[str, str]:
    """Interpreter/platform facts recorded next to every artifact.

    Library versions are included when the library is importable and omitted
    otherwise — a missing dependency must not be recorded as a version.
    """
    env: dict[str, str] = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.system(),
    }
    for name in ("numpy", "pandas", "sklearn"):
        env[name] = _module_version(name)
    return env


def _module_version(name: str) -> str:
    try:
        module = __import__(name)
    except ImportError:
        return "not installed"
    return str(getattr(module, "__version__", "unknown"))


@dataclass(frozen=True)
class SplitBoundaries:
    """Contiguous, chronologically ordered split boundaries.

    The boundaries are the first and last timestamp of each split. They are
    recorded so a reviewer can confirm that validation and test periods start
    after the training period ended — the property that makes the evaluation
    honest.
    """

    train_start: str | None = None
    train_end: str | None = None
    validation_start: str | None = None
    validation_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    train_rows: int | None = None
    validation_rows: int | None = None
    test_rows: int | None = None

    def is_ordered(self) -> bool:
        """True when every recorded boundary is chronologically increasing.

        Returns `True` for an entirely unknown record so an incomplete
        provenance is never reported as a *disordered* one; callers that need a
        definite answer must supply the boundaries.
        """
        pairs = [
            (self.train_start, self.train_end),
            (self.validation_start, self.validation_end),
            (self.test_start, self.test_end),
        ]
        known = [(s, e) for s, e in pairs if s is not None and e is not None]
        if not known:
            return True
        parsed: list[tuple[datetime, datetime]] = []
        for start, end in known:
            parsed.append((_parse(start), _parse(end)))
        for start, end in parsed:
            if end < start:
                return False
        return all(previous[1] < following[0] for previous, following in zip(parsed, parsed[1:]))


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ProvenanceRecord:
    """Immutable provenance for one trained model / evaluation / forecast.

    All fields default to `None` (unknown) except the two disclaimer fields,
    which default to empty text. Constructing a record therefore never requires
    a value the caller does not actually have.
    """

    # --- dataset -----------------------------------------------------------
    dataset_reference: str | None = None
    dataset_type: str = DATASET_TYPE_UNKNOWN
    dataset_license: str | None = None
    dataset_checksum: str | None = None
    sampling_interval: str | None = None
    # --- target ------------------------------------------------------------
    target: str | None = None
    target_units: str | None = None
    forecast_horizon: str | None = None
    station_reference: str | None = None
    # --- model -------------------------------------------------------------
    feature_list: tuple[str, ...] = ()
    split: SplitBoundaries = field(default_factory=SplitBoundaries)
    model_name: str | None = None
    model_version: str | None = None
    artifact_reference: str | None = None
    # --- bookkeeping -------------------------------------------------------
    created_at: str = field(default_factory=utc_now_iso)
    software_environment: Mapping[str, str] = field(default_factory=software_environment)
    disclaimer: str | None = None
    evaluation_metrics: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if self.dataset_type not in (DATASET_TYPE_REAL, DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN):
            raise ValueError(
                "dataset_type must be one of "
                f"{DATASET_TYPE_REAL!r}, {DATASET_TYPE_SYNTHETIC!r}, {DATASET_TYPE_UNKNOWN!r}"
            )
        # The warning is a constructor invariant, not a caller obligation.
        # `provenance_from_config` attaches it, but that is one call site: any
        # other code path that builds a record directly would otherwise produce
        # a synthetic record that silently carries no warning, and a warning
        # that depends on every caller remembering is a warning that will be
        # forgotten. Real data gets none, so a genuine forecast is not
        # dismissed as fake.
        if not (self.disclaimer and self.disclaimer.strip()):
            if self.dataset_type == DATASET_TYPE_SYNTHETIC:
                object.__setattr__(self, "disclaimer", SYNTHETIC_DATA_DISCLAIMER)
            elif self.dataset_type == DATASET_TYPE_UNKNOWN:
                object.__setattr__(self, "disclaimer", UNVERIFIED_DATA_DISCLAIMER)

    # --- derived labels ----------------------------------------------------

    @property
    def is_synthetic(self) -> bool:
        """True when the underlying dataset was declared synthetic."""
        return self.dataset_type == DATASET_TYPE_SYNTHETIC

    @property
    def metrics_label(self) -> str:
        """The label that must accompany any metric from this provenance."""
        return SYNTHETIC_METRIC_DISCLAIMER if self.is_synthetic else "measured evaluation"

    @property
    def is_complete(self) -> bool:
        """True when no honesty-critical field is unknown."""
        required = (
            self.dataset_reference,
            self.dataset_license,
            self.dataset_checksum,
            self.sampling_interval,
            self.target,
            self.target_units,
            self.forecast_horizon,
            self.station_reference,
            self.model_name,
            self.model_version,
        )
        return all(value not in (None, "") for value in required)

    def missing_fields(self) -> tuple[str, ...]:
        """Names of the honesty-critical fields that are still unknown."""
        checks = {
            "dataset_reference": self.dataset_reference,
            "dataset_license": self.dataset_license,
            "dataset_checksum": self.dataset_checksum,
            "sampling_interval": self.sampling_interval,
            "target": self.target,
            "target_units": self.target_units,
            "forecast_horizon": self.forecast_horizon,
            "station_reference": self.station_reference,
            "model_name": self.model_name,
            "model_version": self.model_version,
        }
        return tuple(name for name, value in checks.items() if value in (None, ""))

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable mapping. Unknown values are emitted as `null`."""
        payload = asdict(self)
        payload["feature_list"] = list(self.feature_list)
        # `split` is typed as `SplitBoundaries`, but a record rebuilt from a
        # serialised one - which is what Phase 6 does when it carries a forecast's
        # provenance forward - carries a plain mapping instead, because that is what
        # came off the wire. Both are accepted here. `asdict()` on a mapping raises
        # `TypeError`, and a serialiser that crashes on valid input is worse than one
        # that has to handle two shapes.
        payload["split"] = asdict(self.split) if is_dataclass(self.split) else dict(self.split)
        payload["software_environment"] = dict(self.software_environment)
        if self.evaluation_metrics is not None:
            payload["evaluation_metrics"] = dict(self.evaluation_metrics)
        payload["is_synthetic"] = self.is_synthetic
        payload["metrics_label"] = self.metrics_label
        payload["is_complete"] = self.is_complete
        payload["missing_fields"] = list(self.missing_fields())
        return payload

    def with_metrics(self, metrics: Mapping[str, float]) -> "ProvenanceRecord":
        """Return a copy carrying the measured evaluation metrics."""
        return ProvenanceRecord(**{**asdict_shallow(self), "evaluation_metrics": dict(metrics)})


def asdict_shallow(record: ProvenanceRecord) -> dict[str, Any]:
    """Top-level field mapping that keeps nested dataclasses intact."""
    return {
        "dataset_reference": record.dataset_reference,
        "dataset_type": record.dataset_type,
        "dataset_license": record.dataset_license,
        "dataset_checksum": record.dataset_checksum,
        "sampling_interval": record.sampling_interval,
        "target": record.target,
        "target_units": record.target_units,
        "forecast_horizon": record.forecast_horizon,
        "station_reference": record.station_reference,
        "feature_list": record.feature_list,
        "split": record.split,
        "model_name": record.model_name,
        "model_version": record.model_version,
        "artifact_reference": record.artifact_reference,
        "created_at": record.created_at,
        "software_environment": record.software_environment,
        "disclaimer": record.disclaimer,
        "evaluation_metrics": record.evaluation_metrics,
    }


def synthetic_disclaimer(dataset_type: str, extra: str | None = None) -> str | None:
    """Return the mandatory disclaimer for a dataset type, or `None` for real data."""
    if dataset_type != DATASET_TYPE_SYNTHETIC:
        return extra
    return f"{SYNTHETIC_DATA_DISCLAIMER} {extra}".strip() if extra else SYNTHETIC_DATA_DISCLAIMER


def combine_disclaimers(*parts: str | None) -> str | None:
    """Join the non-empty disclaimer fragments, or return `None` when empty."""
    joined = " ".join(part.strip() for part in parts if part and part.strip())
    return joined or None


def provenance_from_config(
    config: Any,
    *,
    feature_list: Sequence[str] = (),
    split: SplitBoundaries | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    dataset_checksum: str | None = None,
    disclaimer: str | None = None,
) -> ProvenanceRecord:
    """Build a `ProvenanceRecord` from a `config.HydroConfig`.

    The dataset type is read from the configuration exactly as the supplier
    declared it. When the configuration says `synthetic`, the synthetic-data
    disclaimer is attached automatically so it can never be forgotten.
    """
    combined = combine_disclaimers(
        synthetic_disclaimer(config.dataset.dataset_type),
        disclaimer,
    )
    return ProvenanceRecord(
        dataset_reference=config.dataset.reference,
        dataset_type=config.dataset.dataset_type,
        dataset_license=config.dataset.license,
        dataset_checksum=dataset_checksum,
        sampling_interval=config.dataset.sampling_interval,
        target=config.target.column,
        target_units=config.target.units,
        forecast_horizon=f"{config.target.horizon_hours}h",
        station_reference=config.dataset.station_reference,
        feature_list=tuple(feature_list),
        split=split or SplitBoundaries(),
        model_name=model_name,
        model_version=model_version,
        disclaimer=combined,
    )


def describe_unknowns(provenance: ProvenanceRecord) -> str:
    """One-line, human-readable summary of what is still unknown."""
    missing = provenance.missing_fields()
    if not missing:
        return "provenance complete"
    return "unknown: " + ", ".join(missing)


def format_provenance_lines(provenance: ProvenanceRecord) -> Iterable[str]:
    """Human-readable provenance block for logs and evaluation reports."""
    yield f"dataset_reference : {provenance.dataset_reference or 'UNKNOWN'}"
    yield f"dataset_type      : {provenance.dataset_type}"
    yield f"dataset_license   : {provenance.dataset_license or 'UNKNOWN'}"
    yield f"dataset_checksum  : {provenance.dataset_checksum or 'UNKNOWN'}"
    yield f"sampling_interval : {provenance.sampling_interval or 'UNKNOWN'}"
    yield f"target            : {provenance.target or 'UNKNOWN'}"
    yield f"target_units      : {provenance.target_units or 'UNKNOWN'}"
    yield f"forecast_horizon  : {provenance.forecast_horizon or 'UNKNOWN'}"
    yield f"station_reference : {provenance.station_reference or 'UNKNOWN'}"
    yield f"model             : {provenance.model_name or 'UNKNOWN'} {provenance.model_version or ''}".rstrip()
    yield f"features          : {len(provenance.feature_list)}"
    yield f"created_at        : {provenance.created_at}"
    yield f"metric label      : {provenance.metrics_label}"
    if provenance.disclaimer:
        yield f"disclaimer        : {provenance.disclaimer}"
