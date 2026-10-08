# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""End-to-end training, chronological evaluation and candidate comparison.

Pipeline order (each stage documented in the module docstring of its own module):

1. load the configured dataset (``preprocessing`` step 1)
2. validate / parse / sort / dedupe / fill (``preprocessing`` steps 1-5)
3. build strictly-causal features (``features``)
4. contiguous chronological train / validation / test split (``preprocessing``)
5. align features at *t* with the target at *t + lead* **inside each split**, so
   no label crosses a period boundary (``features``)
6. fit the imputer and the scaler on the TRAINING rows only
7. fit the estimator on the TRAINING rows only
8. score the validation and test periods (``evaluation``)
9. compare every candidate the environment can actually run (``models``)

Nothing in this module randomises, shuffles, or hard-codes a score.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .artifacts import ArtifactStore
from .config import HydroConfig, load_config
from .evaluation import (
    HELD_OUT_SPLIT as EVALUATION_HELD_OUT_SPLIT,
)
from .evaluation import (
    SELECTION_SPLIT as EVALUATION_SELECTION_SPLIT,
)
from .evaluation import (
    EvaluationReport,
    ModelComparison,
    compare_models,
    evaluate_estimator,
    selection_policy_note,
)
from .features import (
    FeaturePlan,
    SupervisedSet,
    build_features,
    build_supervised,
    lead_time_rows_for,
)
from .models import (
    HydroEstimator,
    ModelUnavailableError,
    build_model,
    describe_registry,
    registry_keys,
    unavailable_models,
)
from .preprocessing import (
    PreprocessingResult,
    StandardScaler,
    TrainFittedImputer,
    assert_no_overlap,
    chronological_split,
    describe_preprocessing,
    prepare_frame,
)
from .provenance import (
    DATASET_TYPE_UNKNOWN,
    ProvenanceRecord,
    SplitBoundaries,
    file_checksum,
    provenance_from_config,
)
from .synthetic import (
    SyntheticSeriesSpec,
    generate_synthetic_series,
    write_synthetic_csv,
    synthetic_dataset_spec,
    synthetic_target_spec,
)

#: Default candidate order. `linear` is always included as the mandatory
#: baseline; the remaining entries are attempted in order and silently skipped
#: when their optional dependency is absent — with the skip reported.
DEFAULT_CANDIDATE_MODELS = ("linear", "ridge", "random_forest", "gradient_boosting", "xgboost")

#: Metric the comparison ranks candidates by. Lower is better for RMSE.
DEFAULT_SELECTION_METRIC = "rmse"

# The split names are defined in `evaluation`, which is where their meaning
# lives: only `HELD_OUT_SPLIT` yields an estimate of performance on unseen data.
# Re-exported here so callers of this module keep one obvious place to look.
SELECTION_SPLIT = EVALUATION_SELECTION_SPLIT
HELD_OUT_SPLIT = EVALUATION_HELD_OUT_SPLIT


class TrainingError(RuntimeError):
    """Raised when a training run cannot be completed honestly."""


@dataclass(frozen=True)
class SplitMatrices:
    """Feature matrix and target vector for one chronological split."""

    label: str
    features: pd.DataFrame
    target: np.ndarray
    timestamps: pd.Series
    target_timestamps: pd.Series
    feature_names: tuple[str, ...]

    @property
    def n_samples(self) -> int:
        return int(self.target.shape[0])

    def matrix(self) -> np.ndarray:
        return self.features.to_numpy(dtype="float64", na_value=np.nan)


@dataclass
class TrainedModel:
    """One fitted candidate plus everything needed to reproduce it."""

    key: str
    estimator: HydroEstimator
    imputer: TrainFittedImputer
    scaler: StandardScaler
    feature_names: tuple[str, ...]
    validation_report: EvaluationReport | None = None
    test_report: EvaluationReport | None = None

    @property
    def best_report(self) -> EvaluationReport | None:
        """The held-out (test) report when one exists, else the selection one.

        Consumers that display "the score" for a model must get the held-out
        figure, because the validation figure is the one that was optimised
        against and is therefore optimistic by construction.
        """
        return self.test_report or self.validation_report


