# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3's contract, in the shape a model can be fitted on.

Phase 3 hands over `ModelReadyDataset`: a frozen tuple of `FeatureRow`s where
features, targets, identity and metadata are separate fields and an absent value
is `None` rather than a sentinel number. That shape is excellent for auditing and
wrong for arithmetic — an estimator needs a dense matrix, and `None` is not a
number.

This module is the one place that conversion happens, and it is deliberately the
only place. Three rules follow from that.

**Nothing is invented to fill the gap.** Phase 3 leaves a feature absent rather
than guessing. Phase 4 turns an absence into a number only if a policy says how,
and only from *training* rows. The raw matrix — absences intact — is kept
alongside the fitted one so an auditor can still see what was absent.

**The target is never substituted.** `bind_target` resolves the configured target
against what Phase 3 actually built. If the column is missing, the binding is
`available=False` with a reason, and every model in the run reports
`target_unavailable`. No code path anywhere in Phase 4 picks a different column.

**Splits are read, not recomputed.** The split label on each Phase 3 row is the
split. `assemble_dataset` groups by it and never re-slices a timeline.

Everything that scales or imputes reuses `preprocessing.StandardScaler` and
`preprocessing.TrainFittedImputer`, which already refuse to be fitted on anything
other than the training split. Reusing them means the train-only guarantee is a
property of code that predates Phase 4 and is tested there, rather than a promise
made again here.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .feature_pipeline import (
    FEATURE_CONTRACT_VERSION,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
    FeatureDataset,
    FeatureResult,
    ModelReadyDataset,
)
from .model_config import (
    FEATURE_SELECTION_ALL,
    FEATURE_SELECTION_TRAIN_PRESENT,
    IMPUTE_MEDIAN,
    IMPUTE_NONE,
    PERSISTENCE_SOURCE_ANY_PAST,
    PERSISTENCE_SOURCE_POLICIES,
    SCALER_STANDARD,
    ModelConfig,
)
from .preprocessing import StandardScaler, TrainFittedImputer
from .provenance import SplitBoundaries

#: The Phase 4 data prefix for note codes.
DATA_PREFIX = "MODEL_DATA_"

CODE_TARGET_UNAVAILABLE = DATA_PREFIX + "TARGET_UNAVAILABLE"
CODE_TARGET_UNIT_UNKNOWN = DATA_PREFIX + "TARGET_UNIT_NOT_INTERPRETABLE"
CODE_TARGET_NOT_FUTURE = DATA_PREFIX + "TARGET_NOT_STRICTLY_AHEAD"
CODE_FEATURE_DROPPED = DATA_PREFIX + "FEATURE_DROPPED_ABSENT_IN_TRAIN"
CODE_NO_FEATURES = DATA_PREFIX + "NO_FEATURES_REMAINING"
CODE_IMPUTED = DATA_PREFIX + "CELLS_IMPUTED_FROM_TRAIN"
CODE_IMPUTE_NONE = DATA_PREFIX + "IMPUTATION_DISABLED_BY_POLICY"
CODE_SCALER_TRAIN_ONLY = DATA_PREFIX + "SCALER_FITTED_ON_TRAIN_ONLY"
CODE_BASELINE_ROWS_EXCLUDED = DATA_PREFIX + "ROWS_WITHOUT_BASELINE_PREDICTION"

#: There is deliberately no note code for "the sampling step is unknown" or "windows
#: were skipped". `build_sequences` returns an empty `SequenceSet` carrying
#: `step_seconds=None`, and the reason is stated where a reader meets it:
#: `model_training` raises `InsufficientData` naming the missing cadence, and the skip
#: counts live on `SequenceSet` itself. Constants that nothing emitted were removed
#: rather than left exported, because a reader would reasonably expect to find them in
#: `ModelDataset.notes` and would not.


class ModelDataError(RuntimeError):
    """Raised when the Phase 3 contract cannot be turned into matrices."""


