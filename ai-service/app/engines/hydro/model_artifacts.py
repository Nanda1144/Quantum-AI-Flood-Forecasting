# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 artifacts: describe what was built, and refuse to invent what was not.

Three rules, and the module is mostly these three rules.

**A model that did not train has no artifact.** A blocked XGBoost run produces a
manifest with `artifact_status="not_written"` and an empty weight reference. It
does not produce an empty weight file, a placeholder, or a pickled stub. A file
that exists can be loaded, and a loadable file that predicts noise is worse than
no file at all.

**Weights do not go into Git.** A fitted random forest is tens of megabytes; a
Keras network is tens more. Committing either makes the repository unusable and
diffs unreviewable, and the interesting part — which data, which features, which
split, which seed, which library versions — is a few hundred bytes of text.
`WEIGHT_STORAGE_POLICY` says where the binaries belong instead.

**`metadata_only` is the default and stays the default.** A configuration can ask
for parameters to be recorded; nothing here can talk anyone into marking a model
production-ready, and `production_ready_claimed` is permanently `False` on every
manifest because the claim was declined upstream and the refusal travels with the
record.

The manifest reuses `artifacts.ArtifactRecord` and `provenance.ProvenanceRecord`
rather than inventing a third shape. Where Phase 4 needs a field they do not
carry — the training fingerprint, the split row counts, the dependency verdicts —
they are added here rather than smuggled into an existing field, so a reader never
has to guess what a repurposed key meant.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .artifacts import ARTIFACT_FORMAT_VERSION
from .feature_pipeline import FEATURE_CONTRACT_VERSION
from .model_config import (
    ARTIFACT_INCLUDE_PARAMETERS,
    ARTIFACT_METADATA_ONLY,
    ARTIFACT_POLICIES,
    MODEL_CONTRACT_VERSION,
)
from .model_registry import (
    ARTIFACT_STATUS_NOT_WRITTEN,
    ARTIFACT_STATUSES,
    STATUS_TRAINED,
    probe,
    registry_rows,
    spec_for,
)
from .model_training import ModelRun, RunResult
from .provenance import ProvenanceRecord, utc_now_iso

#: Bumped whenever the manifest layout changes incompatibly. Distinct from
#: `artifacts.ARTIFACT_FORMAT_VERSION`, which versions the *estimator* payload;
#: conflating the two would mean a Phase 4 metadata change broke artifact loading.
#:
#: v2 adds `feature_columns` to the canonical (and therefore written) structure, so
#: a manifest now carries the ordered list its own order-sensitive
#: `feature_digest` is computed over. Under v1 the digest could not be re-verified
#: from the file at all, which meant the serving path could not check the feature
#: contract of anything it loaded from disk. Phase 5 refuses a v1 file for that
#: reason rather than accepting a checksum it cannot confirm.
ARTIFACT_MANIFEST_VERSION = "navya-phase4-manifest/v2"

#: Versions this codebase can read. v1 is listed so the error for an old file says
#: *why* it is refused instead of merely that it is a different version.
LEGACY_MANIFEST_VERSION = "navya-phase4-manifest/v1"

#: The bundle index `write_manifests` emits. Named as a constant because Phase 5's
#: directory loader has to find the same file, and a filename written twice in two
#: modules is a filename that will eventually disagree with itself.
#:
#: The index matters to Phase 5 for one specific reason: a dependency-blocked model
#: has `artifact_status='not_written'` and therefore no manifest file, so it is
#: recorded *only* here. Reading the files alone would make a blocked model
#: disappear instead of reporting itself.
INDEX_FILENAME = "phase4-artifacts.index.json"

#: Where fitted weights are meant to live, and why they are not in the repository.
WEIGHT_STORAGE_POLICY = (
    "Fitted model weights are NOT stored in this repository. A random forest and a "
    "recurrent network are tens of megabytes of binary that would make every diff "
    "unreviewable and every clone slow, while everything a reviewer actually needs "
    "- target, horizon, feature list and version, split bounds, random seed, "
    "hyperparameters, library versions, metrics and provenance - is text. A Phase 4 "
    "manifest records the weight reference as a pointer plus a checksum; the bytes "
    "belong in object storage or a model registry (MLflow, S3, a container image), "
    "addressed by that reference. Loading weights is a Phase 5 / deployment "
    "responsibility and is deliberately not implemented here."
)