@dataclass
class TrainResult:
    """Everything one training run produced, for reporting and artifact writing."""

    config: HydroConfig
    plan: FeaturePlan
    boundaries: SplitBoundaries
    preprocessing: PreprocessingResult
    lead_time_rows: int
    supervised: Mapping[str, SplitMatrices]
    models: dict[str, TrainedModel] = field(default_factory=dict)
    comparison: ModelComparison | None = None
    provenance: ProvenanceRecord | None = None
    sampling_interval: str | None = None
    selected_key: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def selected(self) -> TrainedModel | None:
        if self.selected_key is None:
            return None
        return self.models.get(self.selected_key)

    def preprocessing_log(self) -> str:
        return describe_preprocessing(self.preprocessing.steps)

    def supervised_size_summary(self) -> dict[str, int]:
        """Supervised sample count per chronological split."""
        return {label: part.n_samples for label, part in self.supervised.items()}


def load_dataset_frame(config: HydroConfig) -> tuple[pd.DataFrame, str | None]:
    """Load the configured dataset CSV and its checksum.

    Raises when no path is configured. The pipeline never falls back to
    generating data implicitly — a demo dataset must be written out explicitly by
    the demo entrypoint so the `synthetic` label travels with it.
    """
    path = config.dataset.path
    if not path:
        raise TrainingError(
            "no dataset configured. Set HYDRO_DATASET_PATH to a real hydrological CSV, "
            "or run the synthetic demo writer (training.py --write-synthetic <path>) "
            "which labels the output as SYNTHETIC/DEMO DATA."
        )
    if not os.path.exists(path):
        raise TrainingError(f"configured dataset does not exist: {path}")
    frame = pd.read_csv(path)
    return frame, file_checksum(path)


def _slice_to_period(
    features: pd.DataFrame,
    ts_col: str,
    start: Any,
    end: Any,
) -> pd.DataFrame:
    """Rows whose timestamp lies inside the closed period ``[start, end]``."""
    stamps = features[ts_col]
    return features.loc[(stamps >= start) & (stamps <= end)]


def build_split_matrices(
    features: pd.DataFrame,
    plan: FeaturePlan,
    config: HydroConfig,
    boundaries: SplitBoundaries,
    lead_time_rows: int,
) -> dict[str, SplitMatrices]:
    """Produce the per-split feature matrices and target vectors.

    A row belongs to a split only when **both** its origin timestamp and its
    (lead-shifted) target timestamp lie inside that split's period. Restricting
    the label as well as the features means the last `lead` rows of each period
    are dropped rather than supervised by a label from the next period — the
    conservative choice, and the reason a period's score never depends on an
    observation the period did not contain.
    """
    ts_col = config.dataset.timestamp_column
    names = plan.names
    result: dict[str, SplitMatrices] = {}
    periods = (
        ("train", boundaries.train_start, boundaries.train_end),
        ("validation", boundaries.validation_start, boundaries.validation_end),
        ("test", boundaries.test_start, boundaries.test_end),
    )
    for label, start, end in periods:
        if start is None or end is None:
            continue
        period_features = _slice_to_period(features, ts_col, start, end)
        period_features = period_features.reset_index(drop=True)
        supervised: SupervisedSet = build_supervised(
            period_features, plan, config, lead_time_rows=lead_time_rows, timestamp_column=ts_col
        )
        if supervised.n_samples < 2:
            raise TrainingError(
                f"{label} split has {supervised.n_samples} supervised sample(s) after a "
                f"{lead_time_rows}-row lead time; at least 2 are required to score it"
            )
        result[label] = SplitMatrices(
            label=label,
            features=supervised.features,
            target=supervised.target,
            timestamps=supervised.origin_timestamps,
            target_timestamps=supervised.target_timestamps,
            feature_names=supervised.feature_names,
        )
    if "train" not in result:
        raise TrainingError("chronological split produced no training samples")
    return result