@dataclass(frozen=True)
class ModelNote:
    """One statement about what the conversion did or could not do."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _notes(values: Iterable[ModelNote]) -> tuple[ModelNote, ...]:
    """Notes in a stable order, so two identical runs produce identical reports."""
    return tuple(sorted(values, key=lambda note: (note.code, note.message)))


# --------------------------------------------------------------------------- #
# Target binding
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TargetBinding:
    """The Phase 3 target this run predicts, resolved against the real dataset.

    `available` is the load-bearing field. When it is `False` the run reports
    `target_unavailable` for every family; there is no fallback path, by design.
    """

    column: str
    quantity: str
    available: bool
    reason: str | None = None
    units: str | None = None
    unit_understood: bool = False
    horizon_seconds: float | None = None
    horizon_label: str | None = None
    alignment: str | None = None
    #: Phase 3 records whether the target was readable at the prediction instant.
    #: A target that claims to be is a contemporaneous feature, not a forecast
    #: target, so a `True` here is refused rather than trained on.
    available_at_prediction_time: bool | None = None
    entities: tuple[str, ...] = ()
    rows_with_target: int = 0
    rows_without_target: int = 0

    @property
    def usable(self) -> bool:
        """True only when the target exists *and* is genuinely in the future."""
        return (
            self.available
            and self.available_at_prediction_time is False
            and self.horizon_seconds is not None
            and self.horizon_seconds > 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "quantity": self.quantity,
            "available": self.available,
            "usable": self.usable,
            "reason": self.reason,
            "units": self.units,
            "unit_understood": self.unit_understood,
            "horizon_seconds": self.horizon_seconds,
            "horizon_label": self.horizon_label,
            "alignment": self.alignment,
            "available_at_prediction_time": self.available_at_prediction_time,
            "entities": list(self.entities),
            "rows_with_target": self.rows_with_target,
            "rows_without_target": self.rows_without_target,
        }


def bind_target(dataset: FeatureDataset, config: ModelConfig) -> TargetBinding:
    """Resolve the configured target against what Phase 3 actually produced.

    The configured column name comes from Phase 3's own `target_name`, so an
    unbuilt horizon cannot even be spelled. The lookup below therefore asks a
    single question — does this dataset have that column? — and answers it with
    the list of columns it does have when the answer is no.
    """
    column = config.target_columns[0]
    lineage = dict(dataset.target_lineage.get(column) or {})
    built = tuple(dataset.target_columns)
    with_target = [row for row in dataset.rows if row.targets.get(column) is not None]
    entities = tuple(sorted({row.entity for row in with_target}))
    base: dict[str, Any] = {
        "column": column,
        "quantity": config.target_quantity,
        "units": lineage.get("unit"),
        "horizon_seconds": lineage.get("horizon_seconds"),
        "horizon_label": lineage.get("horizon_label"),
        "alignment": lineage.get("alignment"),
        "available_at_prediction_time": lineage.get("available_at_prediction_time"),
        "entities": entities,
        "rows_with_target": len(with_target),
        "rows_without_target": len(dataset.rows) - len(with_target),
    }
    if column not in built:
        return TargetBinding(
            available=False,
            reason=(
                f"Phase 3 built no target column {column!r} for quantity "
                f"{config.target_quantity!r} at horizon(s) {list(config.horizon_labels)}; the "
                f"targets it did build are {list(built) or '(none)'}. Phase 4 does not invent "
                "a target and does not substitute another variable."
            ),
            **base,
        )
    if base["available_at_prediction_time"] is not False:
        return TargetBinding(
            available=True,
            reason=(
                f"target {column!r} does not declare itself strictly after the prediction "
                f"instant (available_at_prediction_time="
                f"{base['available_at_prediction_time']!r}); a target readable at the "
                "prediction instant is a contemporaneous feature, not a forecast target"
            ),
            **base,
        )
    unit = base["units"]
    understood = bool(unit) and unit not in ("UNDETERMINED", "UNKNOWN")
    if unit and not understood:
        return TargetBinding(
            available=True,
            reason=(
                f"target {column!r} is available but its unit is {unit!r}; Phase 3 preserves "
                "that unit rather than converting it, so errors are reported in that unit and "
                "the values are not physically comparable with a converted series"
            ),
            unit_understood=False,
            **base,
        )
    return TargetBinding(available=True, unit_understood=understood, **base)


# --------------------------------------------------------------------------- #
# Per-split matrices
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SplitMatrix:
    """One chronological split, in the shape an estimator consumes.

    `raw_values` and `values` differ only where a policy acted, and both are kept.
    `persistence` holds the naive-baseline prediction for every row, or `NaN` where
    no target value was available at or before the origin under the configured
    policy. It is `NaN` and never `0.0`: a persistence baseline that read "no
    baseline available" as "predict zero" would silently beat every model on a
    target whose natural zero is not its typical value.
    """

    split: str
    feature_names: tuple[str, ...]
    entities: tuple[str, ...]
    #: The entity of each row, in row order. Sequence construction groups on this
    #: rather than assuming a single station, which is what keeps a window from
    #: ever spanning two.
    row_entities: tuple[str, ...]
    origin_instants: tuple[datetime, ...]
    target_instants: tuple[datetime | None, ...]
    #: Absences preserved as `NaN`.
    raw_values: np.ndarray
    #: After the imputation and scaling policies, ready for an estimator.
    values: np.ndarray
    target: np.ndarray
    persistence: np.ndarray
    rows: int
    #: Feature cells this pipeline *replaced*. Under `impute_policy='none'` this is
    #: zero by definition, not the count of cells left absent — a count that means
    #: "absent" under one policy and "replaced" under the other would let a reader
    #: conclude a non-imputing run had filled its gaps.
    imputed_cells: int
    dropped_features: tuple[str, ...] = ()
    #: Rows this split can score on: a target *and* a baseline prediction exist.
    #: Every model uses the same mask, which is what makes the comparison
    #: like-for-like rather than flattering to whoever lost the fewest rows.
    evaluable: int = 0
    #: Per row, every instant any feature in that row read. Carried verbatim from
    #: Phase 3 so the Phase 4 audit can prove the *inputs* it assembled are
    #: point-in-time, rather than taking Phase 3's word for it.
    source_instants: tuple[tuple[datetime, ...], ...] = ()

    @property
    def evaluable_mask(self) -> np.ndarray:
        return np.isfinite(self.target) & np.isfinite(self.persistence)

    def matrices(self) -> tuple[np.ndarray, np.ndarray]:
        """`(X, y)` restricted to evaluable rows, for an evaluation split."""
        mask = self.evaluable_mask
        return self.values[mask], self.target[mask]

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "rows": self.rows,
            "evaluable_rows": self.evaluable,
            "entities": list(self.entities),
            "feature_columns": len(self.feature_names),
            "dropped_features": list(self.dropped_features),
            "imputed_cells": self.imputed_cells,
            "origin_first": _iso(self.origin_instants[0]) if self.origin_instants else None,
            "origin_last": _iso(self.origin_instants[-1]) if self.origin_instants else None,
            "target_first": _iso(self.target_instants[0]) if self.target_instants else None,
            "target_last": _iso(self.target_instants[-1]) if self.target_instants else None,
            "rows_without_baseline_prediction": int((~np.isfinite(self.persistence)).sum()),
        }


@dataclass(frozen=True)
class ModelDataset:
    """Everything one Phase 4 run reads, resolved and immutable."""

    config: ModelConfig
    binding: TargetBinding
    feature_names: tuple[str, ...]
    declared_feature_names: tuple[str, ...]
    dropped_features: Mapping[str, str]
    splits: Mapping[str, SplitMatrix]
    entities: tuple[str, ...]
    bounds: SplitBoundaries
    feature_contract_version: str
    feature_registry_names: tuple[str, ...]
    dataset_reference: str | None
    dataset_license: str | None
    dataset_checksum: str | None
    dataset_type: str
    station_reference: str | None
    is_synthetic: bool
    disclaimer: str | None
    notes: tuple[ModelNote, ...] = ()
    scaler_state: Mapping[str, Any] | None = None
    imputer_state: Mapping[str, Any] | None = None
    #: Series key -> the `Cadence` Phase 3 published. Phase 4 never re-infers a
    #: sampling interval; this is handed through so a sequence window can be sized
    #: in time, and its absence is reported rather than assumed away.
    cadences: Mapping[str, Any] | None = None

    def split(self, name: str) -> SplitMatrix:
        if name not in self.splits:
            raise KeyError(
                f"no {name!r} split in this dataset; available splits: {sorted(self.splits)}"
            )
        return self.splits[name]

    @property
    def train(self) -> SplitMatrix:
        return self.split(SPLIT_TRAIN)

    @property
    def target_column(self) -> str:
        return self.binding.column

    @property
    def target_units(self) -> str | None:
        return self.binding.units

    @property
    def total_rows(self) -> int:
        return sum(part.rows for part in self.splits.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "binding": self.binding.to_dict(),
            "feature_columns": list(self.feature_names),
            "declared_feature_columns": list(self.declared_feature_names),
            "dropped_features": dict(sorted(self.dropped_features.items())),
            "entities": list(self.entities),
            "feature_contract_version": self.feature_contract_version,
            "feature_registry_columns": len(self.feature_registry_names),
            "dataset_reference": self.dataset_reference,
            "dataset_license": self.dataset_license,
            "dataset_checksum": self.dataset_checksum,
            "dataset_type": self.dataset_type,
            "station_reference": self.station_reference,
            "is_synthetic": self.is_synthetic,
            "disclaimer": self.disclaimer,
            "split_bounds": {
                "train_start": self.bounds.train_start,
                "train_end": self.bounds.train_end,
                "validation_start": self.bounds.validation_start,
                "validation_end": self.bounds.validation_end,
                "test_start": self.bounds.test_start,
                "test_end": self.bounds.test_end,
            },
            "splits": {name: part.to_dict() for name, part in sorted(self.splits.items())},
            "scaler": dict(self.scaler_state) if self.scaler_state else None,
            "imputer": dict(self.imputer_state) if self.imputer_state else None,
            "cadence_series": sorted(self.cadences or {}),
            "notes": [note.to_dict() for note in self.notes],
        }

    def describe(self) -> str:
        lines = [
            f"Phase 4 model dataset (feature contract {self.feature_contract_version})",
            f"  target          : {self.binding.column}"
            + (f" [{self.binding.units}]" if self.binding.units else " [unit unknown]"),
            f"  horizon         : {self.binding.horizon_label}",
            f"  usable          : {self.binding.usable}",
            f"  feature columns : {len(self.feature_names)}"
            f" of {len(self.declared_feature_names)} declared",
            f"  rows            : {self.total_rows} across {len(self.splits)} split(s)",
        ]
        for name in sorted(self.splits):
            part = self.splits[name]
            lines.append(
                f"    {name:<11}: rows={part.rows:<6} evaluable={part.evaluable:<6}"
                f" imputed_cells={part.imputed_cells}"
            )
        lines.append(f"  synthetic       : {self.is_synthetic}")
        if self.disclaimer:
            lines.append(f"  disclaimer      : {self.disclaimer}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _numeric_matrix(rows: Sequence[Any], names: Sequence[str]) -> np.ndarray:
    """Dense `float64` matrix with `None` preserved as `NaN`."""
    if not rows:
        return np.zeros((0, len(names)), dtype="float64")
    out = np.full((len(rows), len(names)), np.nan, dtype="float64")
    for index, row in enumerate(rows):
        values = row.values
        for column, name in enumerate(names):
            raw = values.get(name)
            if raw is not None:
                out[index, column] = float(raw)
    return out


def _target_vector(rows: Sequence[Any], column: str) -> np.ndarray:
    out = np.full(len(rows), np.nan, dtype="float64")
    for index, row in enumerate(rows):
        raw = row.targets.get(column)
        if raw is not None:
            out[index] = float(raw)
    return out


def persistence_predictions(
    rows: Sequence[Any],
    column: str,
    *,
    policy: str,
    pool: Sequence[Any] | None = None,
) -> np.ndarray:
    """The naive baseline: the latest target value read at or before each origin.

    `prediction(t + h) = latest known target value`, taken from the target series
    itself rather than from a new feature column, because Phase 3's target at
    origin ``t - h`` *is* the observation at ``t``. That keeps the baseline inside
    the Phase 3 contract without asking Phase 3 for a zero-horizon target.

    Causal by construction: the search accepts only target instants ``<= origin``,
    and a row's own target is strictly after its origin, so a row can never be its
    own baseline. Entity isolation is absolute — the search pool is per entity, so
    station A's baseline never reads station B.

    `policy` decides which rows may act as the pool:

    * ``same_split_only`` — only rows from the queried row's own split.
    * ``any_past_split`` — every row in `pool` whose target instant is at or
      before the origin. Everything involved is in the past at prediction time, so
      this is causal too; it is opt-in because it reaches across a boundary a
      reader may reasonably expect to be sealed.
    """
    if policy not in PERSISTENCE_SOURCE_POLICIES:
        raise ModelDataError(
            f"unknown persistence policy {policy!r}; the implemented policies are "
            f"{list(PERSISTENCE_SOURCE_POLICIES)}. An unrecognised policy is refused rather "
            "than treated as the default, because the two policies disagree about whether a "
            "baseline may read across a split boundary - and the whole comparison rests on "
            "knowing which one was used."
        )

    sources = list(pool if pool is not None else rows)
    by_entity: dict[str, list[tuple[datetime, float, str]]] = {}
    for row in sources:
        value = row.targets.get(column)
        instant = row.target_instants.get(column)
        if value is None or instant is None:
            continue
        by_entity.setdefault(row.entity, []).append((instant, float(value), row.split))

    out = np.full(len(rows), np.nan, dtype="float64")
    for index, row in enumerate(rows):
        candidates = by_entity.get(row.entity, [])
        if policy == PERSISTENCE_SOURCE_ANY_PAST:
            usable = list(candidates)
        else:
            usable = [entry for entry in candidates if entry[2] == row.split]
        if not usable:
            continue
        usable.sort(key=lambda entry: (entry[0], entry[2]))
        position = bisect.bisect_right([entry[0] for entry in usable], row.instant)
        if position == 0:
            continue
        out[index] = usable[position - 1][1]
    return out


def _select_features(
    raw_train: np.ndarray, declared: Sequence[str], policy: str
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Pick the columns a model may see, decided on training rows alone."""
    if policy == FEATURE_SELECTION_ALL:
        return tuple(declared), {}
    kept: list[str] = []
    dropped: dict[str, str] = {}
    for column, name in enumerate(declared):
        if np.isfinite(raw_train[:, column]).any():
            kept.append(name)
        else:
            dropped[name] = (
                "no finite value in the training split; the dataset declares the feature but "
                "the data behind it does not exist for any entity"
            )
    return tuple(kept), dropped