#: Fields that legitimately vary between two otherwise identical runs. They are
#: excluded from the deterministic digest and are named here rather than left as a
#: surprise for whoever compares two manifests.
#:
#: These are *paths*, not top-level keys, and that is load-bearing. The manifest
#: carries a second wall-clock instant inside the provenance block it reuses from
#: Phase 3, so a manifest that declared only `created_at` would be claiming a
#: determinism it does not have: two identical runs would produce two documents
#: differing in a field nobody had declared. Declaring the nested path is what makes
#: the claim true rather than merely stated.
NONDETERMINISTIC_FIELDS: tuple[str, ...] = ("created_at", "provenance.created_at")

#: Payload keys that are the artifact digest and therefore cannot cover themselves.
_SELF_REFERENTIAL = ("manifest_checksum",)


class ArtifactManifestError(RuntimeError):
    """Raised when a manifest cannot be built or written safely."""


# --------------------------------------------------------------------------- #
# Determinism: the training fingerprint
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TrainingFingerprint:
    """Everything needed to decide whether two runs produced the same thing.

    A checksum over this object answers "were these two runs the same experiment?"
    without comparing floating-point model weights, which may legitimately differ
    in their last bits even when the seed, the code and the data are identical.

    It covers: both contract versions, the target, the horizon, the feature list
    and its digest, the row counts, the seed, the policy tuple, the hyperparameters
    actually used, and the resolved dependency versions. It deliberately excludes
    timestamps and the seed's effect on floating-point noise.
    """

    model_contract_version: str
    feature_contract_version: str
    target: str | None
    horizon: str | None
    feature_columns: tuple[str, ...]
    feature_digest: str
    split_policy: str
    scaler_policy: str
    impute_policy: str
    feature_selection: str
    persistence_source: str
    random_seed: int
    hyperparameters: Mapping[str, Any]
    train_rows: int | None
    validation_rows: int | None
    test_rows: int | None
    supervised_train_rows: int | None
    supervised_validation_rows: int | None
    supervised_test_rows: int | None
    dataset_reference: str | None
    dataset_checksum: str | None
    dependency_versions: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.to_canonical())
        payload["feature_columns"] = list(self.feature_columns)
        payload["hyperparameters"] = dict(sorted(self.hyperparameters.items()))
        payload["dependency_versions"] = dict(sorted(self.dependency_versions.items()))
        return payload

    def to_canonical(self) -> dict[str, Any]:
        """The exact structure that is hashed. Lists, not tuples, and sorted keys.

        `feature_columns` keeps the model's column order rather than being sorted.
        Sorting it here made the hashed structure disagree with the
        order-sensitive `feature_digest` sitting next to it, so the fingerprint
        described two different feature matrices - the one the model saw, and its
        alphabetisation - while appearing to name only one.
        """
        return {
            "model_contract_version": self.model_contract_version,
            "feature_contract_version": self.feature_contract_version,
            "target": self.target,
            "horizon": self.horizon,
            "feature_columns": list(self.feature_columns),
            "feature_digest": self.feature_digest,
            "split_policy": self.split_policy,
            "scaler_policy": self.scaler_policy,
            "impute_policy": self.impute_policy,
            "feature_selection": self.feature_selection,
            "persistence_source": self.persistence_source,
            "random_seed": self.random_seed,
            "hyperparameters": {str(k): _scalar(v) for k, v in sorted(self.hyperparameters.items())},
            "train_rows": self.train_rows,
            "validation_rows": self.validation_rows,
            "test_rows": self.test_rows,
            "supervised_train_rows": self.supervised_train_rows,
            "supervised_validation_rows": self.supervised_validation_rows,
            "supervised_test_rows": self.supervised_test_rows,
            "dataset_reference": self.dataset_reference,
            "dataset_checksum": self.dataset_checksum,
            "dependency_versions": dict(sorted(self.dependency_versions.items())),
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical form.

        `canonical_checksum` from `artifacts.py` is reused rather than
        reimplemented, so an artifact and a manifest hash the same way.
        """
        text = json.dumps(self.to_canonical(), indent=2, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scalar(value: Any) -> Any:
    """Reduce a hyperparameter to something JSON-stable and hashable."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_scalar(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _scalar(item) for key, item in sorted(value.items())}
    return str(value)


def feature_digest(feature_names: Sequence[str]) -> str:
    """SHA-256 over the ordered feature list.

    Order matters, so the hash is taken over the list as given rather than over a
    sorted set: two datasets with the same 32 columns in a different order are
    different feature matrices.
    """
    return hashlib.sha256("\n".join(feature_names).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# The manifest
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ArtifactManifest:
    """One model's artifact description, whether or not anything was written.

    `artifact_status` is the field that matters most and it is never inferred from
    whether the run happened to succeed. A trained model under the default
    `metadata_only` policy is `metadata_only`; a trained model under
    `metadata_and_parameters` is `metadata_and_parameters`; anything that did not
    train is `not_written`.
    """

    model_id: str
    model_family: str
    display_name: str
    role: str
    target: str
    target_units: str | None
    horizon: str | None
    training_status: str
    evaluation_status: str
    artifact_status: str
    artifact_policy: str
    weight_reference: str | None
    weight_stored_in_repository: bool
    weight_policy: str = WEIGHT_STORAGE_POLICY
    feature_contract_version: str = FEATURE_CONTRACT_VERSION
    model_contract_version: str = MODEL_CONTRACT_VERSION
    artifact_format_version: str = ARTIFACT_FORMAT_VERSION
    manifest_version: str = ARTIFACT_MANIFEST_VERSION
    feature_count: int = 0
    feature_columns: tuple[str, ...] = ()
    feature_digest: str = ""
    dataset_reference: str | None = None
    dataset_checksum: str | None = None
    dataset_type: str = "unknown"
    data_status: str = "unknown"
    synthetic_demo: bool = True
    disclaimer: str | None = None
    split_policy: str | None = None
    split_bounds: Mapping[str, Any] = field(default_factory=dict)
    row_counts: Mapping[str, int | None] = field(default_factory=dict)
    random_seed: int | None = None
    hyperparameters: Mapping[str, Any] = field(default_factory=dict)
    #: True exactly when `hyperparameters` above is non-empty, i.e. when this manifest
    #: records the parameters the fitted estimator actually had. It says nothing about
    #: whether a weights blob exists; `artifact_status` says that.
    parameters_recorded: bool = False
    dependency_versions: Mapping[str, str] = field(default_factory=dict)
    metrics_by_split: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    evaluation_status_by_split: Mapping[str, str] = field(default_factory=dict)
    reason: str | None = None
    insufficiency: Mapping[str, Any] | None = None
    fingerprint: TrainingFingerprint | None = None
    provenance: Mapping[str, Any] | None = None
    production_ready_claimed: bool = False
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.artifact_status not in ARTIFACT_STATUSES:
            raise ArtifactManifestError(
                f"unknown artifact status {self.artifact_status!r}; known statuses are "
                f"{list(ARTIFACT_STATUSES)}"
            )
        if self.artifact_policy not in ARTIFACT_POLICIES:
            raise ArtifactManifestError(
                f"unknown artifact policy {self.artifact_policy!r}; known policies are "
                f"{list(ARTIFACT_POLICIES)}"
            )
        if self.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN and self.weight_reference:
            raise ArtifactManifestError(
                f"model {self.model_id!r} reports {ARTIFACT_STATUS_NOT_WRITTEN!r} yet carries a "
                f"weight reference ({self.weight_reference!r}); a model with no artifact must "
                "not point at one"
            )

    @property
    def fingerprint_digest(self) -> str | None:
        return self.fingerprint.digest if self.fingerprint is not None else None

    def to_canonical(self) -> dict[str, Any]:
        """The structure that is hashed. Excludes `created_at` and the digest.

        `feature_columns` is included deliberately. The feature digest is taken over
        the *ordered* list, so a manifest that recorded the digest without the list
        could not be verified by anyone reading it back: the only column list in the
        file was the fingerprint's, and that one is a set rendered in sorted order,
        which hashes differently from the order the model actually saw. A checksum
        that cannot be checked against the thing it checksums is decoration.
        """
        return {
            "manifest_version": self.manifest_version,
            "model_contract_version": self.model_contract_version,
            "feature_contract_version": self.feature_contract_version,
            "artifact_format_version": self.artifact_format_version,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "role": self.role,
            "target": self.target,
            "target_units": self.target_units,
            "horizon": self.horizon,
            "training_status": self.training_status,
            "evaluation_status": self.evaluation_status,
            "artifact_status": self.artifact_status,
            "artifact_policy": self.artifact_policy,
            "weight_stored_in_repository": self.weight_stored_in_repository,
            "feature_count": self.feature_count,
            "feature_columns": list(self.feature_columns),
            "feature_digest": self.feature_digest,
            "dataset_reference": self.dataset_reference,
            "dataset_checksum": self.dataset_checksum,
            "dataset_type": self.dataset_type,
            "data_status": self.data_status,
            "synthetic_demo": self.synthetic_demo,
            "split_policy": self.split_policy,
            "split_bounds": dict(sorted(self.split_bounds.items())),
            "row_counts": dict(sorted(self.row_counts.items())),
            "random_seed": self.random_seed,
            "parameters_recorded": self.parameters_recorded,
            "hyperparameters": {
                str(k): _scalar(v) for k, v in sorted(self.hyperparameters.items())
            },
            "dependency_versions": dict(sorted(self.dependency_versions.items())),
            "metrics_by_split": {
                split: {k: float(v) for k, v in sorted(values.items())}
                for split, values in sorted(self.metrics_by_split.items())
            },
            "evaluation_status_by_split": dict(sorted(self.evaluation_status_by_split.items())),
            "insufficiency": self.insufficiency,
            "fingerprint": self.fingerprint.to_canonical() if self.fingerprint else None,
            "production_ready_claimed": self.production_ready_claimed,
        }

    @property
    def checksum(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_canonical(), indent=2, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_canonical()
        # Fields outside the digest are appended after it, so a reader can see
        # exactly what the checksum does and does not cover.
        payload["disclaimer"] = self.disclaimer
        payload["reason"] = self.reason
        payload["provenance"] = dict(self.provenance) if self.provenance else None
        payload["weight_policy"] = self.weight_policy
        payload["nondeterministic_fields"] = list(NONDETERMINISTIC_FIELDS)
        payload["created_at"] = self.created_at
        payload["fingerprint_digest"] = self.fingerprint_digest
        payload["manifest_checksum"] = self.checksum
        return payload

    def to_json(self) -> str:
        """Deterministic rendering.

        Two manifests built from the same run differ only in `created_at`. That is
        stated in `nondeterministic_fields` rather than left to be discovered when a
        diff test fails.
        """
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)

    def describe(self) -> str:
        lines = [
            f"Artifact manifest {self.manifest_version}",
            f"  model_id       : {self.model_id}",
            f"  family / role  : {self.model_family} / {self.role}",
            f"  target         : {self.target} [{self.target_units or 'unit unknown'}]",
            f"  horizon        : {self.horizon}",
            f"  training       : {self.training_status}",
            f"  evaluation     : {self.evaluation_status}",
            f"  artifact       : {self.artifact_status} (policy {self.artifact_policy})",
            f"  weights in git : {self.weight_stored_in_repository}",
            f"  features       : {self.feature_count} (digest {self.feature_digest[:12]})",
            f"  row counts     : {dict(sorted(self.row_counts.items()))}",
            f"  seed           : {self.random_seed}",
            f"  data status    : {self.data_status}",
            f"  synthetic      : {self.synthetic_demo}",
        ]
        if self.fingerprint_digest:
            lines.append(f"  fingerprint    : {self.fingerprint_digest[:16]}")
        for split in sorted(self.metrics_by_split):
            values = ", ".join(
                f"{key}={value:.6g}" for key, value in sorted(self.metrics_by_split[split].items())
            )
            lines.append(f"  {split:<15}: {values}")
        if not self.metrics_by_split and self.training_status != STATUS_TRAINED:
            lines.append("  metrics        : none - the model was never fitted")
        if self.disclaimer:
            lines.append(f"  disclaimer     : {self.disclaimer}")
        lines.append(f"  checksum       : {self.checksum[:16]}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ArtifactManifests:
    """Every manifest from one `train_models` call, plus the run-level facts."""

    manifests: tuple[ArtifactManifest, ...] = ()
    data_status: str = "unknown"
    is_synthetic: bool = True
    disclaimer: str | None = None
    baseline_family: str | None = None
    selection_metric: str | None = None
    selection_split: str | None = None
    manifest_version: str = ARTIFACT_MANIFEST_VERSION
    created_at: str = field(default_factory=utc_now_iso)

    def for_model(self, model_id: str) -> ArtifactManifest:
        for manifest in self.manifests:
            if manifest.model_id == model_id:
                return manifest
        raise KeyError(
            f"no artifact manifest for {model_id!r}; known models: "
            f"{[m.model_id for m in self.manifests]}"
        )

    def by_status(self, status: str) -> tuple[ArtifactManifest, ...]:
        return tuple(m for m in self.manifests if m.artifact_status == status)

    @property
    def written(self) -> tuple[ArtifactManifest, ...]:
        return tuple(
            m for m in self.manifests if m.artifact_status != ARTIFACT_STATUS_NOT_WRITTEN
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "data_status": self.data_status,
            "is_synthetic": self.is_synthetic,
            "disclaimer": self.disclaimer,
            "baseline_family": self.baseline_family,
            "selection_metric": self.selection_metric,
            "selection_split": self.selection_split,
            "weight_storage_policy": WEIGHT_STORAGE_POLICY,
            "nondeterministic_fields": list(NONDETERMINISTIC_FIELDS),
            "created_at": self.created_at,
            "manifests": [manifest.to_dict() for manifest in self.manifests],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)

    def describe(self) -> str:
        lines = [
            f"Phase 4 artifact manifests ({self.manifest_version})",
            f"  data status : {self.data_status}",
            f"  synthetic   : {self.is_synthetic}",
        ]
        if self.disclaimer:
            lines.append(f"  disclaimer  : {self.disclaimer}")
        for manifest in self.manifests:
            lines.append("")
            lines.append(manifest.describe())
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Building manifests from a training run
# --------------------------------------------------------------------------- #


def _dependency_versions(run: ModelRun) -> dict[str, str]:
    """Resolved versions for this family's own requirements.

    An absent package is recorded as the blocker text, not omitted and not as an
    empty string. An environment block that simply lacks `xgboost` reads as "not
    relevant"; the honest reading is "requested, missing, here is why".
    """
    versions: dict[str, str] = {}
    for requirement in spec_for(run.model_family).requires:
        report = probe(requirement)
        versions[requirement.module] = (
            f"installed ({report.version})"
            if report.installed
            else f"not installed - {report.blocked_reason}"
        )
    return versions


def _fingerprint_for(run: ModelRun, dataset: Any) -> TrainingFingerprint | None:
    """The fingerprint, or `None` when there is no dataset to describe.

    A run that never reached the dataset (a missing target, a blocked dependency)
    has no feature list and no row counts, and inventing zeros for them would put
    a plausible-looking fingerprint on a run that never touched any data.
    """
    if dataset is None:
        return None
    config = dataset.config
    splits = dataset.splits
    return TrainingFingerprint(
        model_contract_version=MODEL_CONTRACT_VERSION,
        feature_contract_version=dataset.feature_contract_version,
        target=run.target,
        horizon=run.horizon,
        feature_columns=tuple(run.feature_names),
        feature_digest=feature_digest(run.feature_names),
        split_policy=config.split_policy,
        scaler_policy=config.scaler_policy,
        impute_policy=config.impute_policy,
        feature_selection=config.feature_selection,
        persistence_source=config.persistence_source,
        random_seed=config.random_seed,
        hyperparameters=dict(run.record.get("hyperparameters") or {}),
        train_rows=_rows(splits, "train"),
        validation_rows=_rows(splits, "validation"),
        test_rows=_rows(splits, "test"),
        supervised_train_rows=_supervised(splits, "train"),
        supervised_validation_rows=_supervised(splits, "validation"),
        supervised_test_rows=_supervised(splits, "test"),
        dataset_reference=dataset.dataset_reference,
        dataset_checksum=dataset.dataset_checksum,
        dependency_versions=_dependency_versions(run),
    )


def _rows(splits: Mapping[str, Any], name: str) -> int | None:
    part = splits.get(name)
    return int(part.rows) if part is not None else None


def _supervised(splits: Mapping[str, Any], name: str) -> int | None:
    part = splits.get(name)
    return int(part.evaluable) if part is not None else None


def manifest_for(result: RunResult, model_id: str) -> ArtifactManifest:
    """Build the manifest for one model in a completed run."""
    run = result.run_for(model_id)
    dataset = _dataset_for(result, run)
    return _manifest_for_run(run, dataset, result)


def _dataset_for(result: RunResult, run: ModelRun) -> Any:
    """The assembled dataset behind this run, when one exists."""
    primary = result.primary_dataset
    if primary is not None and primary.binding.column == run.target:
        return primary
    return result.datasets.get(run.target)


def _manifest_for_run(
    run: ModelRun, dataset: Any, result: RunResult
) -> ArtifactManifest:
    trained = run.status == STATUS_TRAINED
    policy = str(run.record.get("artifact_policy") or ARTIFACT_METADATA_ONLY)
    if policy not in ARTIFACT_POLICIES:
        policy = ARTIFACT_METADATA_ONLY

    # The artifact status follows the training status. `ModelRun` already refuses to
    # claim an artifact for a model that did not fit, so this is a restatement of
    # the same rule rather than a second opinion: a blocked model is `not_written`
    # and points at no weight file.
    artifact_status = (
        run.artifact_status if trained else ARTIFACT_STATUS_NOT_WRITTEN
    )

    metrics_by_split: dict[str, Mapping[str, float]] = {}
    status_by_split: dict[str, str] = {}
    for outcome in result.outcomes:
        if outcome.model_id != run.model_id:
            continue
        status_by_split[outcome.split] = outcome.status
        if outcome.metrics:
            metrics_by_split[outcome.split] = dict(outcome.metrics)

    provenance: dict[str, Any] | None = None
    if run.provenance is not None:
        provenance = run.provenance.to_dict()

    bounds: dict[str, Any] = {}
    if dataset is not None:
        bounds = {
            "train_start": dataset.bounds.train_start,
            "train_end": dataset.bounds.train_end,
            "validation_start": dataset.bounds.validation_start,
            "validation_end": dataset.bounds.validation_end,
            "test_start": dataset.bounds.test_start,
            "test_end": dataset.bounds.test_end,
        }

    return ArtifactManifest(
        model_id=run.model_id,
        model_family=run.model_family,
        display_name=spec_for(run.model_family).display_name,
        role=run.role,
        target=run.target,
        target_units=run.target_units,
        horizon=run.horizon,
        training_status=run.status,
        evaluation_status=run.evaluation_status,
        artifact_status=artifact_status,
        artifact_policy=policy,
        weight_reference=None,
        weight_stored_in_repository=False,
        feature_columns=tuple(run.feature_names),
        feature_count=len(run.feature_names),
        feature_digest=feature_digest(run.feature_names),
        dataset_reference=dataset.dataset_reference if dataset is not None else None,
        dataset_checksum=dataset.dataset_checksum if dataset is not None else None,
        dataset_type=dataset.dataset_type if dataset is not None else "unknown",
        data_status=run.data_status,
        synthetic_demo=run.synthetic_demo,
        disclaimer=result.disclaimer,
        split_policy=dataset.config.split_policy if dataset is not None else None,
        split_bounds=bounds,
        row_counts={
            "train": _rows(dataset.splits, "train") if dataset is not None else None,
            "validation": _rows(dataset.splits, "validation") if dataset is not None else None,
            "test": _rows(dataset.splits, "test") if dataset is not None else None,
            "supervised_train": (
                _supervised(dataset.splits, "train") if dataset is not None else None
            ),
            "supervised_validation": (
                _supervised(dataset.splits, "validation") if dataset is not None else None
            ),
            "supervised_test": (
                _supervised(dataset.splits, "test") if dataset is not None else None
            ),
        },
        # A run that never reached `fit_family` has no `record`, and therefore no
        # `seed` in it. The configuration still declared one, and the fingerprint
        # needs it, so it is read from there rather than left blank.
        random_seed=run.record.get("seed")
        or (dataset.config.random_seed if dataset is not None else None),
        hyperparameters=dict(run.record.get("hyperparameters") or {}),
        # Whether *this manifest* carries the fitted parameters - read off the block
        # beside it, so the two fields cannot disagree. It previously keyed off the
        # artifact policy instead, which made a manifest show a fully populated
        # `hyperparameters` block next to `parameters_recorded: false` and left the
        # reader to guess which of the two was lying. Whether a separate weights or
        # parameter blob exists is `artifact_status`, which is what says that.
        parameters_recorded=bool(run.record.get("hyperparameters") or {}),
        dependency_versions=_dependency_versions(run),
        metrics_by_split=metrics_by_split,
        evaluation_status_by_split=status_by_split,
        reason=run.reason,
        insufficiency=run.insufficiency.to_dict() if run.insufficiency else None,
        fingerprint=_fingerprint_for(run, dataset),
        provenance=provenance,
        production_ready_claimed=False,
    )


def build_manifests(result: RunResult) -> ArtifactManifests:
    """Build every manifest for one completed `train_models` call.

    The connection to `model_training` lives here rather than inside
    `train_models`: training does not know whether anyone wants artifacts, and
    making it build them would mean every fit paid for a manifest nobody asked for.
    """
    return ArtifactManifests(
        manifests=tuple(
            _manifest_for_run(run, _dataset_for(result, run), result) for run in result.runs
        ),
        data_status=result.data_status,
        is_synthetic=result.is_synthetic,
        disclaimer=result.disclaimer,
        baseline_family=result.baseline_family,
        selection_metric=result.selection_metric,
        selection_split=result.selection_split,
    )


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def write_manifests(manifests: ArtifactManifests, directory: str) -> tuple[str, ...]:
    """Write one JSON manifest per model, atomically. Never writes weights.

    Only manifests whose status is not `not_written` produce a file. A blocked
    model still gets a manifest in memory — and in `to_json()` — so the reason it
    could not be built is preserved; it just does not get a file that says nothing.

    Returns the paths written. Raises when `directory` is empty, because silently
    writing nowhere is the kind of success that hides a misconfiguration.
    """
    if not directory:
        raise ArtifactManifestError(
            "no artifact directory given; Phase 4 writes manifests only where it is told to, "
            "and HYDRO_ARTIFACT_DIR is the conventional source"
        )
    os.makedirs(directory, exist_ok=True)
    written: list[str] = []
    for manifest in manifests.manifests:
        if manifest.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN:
            continue
        safe = manifest.model_id.replace("/", "__").replace("\\", "__").replace(":", "__")
        path = os.path.join(directory, f"{safe}.manifest.json")
        _atomic_write(path, manifest.to_json())
        written.append(path)
    index = os.path.join(directory, INDEX_FILENAME)
    _atomic_write(index, manifests.to_json())
    written.append(index)
    return tuple(written)


def _atomic_write(path: str, text: str) -> None:
    """Write via a temporary file and `os.replace`, mirroring `artifacts.py`.

    Duplicated rather than imported because `artifacts._atomic_write` is private
    to that module; a two-line call into a private name is worse coupling than
    repeating it.
    """
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


def registry_manifest_rows() -> list[dict[str, Any]]:
    """The registry, rendered as manifest-shaped rows.

    Lets a reviewer read the artifact surface without running a fit, and gives the
    docs and the tests one source for "which families exist and what do they need".
    """
    rows: list[dict[str, Any]] = []
    for row in registry_rows():
        rows.append(
            {
                "model_family": row["model_family"],
                "display_name": row["display_name"],
                "role": row["role"],
                "implementation": row["implementation"],
                "available_here": row["available_here"],
                "blocked_reason": row["blocked_reason"],
                "default_artifact_policy": row["default_artifact_policy"],
                "expected_artifact_status": (
                    ARTIFACT_STATUS_NOT_WRITTEN
                    if not row["available_here"]
                    else row["default_artifact_policy"]
                ),
                "production_ready_claimed": False,
                "runtime_versions": row["runtime_versions"],
            }
        )
    return rows


__all__ = [
    "ARTIFACT_MANIFEST_VERSION",
    "INDEX_FILENAME",
    "LEGACY_MANIFEST_VERSION",
    "NONDETERMINISTIC_FIELDS",
    "WEIGHT_STORAGE_POLICY",
    "ArtifactManifest",
    "ArtifactManifestError",
    "ArtifactManifests",
    "TrainingFingerprint",
    "build_manifests",
    "feature_digest",
    "manifest_for",
    "registry_manifest_rows",
    "write_manifests",
]