def fit_pipeline(
    train: SplitMatrices,
    *,
    model_key: str,
    config: HydroConfig,
    model_options: Mapping[str, Any] | None = None,
) -> TrainedModel:
    """Fit the imputer, the scaler and one estimator — on training rows only."""
    names = train.feature_names
    imputer = TrainFittedImputer(strategy="median").fit(
        train.features, names, split_label="train"
    )
    imputed = imputer.transform(train.features, names)
    scaler = StandardScaler()
    if config.scaler == "standard":
        scaler = scaler.fit(imputed, names, split_label="train")

    options = dict(model_options or {})
    if model_key == "ridge":
        options.setdefault("alpha", config.ridge_alpha)
    estimator = build_model(model_key, options)
    estimator.fit(
        scaler.transform_matrix(imputed.to_numpy(dtype="float64", na_value=np.nan), names),
        train.target,
    )
    return TrainedModel(
        key=model_key,
        estimator=estimator,
        imputer=imputer,
        scaler=scaler,
        feature_names=names,
    )


def apply_trained(model: TrainedModel, matrices: SplitMatrices) -> np.ndarray:
    """Transform a split with the train-fitted statistics and predict.

    The imputer and the scaler are *reused*; nothing is refitted here. This is the
    line that guarantees validation/test scores are out-of-sample.
    """
    names = model.feature_names
    imputed = model.imputer.transform(matrices.features, names)
    if model.scaler.is_fitted:
        transformed = model.scaler.transform_matrix(imputed.to_numpy(dtype="float64", na_value=np.nan), names)
    else:
        transformed = imputed.to_numpy(dtype="float64", na_value=np.nan)
    return model.estimator.predict(transformed)