def _fit_transforms(
    frames: Mapping[str, np.ndarray],
    names: Sequence[str],
    config: ModelConfig,
) -> tuple[
    dict[str, np.ndarray],
    dict[str, int],
    StandardScaler | None,
    TrainFittedImputer | None,
]:
    """Apply the imputation then scaling policies, fitting only on training rows.

    Order matters and is fixed: impute, then scale. A scaler fitted on missing
    cells would either skip them (a `NaN` mean) or fill them with something that
    has not been reported. Imputing first means every fitted statistic is a
    statistic of a stated value rather than of an artefact of the pipeline.
    """
    train = frames[SPLIT_TRAIN]
    out: dict[str, np.ndarray] = {}
    imputed: dict[str, int] = {}

    if config.impute_policy == IMPUTE_NONE:
        # Nothing is imputed, so nothing is counted as imputed. Counting the cells
        # that *stay* absent here would make `imputed_cells` mean "absent" under one
        # policy and "replaced" under the other, and a reader summing the field
        # across runs would conclude that a run configured not to impute had filled
        # its gaps. How many cells remain absent is visible in the matrix itself.
        for name, matrix in frames.items():
            imputed[name] = 0
            out[name] = matrix
        return out, imputed, None, None

    frame = pd.DataFrame(train, columns=list(names))
    imputer = TrainFittedImputer(strategy=IMPUTE_MEDIAN).fit(
        frame, list(names), split_label=SPLIT_TRAIN
    )
    for name, matrix in frames.items():
        block = pd.DataFrame(matrix, columns=list(names))
        imputed[name] = int(np.count_nonzero(~np.isfinite(matrix)))
        out[name] = imputer.transform(block, list(names)).to_numpy(dtype="float64")

    if config.scaler_policy != SCALER_STANDARD:
        return out, imputed, None, imputer

    scaler = StandardScaler().fit(
        pd.DataFrame(out[SPLIT_TRAIN], columns=list(names)),
        list(names),
        split_label=SPLIT_TRAIN,
    )
    for name in list(out):
        out[name] = scaler.transform_matrix(out[name], list(names))
    return out, imputed, scaler, imputer