def train(
    config: HydroConfig,
    *,
    frame: pd.DataFrame | None = None,
    candidate_models: Sequence[str] = DEFAULT_CANDIDATE_MODELS,
    selection_metric: str = DEFAULT_SELECTION_METRIC,
) -> TrainResult:
    """Run the whole pipeline and return the comparison plus the selected model.

    Candidates whose optional dependency is missing are skipped and recorded in
    `TrainResult.notes`; they are never reported as evaluated.
    """
    ts_col = config.dataset.timestamp_column
    notes: list[str] = []

    if frame is None:
        frame, _checksum = load_dataset_frame(config)
    else:
        _checksum = None

    prepared = prepare_frame(frame, config)
    if prepared.duplicate_report and prepared.duplicate_report.has_duplicates:
        notes.append(
            f"resolved {prepared.duplicate_report.duplicate_count} duplicated timestamp(s) "
            "using the documented 'last wins' policy"
        )
    sampling_interval = prepared.sampling_interval
    if not sampling_interval:
        raise TrainingError(
            "the sampling interval could not be determined from the data; configure "
            "HYDRO_SAMPLING_INTERVAL so the forecast horizon can be converted to rows"
        )
    lead_time_rows = lead_time_rows_for(config, sampling_interval)

    features, plan = build_features(prepared.frame, config, timestamp_column=ts_col)
    # `build_features` cannot know the lead time - it is derived from the sampling
    # interval, which is only resolved here - so its plan carries the placeholder
    # value. The plan stored on the result describes the alignment that was
    # actually used, so it is rebound here rather than recording two different
    # lead times on one run.
    plan = replace(plan, lead_time_rows=lead_time_rows)
    split, boundaries = chronological_split(features, ts_col, config.split)
    assert_no_overlap(split, ts_col)

    matrices = build_split_matrices(features, plan, config, boundaries, lead_time_rows)
    if "validation" not in matrices or "test" not in matrices:
        raise TrainingError(
            "the chronological split produced no validation or test period; increase the dataset size "
            f"or adjust HYDRO_TRAIN_FRACTION / HYDRO_VALIDATION_FRACTION (train={config.split.train_fraction}, "
            f"validation={config.split.validation_fraction})"
        )

    provenance = provenance_from_config(
        config,
        feature_list=plan.names,
        split=boundaries,
        model_name=None,
        model_version=None,
        dataset_checksum=_checksum,
    )

    result = TrainResult(
        config=config,
        plan=plan,
        boundaries=boundaries,
        preprocessing=prepared,
        lead_time_rows=lead_time_rows,
        supervised=matrices,
        provenance=provenance,
        sampling_interval=sampling_interval,
        notes=notes,
    )

    # --- pass 1: fit every candidate on TRAIN, score each on VALIDATION -----
    #
    # Only the validation period is used to rank candidates. The test period is
    # deliberately not touched yet: if it were scored here it would take part in
    # the ranking, which would make the test score a selection statistic instead
    # of a held-out estimate.
    selection_reports: list[EvaluationReport] = []
    unevaluated: list[str] = []
    for model_key in candidate_models:
        if model_key not in registry_keys(available_only=False):
            unevaluated.append(model_key)
            continue
        try:
            trained = fit_pipeline(matrices["train"], model_key=model_key, config=config)
        except ModelUnavailableError as exc:
            unevaluated.append(model_key)
            notes.append(f"skipped {model_key}: {exc}")
            continue

        part = matrices[SELECTION_SPLIT]
        report = evaluate_estimator(
            trained.estimator,
            _transform_for(trained, part),
            part.target,
            config=config,
            split_label=SELECTION_SPLIT,
            model_version=_model_version(config, model_key),
            split=boundaries,
            provenance=provenance,
            lead_time_rows=lead_time_rows,
            feature_list=plan.names,
        )
        trained.validation_report = report
        selection_reports.append(report)
        result.models[model_key] = trained

    if not selection_reports:
        raise TrainingError(
            "no candidate model could be evaluated; see the notes for the reason each was skipped"
        )

    # --- pass 2: rank on validation, then spend the test split exactly once --
    comparison = compare_models(
        selection_reports,
        selection_metric=selection_metric,
        selection_split=SELECTION_SPLIT,
        held_out_split=HELD_OUT_SPLIT,
        unevaluated_keys=unevaluated,
        unavailable=unavailable_models(),
    )
    result.selected_key = comparison.selected_key

    held_out_report = None
    if comparison.selected_key is not None and HELD_OUT_SPLIT in matrices:
        winner = result.models[comparison.selected_key]
        part = matrices[HELD_OUT_SPLIT]
        held_out_report = evaluate_estimator(
            winner.estimator,
            _transform_for(winner, part),
            part.target,
            config=config,
            split_label=HELD_OUT_SPLIT,
            model_version=_model_version(config, comparison.selected_key),
            split=boundaries,
            provenance=provenance,
            lead_time_rows=lead_time_rows,
            feature_list=plan.names,
        )
        winner.test_report = held_out_report
        comparison = compare_models(
            selection_reports,
            selection_metric=selection_metric,
            selection_split=SELECTION_SPLIT,
            held_out_split=HELD_OUT_SPLIT,
            held_out_report=held_out_report,
            unevaluated_keys=unevaluated,
            unavailable=unavailable_models(),
        )
    result.comparison = comparison
    if comparison.selected_key:
        result.provenance = provenance_from_config(
            config,
            feature_list=plan.names,
            split=boundaries,
            model_name=result.models[comparison.selected_key].estimator.display_name,
            model_version=_model_version(config, comparison.selected_key),
            dataset_checksum=_checksum,
        )
        best = result.models[comparison.selected_key].best_report
        if best is not None:
            result.provenance = ProvenanceRecord(
                **{
                    **{
                        key: getattr(result.provenance, key)
                        for key in (
                            "dataset_reference",
                            "dataset_type",
                            "dataset_license",
                            "dataset_checksum",
                            "sampling_interval",
                            "target",
                            "target_units",
                            "forecast_horizon",
                            "station_reference",
                            "feature_list",
                            "split",
                            "model_name",
                            "model_version",
                            "artifact_reference",
                            "created_at",
                            "software_environment",
                            "disclaimer",
                        )
                    },
                    "evaluation_metrics": best.metrics.as_dict(),
                }
            )
    return result


def _transform_for(model: TrainedModel, matrices: SplitMatrices) -> np.ndarray:
    names = model.feature_names
    imputed = model.imputer.transform(matrices.features, names)
    if model.scaler.is_fitted:
        return model.scaler.transform_matrix(
            imputed.to_numpy(dtype="float64", na_value=np.nan), names
        )
    return imputed.to_numpy(dtype="float64", na_value=np.nan)