def _with_evaluable(matrix: SplitMatrix) -> SplitMatrix:
    from dataclasses import replace as _replace

    return _replace(matrix, evaluable=int(np.count_nonzero(matrix.evaluable_mask)))


def _descriptor_field(dataset: FeatureDataset, name: str) -> str | None:
    descriptor = dataset.dataset
    if descriptor is None:
        return None
    return getattr(descriptor, name, None)


def _bound(raw: Mapping[str, Any], split: str, key: str) -> str | None:
    block = raw.get(split)
    if not isinstance(block, Mapping):
        return None
    value = block.get(key)
    return str(value) if value else None


def _count(raw: Mapping[str, Any], split: str) -> int | None:
    block = raw.get(split)
    if not isinstance(block, Mapping):
        return None
    rows = block.get("rows")
    return int(rows) if isinstance(rows, int) else None


def _bounds(dataset: FeatureDataset) -> SplitBoundaries:
    """Phase 3's split bounds, in Phase 1's provenance shape."""
    raw = dict(dataset.split_bounds or {})
    if not raw:
        return SplitBoundaries()
    return SplitBoundaries(
        train_start=_bound(raw, SPLIT_TRAIN, "origin_first"),
        train_end=_bound(raw, SPLIT_TRAIN, "origin_last"),
        validation_start=_bound(raw, SPLIT_VALIDATION, "origin_first"),
        validation_end=_bound(raw, SPLIT_VALIDATION, "origin_last"),
        test_start=_bound(raw, SPLIT_TEST, "origin_first"),
        test_end=_bound(raw, SPLIT_TEST, "origin_last"),
        train_rows=_count(raw, SPLIT_TRAIN),
        validation_rows=_count(raw, SPLIT_VALIDATION),
        test_rows=_count(raw, SPLIT_TEST),
    )


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def assemble_dataset(
    source: FeatureDataset | ModelReadyDataset | FeatureResult,
    config: ModelConfig,
    *,
    cadences: Mapping[str, Any] | None = None,
) -> ModelDataset:
    """Turn the Phase 3 contract into per-split matrices for one configuration.

    `source` accepts the three things a caller might have to hand: the raw
    dataset, the explicit contract, or the whole Phase 3 result. All three carry
    the same rows; accepting all of them removes a reason to reach around the
    contract.

    `cadences` is the Phase 3 report's `Cadence` mapping. It is optional and only
    sequence families need it, because only they convert a row count into a span
    of time. When it is absent the window length in time is unknowable, and
    `build_sequences` says so instead of assuming an hour.
    """
    if isinstance(source, FeatureResult):
        dataset = source.dataset
    elif isinstance(source, ModelReadyDataset):
        dataset = source.dataset
    else:
        dataset = source

    notes: list[ModelNote] = []
    binding = bind_target(dataset, config)
    if not binding.available:
        notes.append(ModelNote(CODE_TARGET_UNAVAILABLE, binding.reason or "target unavailable"))
    elif binding.available_at_prediction_time is not False:
        notes.append(
            ModelNote(
                CODE_TARGET_NOT_FUTURE,
                binding.reason or "the target is not strictly ahead of the prediction origin",
            )
        )
    if binding.available and binding.units and not binding.unit_understood:
        notes.append(
            ModelNote(
                CODE_TARGET_UNIT_UNKNOWN,
                f"target unit {binding.units!r} is not interpretable; reported errors stay in "
                "that unit and are not comparable with a converted series",
            )
        )

    declared = tuple(dataset.feature_columns)
    column = binding.column
    per_split_rows = {name: dataset.by_split(name) for name in sorted(dataset.split_counts)}

    raw = {name: _numeric_matrix(rows, declared) for name, rows in per_split_rows.items()}
    targets = {name: _target_vector(rows, column) for name, rows in per_split_rows.items()}

    if SPLIT_TRAIN not in raw:
        raise ModelDataError(
            f"the Phase 3 dataset has no {SPLIT_TRAIN!r} split; a model cannot be fitted "
            f"without one. Available splits: {sorted(raw)}"
        )

    common = {
        "config": config,
        "binding": binding,
        "declared_feature_names": declared,
        "feature_registry_names": declared,
        "entities": tuple(sorted({row.entity for row in dataset.rows})),
        "bounds": _bounds(dataset),
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "dataset_reference": _descriptor_field(dataset, "reference"),
        "dataset_license": _descriptor_field(dataset, "license"),
        "dataset_checksum": _descriptor_field(dataset, "checksum"),
        "dataset_type": dataset.dataset.dataset_type if dataset.dataset else "unknown",
        "station_reference": _descriptor_field(dataset, "station_reference"),
        "is_synthetic": dataset.is_synthetic,
        "disclaimer": dataset.disclaimer(),
        "cadences": dict(cadences) if cadences else None,
    }

    feature_names, dropped = _select_features(
        raw[SPLIT_TRAIN], declared, config.feature_selection
    )
    for name in sorted(dropped):
        notes.append(ModelNote(CODE_FEATURE_DROPPED, f"{name}: {dropped[name]}"))

    if not feature_names:
        notes.append(
            ModelNote(
                CODE_NO_FEATURES,
                "no declared feature has a finite value in the training split, so no model can "
                "be fitted; the dataset was not modified to make one possible",
            )
        )
        return ModelDataset(
            **common,
            feature_names=(),
            dropped_features=dropped,
            splits={},
            notes=_notes(notes),
        )

    kept = [declared.index(name) for name in feature_names]
    trimmed = {name: matrix[:, kept] for name, matrix in raw.items()}
    fitted, imputed, scaler, imputer = _fit_transforms(trimmed, feature_names, config)

    if scaler is not None:
        notes.append(
            ModelNote(
                CODE_SCALER_TRAIN_ONLY,
                f"standard scaler fitted on {scaler.fitted_rows} training row(s) only; "
                "validation and test statistics never reach it",
            )
        )
    total_imputed = sum(imputed.values())
    if total_imputed:
        notes.append(
            ModelNote(
                CODE_IMPUTED,
                f"{total_imputed} absent feature cell(s) replaced by the training median of "
                "their column; Phase 3 leaves absences intact and this is the only fill",
            )
        )
    elif config.impute_policy == IMPUTE_NONE:
        # Recorded rather than left silent: a run that imputed nothing and a run over
        # a gap-free dataset are different experiments, and only this note separates
        # them. The count is of cells *still* absent, so it is labelled as such.
        still_absent = sum(
            int(np.count_nonzero(~np.isfinite(values))) for values in fitted.values()
        )
        notes.append(
            ModelNote(
                CODE_IMPUTE_NONE,
                f"imputation is disabled by policy '{IMPUTE_NONE}': nothing was replaced and "
                f"{still_absent} cell(s) remain absent as NaN, so an estimator must handle them "
                "or the run cannot proceed",
            )
        )

    all_rows = [row for name in sorted(per_split_rows) for row in per_split_rows[name]]
    splits: dict[str, SplitMatrix] = {}
    for name in sorted(per_split_rows):
        rows = per_split_rows[name]
        matrix = SplitMatrix(
            split=name,
            feature_names=feature_names,
            entities=tuple(sorted({row.entity for row in rows})),
            row_entities=tuple(row.entity for row in rows),
            origin_instants=tuple(row.instant for row in rows),
            target_instants=tuple(row.target_instants.get(column) for row in rows),
            raw_values=trimmed[name],
            values=fitted[name],
            target=targets[name],
            persistence=persistence_predictions(
                rows, column, policy=config.persistence_source, pool=all_rows
            ),
            rows=len(rows),
            imputed_cells=imputed.get(name, 0),
            dropped_features=tuple(sorted(dropped)),
            source_instants=tuple(tuple(row.source_instants) for row in rows),
        )
        splits[name] = _with_evaluable(matrix)
        missing = int(np.count_nonzero(~np.isfinite(splits[name].persistence)))
        if missing:
            notes.append(
                ModelNote(
                    CODE_BASELINE_ROWS_EXCLUDED,
                    f"{name}: {missing} row(s) have no baseline prediction under policy "
                    f"{config.persistence_source!r} and are excluded from every model's score "
                    "on this split so the comparison stays like-for-like",
                )
            )

    return ModelDataset(
        **common,
        feature_names=feature_names,
        dropped_features=dropped,
        splits=splits,
        notes=_notes(notes),
        scaler_state=scaler.state() if scaler is not None else None,
        imputer_state=imputer.state() if imputer is not None else None,
    )