def _model_version(config: HydroConfig, model_key: str) -> str:
    """Model version derived from the contract version and the model key.

    There is no trained-artifact version yet, so the version reflects the
    pipeline contract revision rather than a trained release number. A real
    release must also record the artifact checksum (see `artifacts`).
    """
    return f"{model_key}-{config.contract_version.replace('/', '-')}"


def save_artifact(
    result: TrainResult,
    *,
    reference: str,
    allow_pickle: bool = False,
) -> Any:
    """Write the selected model plus its provenance to the artifact store."""
    selected = result.selected
    if selected is None or result.provenance is None:
        raise TrainingError("no model was selected; nothing to persist")
    store = ArtifactStore(result.config.artifact_dir)
    return store.save(
        reference=reference,
        estimator=selected.estimator,
        model_version=_model_version(result.config, selected.key),
        provenance=result.provenance,
        feature_list=selected.feature_names,
        evaluation_metrics=(
            selected.best_report.metrics.as_dict() if selected.best_report else None
        ),
        allow_pickle=allow_pickle,
    )


def format_report(result: TrainResult) -> str:
    """Full human-readable report of a training run."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("Q-FLARE HYDROLOGICAL FORECASTING — TRAINING RUN")
    lines.append("=" * 78)
    config = result.config
    lines.append(f"dataset_reference   : {config.dataset.reference or 'UNKNOWN'}")
    lines.append(f"dataset_type        : {config.dataset.dataset_type}")
    lines.append(f"dataset_path        : {config.dataset.path or 'UNKNOWN'}")
    lines.append(f"sampling_interval   : {result.sampling_interval or 'UNKNOWN'}")
    lines.append(f"target              : {config.target.describe()}")
    lines.append(f"forecast_horizon    : {config.target.horizon_hours}h "
                 f"(lead time {result.lead_time_rows} row(s))")
    lines.append(f"missing policy      : {config.missing_policy} (max gap {config.max_fill_gap})")
    lines.append(f"scaler              : {config.scaler} (fitted on training rows only)")
    lines.append(f"split fractions     : train {config.split.train_fraction} / "
                 f"validation {config.split.validation_fraction} / test {config.split.test_fraction}")
    lines.append(f"split sizes         : {json_like(result.supervised_size_summary())}")
    lines.append(f"features built      : {len(result.plan.names)}")
    lines.append("")
    lines.append("PREPROCESSING STEPS")
    for line in result.preprocessing_log().splitlines():
        lines.append(f"  {line}")
    lines.append("")
    lines.append("CANDIDATE MODEL COMPARISON")
    lines.append(
        f"(selection on the {SELECTION_SPLIT} split only; the {HELD_OUT_SPLIT} split is scored "
        "once, by the selected model, and never influences the ranking)"
    )
    if result.comparison is not None:
        lines.append(result.comparison.table())
        lines.append("")
        lines.append(f"selection metric    : {result.comparison.selection_metric}")
        lines.append(f"selection split     : {result.comparison.selection_split}")
        lines.append(f"selected model      : {result.comparison.selected_key}")
        lines.append(f"selection rationale : {selection_policy_note(result.comparison.selection_metric)}")
        if result.comparison.unevaluated_keys:
            lines.append(
                "not evaluated       : " + ", ".join(result.comparison.unevaluated_keys)
            )
        if result.comparison.unavailable:
            lines.append(
                "unavailable in this environment: "
                + ", ".join(f"{k} (missing {v})" for k, v in result.comparison.unavailable.items())
            )
        lines.append("")
        lines.append(f"HELD-OUT SCORE ({result.comparison.held_out_split} split, selected model only)")
        lines.append(result.comparison.held_out_table())
    lines.append("")
    lines.append("PER-MODEL DETAIL (validation = selection score, test = held-out score)")
    for model_key, trained in result.models.items():
        for label in ("validation", "test"):
            report = trained.validation_report if label == "validation" else trained.test_report
            if report is not None:
                lines.append("")
                lines.append(report.format())
    if result.notes:
        lines.append("")
        lines.append("NOTES")
        for note in result.notes:
            lines.append(f"  - {note}")
    lines.append("=" * 78)
    return "\n".join(lines)


def json_like(value: Mapping[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in value.items())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="q-flare-hydro-train",
        description=(
            "Train and evaluate the hydrological forecasting pipeline. "
            "Uses only chronological splits; no metric is hard-coded."
        ),
    )
    parser.add_argument(
        "--write-synthetic",
        metavar="PATH",
        help=(
            "Write a deterministic SYNTHETIC/DEMO CSV to PATH, label it as synthetic, "
            "and exit. The output is NOT real hydrological observation data."
        ),
    )
    parser.add_argument(
        "--dataset",
        metavar="PATH",
        help="Dataset CSV to train on (overrides HYDRO_DATASET_PATH for this run).",
    )
    parser.add_argument(
        "--dataset-type",
        choices=("real", "synthetic", "unknown"),
        help="Declared dataset type. Defaults to the configured value.",
    )
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_CANDIDATE_MODELS),
        help="Comma-separated candidate model keys to compare.",
    )
    parser.add_argument(
        "--selection-metric",
        default=DEFAULT_SELECTION_METRIC,
        help="Metric used to select the final model (default: rmse).",
    )
    parser.add_argument(
        "--save-artifact",
        metavar="REFERENCE",
        help="Persist the selected model under this reference (requires HYDRO_ARTIFACT_DIR).",
    )
    parser.add_argument(
        "--describe-registry",
        action="store_true",
        help="Print which candidate models this environment can actually run, then exit.",
    )
    parser.add_argument("--quiet", action="store_true", help="Print only the comparison table.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    args = build_arg_parser().parse_args(argv)

    if args.describe_registry:
        print(describe_registry())
        return 0

    if args.write_synthetic:
        spec = SyntheticSeriesSpec()
        written = write_synthetic_csv(args.write_synthetic, spec)
        print("WROTE SYNTHETIC/DEMO DATASET")
        print(f"  path             : {written['path']}")
        print(f"  dataset_reference: {written['dataset_reference']}")
        print(f"  dataset_type     : {written['dataset_type']}")
        print(f"  dataset_checksum : {written['dataset_checksum']}")
        print(f"  rows             : {written['n_rows']}")
        print(f"  columns          : {written['columns']}")
        print(f"  {written['disclaimer']}")
        return 0

    config = load_config()
    if args.dataset:
        config = config.with_overrides(
            dataset=replace(
                config.dataset,
                path=args.dataset,
                reference=config.dataset.reference or 'unrecorded://local-file',
            )
        )
    if args.dataset_type:
        config = config.with_overrides(
            dataset=replace(config.dataset, dataset_type=args.dataset_type)
        )

    if config.dataset.dataset_type == "synthetic" or args.dataset_type == "synthetic":
        # A synthetic run must always carry a declared synthetic station and a
        # declared unit, otherwise its provenance is incomplete by construction.
        config = config.with_overrides(
            dataset=synthetic_dataset_spec(config), target=synthetic_target_spec(config)
        )

    try:
        result = train(
            config,
            candidate_models=tuple(key for key in args.models.split(",") if key),
            selection_metric=args.selection_metric,
        )
    except (TrainingError, ValueError) as exc:
        print(f"TRAINING FAILED: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(result.comparison.table() if result.comparison else "no comparison")
    else:
        print(format_report(result))

    if args.save_artifact:
        if not config.artifact_dir:
            print(
                "cannot save artifact: HYDRO_ARTIFACT_DIR is not configured",
                file=sys.stderr,
            )
            return 1
        try:
            record = save_artifact(result, reference=args.save_artifact)
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
            print(f"ARTIFACT NOT SAVED: {exc}", file=sys.stderr)
            return 1
        print("")
        print(f"artifact written   : {record.reference}")
        print(f"artifact checksum  : {record.artifact_checksum}")
        print(f"production_ready   : {record.production_ready}")
        if record.disclaimer:
            print(f"disclaimer         : {record.disclaimer}")

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