# --------------------------------------------------------------------------- #
# Causal sequences
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SequenceSet:
    """Causal lookback windows for one split, with the skips accounted for.

    A window is `(origin - (lookback - 1) * step, origin]` of one entity's rows.
    It opens on the left and closes on the origin, so it can never contain `t + 1`
    through `t + H`; those are the target, not the input. Windows never span
    entities and never span splits, so no window can stitch station A to station B
    or reach back into a previous split's rows.
    """

    split: str
    lookback: int
    step_seconds: float | None
    feature_names: tuple[str, ...]
    windows: np.ndarray
    targets: np.ndarray
    entities: tuple[str, ...]
    origin_instants: tuple[datetime, ...]
    #: Per window, the instants it contains, oldest first. Kept so the leakage
    #: audit can check causality against real timestamps instead of trusting the
    #: construction that produced them.
    window_instants: tuple[tuple[datetime, ...], ...] = ()
    #: Per window, the single entity it belongs to.
    window_entities: tuple[str, ...] = ()
    #: Per window, the distinct entities of the rows it was actually assembled from,
    #: as the builder found them. Exactly one today, because the builder walks one
    #: entity's rows at a time - and that is the point. Recording what the builder
    #: *found* rather than what it *meant* is what lets the leakage audit fail on a
    #: window that really did mix two stations, instead of restating the intent.
    window_entity_sets: tuple[tuple[str, ...], ...] = ()
    #: Rows left out because `restrict` masked them, rather than because they lacked
    #: history or a target. Counted apart so that
    #: `samples + skipped_insufficient_history + skipped_missing_target
    #: + restricted_rows == matrix.rows` holds exactly, and no row leaves the
    #: accounting without being named.
    restricted_rows: int = 0
    skipped_insufficient_history: int = 0
    skipped_missing_target: int = 0

    @property
    def samples(self) -> int:
        return int(self.windows.shape[0])

    def accounted_for(self) -> int:
        """Every row of the source matrix, named by whichever bucket it fell into."""
        return (
            self.samples
            + self.skipped_insufficient_history
            + self.skipped_missing_target
            + self.restricted_rows
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "lookback": self.lookback,
            "step_seconds": self.step_seconds,
            "feature_columns": len(self.feature_names),
            "samples": self.samples,
            "entities": sorted(set(self.entities)),
            "skipped_insufficient_history": self.skipped_insufficient_history,
            "skipped_missing_target": self.skipped_missing_target,
        }


def resolve_step_seconds(
    cadences: Mapping[str, Any] | None,
    entities: Sequence[str],
    quantity: str,
) -> float | None:
    """The sampling step, taken from the cadence Phase 3 already established.

    Phase 2 owns cadence inference and Phase 3 published the answer; Phase 4 reads
    it. It does not re-derive it from row spacing, because a second inference
    could disagree with the first and a window sized from the wrong step is a
    window of the wrong length.

    The lookup prefers the target quantity's own series (`entity|quantity`) and
    falls back to any series Phase 3 reported for that entity. `None` means the
    step is genuinely unknown, and the caller reports `insufficient_data` naming
    the reason rather than assuming an hour.
    """
    if not cadences:
        return None
    for entity in entities:
        exact = cadences.get(f"{entity}|{quantity}")
        seconds = getattr(exact, "seconds", None) if exact is not None else None
        if seconds and seconds > 0:
            return float(seconds)
    for entity in entities:
        for series, cadence in sorted(cadences.items()):
            if not str(series).startswith(f"{entity}|"):
                continue
            seconds = getattr(cadence, "seconds", None)
            if seconds and seconds > 0:
                return float(seconds)
    return None


def build_sequences(
    matrix: SplitMatrix,
    lookback: int,
    step_seconds: float | None,
    *,
    restrict: np.ndarray | None = None,
) -> SequenceSet:
    """Build causal windows from one split matrix.

    `step_seconds is None` means the sampling interval was never established, so
    the length of a `lookback`-row window in time is unknown. Rather than assume
    one hour — the exact assumption Phase 2 and Phase 3 both refuse to make —
    this returns an empty set with the reason, and the caller reports
    `insufficient_data`.

    `restrict` is a per-row boolean mask selecting which rows may *end* a window.
    The window still draws its history from every row in the split, so masking a
    row out does not truncate another row's history. It exists so a sequence
    model is scored on exactly the rows the comparison mask selected: without it a
    sequence family would silently be evaluated on a slightly different population
    than the persistence baseline it is being compared against, and the resulting
    metric gap would be an artefact of which rows were dropped rather than a fact
    about the model.
    """
    if restrict is not None and restrict.shape[0] != matrix.rows:
        raise ModelDataError(
            f"restrict has {restrict.shape[0]} entries but the {matrix.split!r} split holds "
            f"{matrix.rows} row(s)"
        )
    if lookback < 1:
        raise ModelDataError(f"lookback must be >= 1; got {lookback}")
    if step_seconds is None or step_seconds <= 0:
        return SequenceSet(
            split=matrix.split,
            lookback=lookback,
            step_seconds=None,
            feature_names=matrix.feature_names,
            windows=np.zeros((0, lookback, len(matrix.feature_names)), dtype="float64"),
            targets=np.zeros(0, dtype="float64"),
            entities=matrix.entities,
            origin_instants=(),
            window_instants=(),
            window_entities=(),
            window_entity_sets=(),
            restricted_rows=0,
            skipped_insufficient_history=matrix.rows,
            skipped_missing_target=matrix.rows,
        )

    by_entity: dict[str, list[int]] = {}
    for index, entity in enumerate(matrix.row_entities):
        by_entity.setdefault(entity, []).append(index)

    windows: list[np.ndarray] = []
    targets: list[float] = []
    origins: list[datetime] = []
    entities: list[str] = []
    window_instants: list[tuple[datetime, ...]] = []
    window_entities: list[str] = []
    window_entity_sets: list[tuple[str, ...]] = []
    short_history = 0
    missing_target = 0
    restricted = 0

    for entity, indices in sorted(by_entity.items()):
        indices.sort(key=lambda position: matrix.origin_instants[position])
        for position, end in enumerate(indices):
            if restrict is not None and not bool(restrict[end]):
                restricted += 1
                continue
            origin = matrix.origin_instants[end]
            target = matrix.target[end]
            if not np.isfinite(target):
                missing_target += 1
                continue
            start = position - lookback + 1
            if start < 0:
                short_history += 1
                continue
            chosen = indices[start : position + 1]
            oldest = matrix.origin_instants[chosen[0]]
            if origin - oldest >= timedelta(seconds=lookback * step_seconds):
                # The rows are there but they are further apart than `lookback`
                # steps, so the window does not actually span the intended period.
                # Counting it as a sample would silently shorten the history the
                # model was configured to receive.
                short_history += 1
                continue
            if any(matrix.origin_instants[c] > origin for c in chosen):
                # Structurally impossible given the ordering; refused rather than
                # trusted, because "impossible" is exactly the property the
                # leakage audit exists to protect.
                short_history += 1
                continue
            windows.append(matrix.values[chosen])
            targets.append(float(target))
            origins.append(origin)
            entities.append(entity)
            window_instants.append(tuple(matrix.origin_instants[c] for c in chosen))
            window_entities.append(entity)
            # What the chosen rows turned out to be, not what `entity` intended. The
            # builder's grouping makes a mixed window impossible today; recording the
            # observed set is what turns that into something the audit can verify.
            window_entity_sets.append(
                tuple(sorted({matrix.row_entities[c] for c in chosen}))
            )

    shape = (len(windows), lookback, len(matrix.feature_names))
    return SequenceSet(
        split=matrix.split,
        lookback=lookback,
        step_seconds=float(step_seconds),
        feature_names=matrix.feature_names,
        windows=np.asarray(windows, dtype="float64").reshape(shape),
        targets=np.asarray(targets, dtype="float64"),
        entities=tuple(entities),
        origin_instants=tuple(origins),
        window_instants=tuple(window_instants),
        window_entities=tuple(window_entities),
        window_entity_sets=tuple(window_entity_sets),
        restricted_rows=restricted,
        skipped_insufficient_history=short_history,
        skipped_missing_target=missing_target,
    )


__all__ = [
    "CODE_BASELINE_ROWS_EXCLUDED",
    "CODE_FEATURE_DROPPED",
    "CODE_IMPUTED",
    "CODE_IMPUTE_NONE",
    "CODE_NO_FEATURES",
    "CODE_SCALER_TRAIN_ONLY",
    "CODE_TARGET_NOT_FUTURE",
    "CODE_TARGET_UNAVAILABLE",
    "CODE_TARGET_UNIT_UNKNOWN",
    "DATA_PREFIX",
    "ModelDataError",
    "ModelDataset",
    "ModelNote",
    "SequenceSet",
    "SplitMatrix",
    "TargetBinding",
    "assemble_dataset",
    "bind_target",
    "build_sequences",
    "persistence_predictions",
    "resolve_step_seconds",
]