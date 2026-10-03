# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — the orchestrator, the leakage tests, and the scope guards.

The leakage tests come first in the file because they are the reason the rest
exists. They are behavioural where they can be: an assertion that a feature value
did not change when the future was deleted catches a whole class of bugs that an
introspection of the code cannot, because the class is defined by what the value
depends on.

The scope guards at the end are deliberately different in kind. They read the
Phase 3 source with `ast` and refuse a forbidden import or a call to a fitting
routine. Phase 3 builds features and stops; a dependency on a machine-learning
framework appearing here would mean the boundary has moved without anybody
deciding to move it, and that is worth a test rather than a code review comment
nobody re-reads.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.engines.hydro import feature_pipeline as pipeline
from app.engines.hydro import feature_registry as registry
from app.engines.hydro import feature_temporal as temporal
from app.engines.hydro.domains import Measurement, Observation
from app.engines.hydro.feature_config import (
    MISSING_DROP_ROWS,
    WARMUP_DROP_ROWS,
    FeatureConfig,
)


UTC = dt.timezone.utc
EPOCH = dt.datetime(2024, 1, 1, tzinfo=UTC)
HOUR = 3600.0
PACKAGE = Path(__file__).resolve().parents[1] / "app" / "engines" / "hydro"


PHASE3_MODULES = (
    "feature_registry.py",
    "feature_config.py",
    "feature_temporal.py",
    "feature_pipeline.py",
)

FORBIDDEN_IMPORTS = frozenset(
    {
        "xgboost",
        "tensorflow",
        "torch",
        "keras",
        "sklearn",
        "lightgbm",
        "catboost",
        "pennylane",
        "qiskit",
        "cirq",
        "dask",
    }
)

#: Every top-level module name in the standard library for this interpreter.
_STDLIB = frozenset(sys.stdlib_module_names)


def module_source(name: str) -> str:
    """The text of one Phase 3 module, read from disk rather than imported."""
    return (PACKAGE / name).read_text(encoding="utf-8")


#: Verbs that would mean Phase 3 had started doing Phase 2's job. Matched
#: against identifiers with `ast`, not against the file text: `resolve_cadence`'s
#: own docstring says "Phase 3 never resamples", and a substring search would
#: fail on the sentence that documents the guarantee it is checking for.
RESAMPLING_VERBS = frozenset(
    {
        "asfreq",
        "backfill",
        "bfill",
        "ffill",
        "fillna",
        "interpolate",
        "pad",
        "reindex",
        "resample",
        "rolling",
    }
)


def identifiers(module: str) -> set[str]:
    """Every name and attribute `module` mentions, excluding string literals."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(module_source(module))):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
    return found


def imported_roots(module: str) -> set[str]:
    """Top-level module names `module` imports, excluding relative imports.

    Relative imports are excluded because they name a sibling, not a dependency.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(module_source(module))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def at(hours: float) -> dt.datetime:
    return EPOCH + dt.timedelta(hours=hours)


def record(
    hour: float,
    value: float,
    *,
    quantity: str = "rainfall",
    domain: str = "rainfall",
    unit: str = "mm",
    location: str = "F1",
) -> Observation:
    return Observation(
        domain=domain,
        location_reference=location,
        observed_at=at(hour).isoformat().replace("+00:00", "Z"),
        measurements=(Measurement(quantity=quantity, value=value, unit=unit),),
    )


# --------------------------------------------------------------------------- #
# A Phase 2 stand-in
# --------------------------------------------------------------------------- #


@dataclass
class Phase2Result:
    """The Phase 2 output, in the shape Phase 3 reads.

    Duck-typed rather than imported so the boundary can be tested from both
    sides: a change to Phase 2's real result type must not be able to silently
    satisfy these tests by agreeing with themselves.
    """

    train: tuple = ()
    validation: tuple = ()
    test: tuple = ()
    dataset: object = None


def sample(hours: int = 48, *, train_until: int = 32, valid_until: int = 40) -> Phase2Result:
    """`hours` hourly readings of rainfall and water level, split three ways.

    Values are a recognisable ramp rather than random, so a wrong window shows up
    as a specific wrong number and can be checked by eye.
    """
    rain = [record(h, float(h % 5)) for h in range(hours)]
    level = [
        record(h, 1.0 + h * 0.1, quantity="water_level", domain="water_level", unit="m")
        for h in range(hours)
    ]

    def part(lo: int, hi: int) -> tuple:
        return tuple(rain[lo:hi]) + tuple(level[lo:hi])

    return Phase2Result(
        train=part(0, train_until),
        validation=part(train_until, valid_until),
        test=part(valid_until, hours),
    )


@pytest.fixture(scope="module")
def built():
    return pipeline.build_features(sample(), FeatureConfig())


@pytest.fixture(scope="module")
def dataset(built):
    return built.dataset


# --------------------------------------------------------------------------- #
# LEAKAGE 1 — features read nothing later than the prediction instant
# --------------------------------------------------------------------------- #


def test_leakage_1_no_feature_reads_later_than_its_origin(built, dataset) -> None:
    """The core claim, asserted on the produced rows rather than on the code.

    Every feature carries the instants it actually read, not merely the window it
    was supposed to read. If a window were implemented as `[T-w, T+w]` — centred,
    the classic mistake — the recorded instants would show it even though every
    configured number still said `at_prediction_instant`.
    """
    offenders = [
        (row.entity, row.instant, max(row.source_instants))
        for row in dataset.rows
        if row.source_instants and max(row.source_instants) > row.instant
    ]
    assert offenders == [], f"feature(s) read the future: {offenders[:3]}"


def test_leakage_1_the_audit_records_this_check_by_name(built) -> None:
    """An audit that reports `ok` without naming what it checked is an assertion,
    not evidence. A reader has to be able to see which checks actually ran."""
    audit = built.report.leakage
    assert "features_read_at_or_before_origin" in audit.names
    assert audit.ok
    assert audit.failures == ()
    assert len(audit.records) == 8


def test_leakage_1_deleting_the_future_changes_nothing(built) -> None:
    """The behavioural version, and the strongest of the three.

    Build the same dataset twice — once intact, once with every record after an
    origin instant removed. Any feature at that origin that changes has read the
    future, whatever the window arithmetic says. This catches the bug class
    directly rather than by proxy, and it is how the unknown-cadence state-cutoff
    defect was found.

    `audit_point_in_time` runs the check across the dataset for us and returns the
    findings, so the assertion is that it finds nothing.
    """
    findings = pipeline.audit_point_in_time(sample(), FeatureConfig(), probes=4)
    assert findings == (), findings


# --------------------------------------------------------------------------- #
# LEAKAGE 2 — every target instant is strictly after its origin
# --------------------------------------------------------------------------- #


def test_leakage_2_every_target_instant_is_strictly_in_the_future(built, dataset) -> None:
    """A target at or before its own origin is not a forecast; it is a
    restatement of something already observed, and a model would fit it exactly
    while reporting a perfect score."""
    offenders = [
        (row.entity, row.instant, name, instant)
        for row in dataset.rows
        for name, instant in row.target_instants.items()
        if instant is not None and instant <= row.instant
    ]
    assert offenders == [], offenders[:3]


def test_leakage_2_the_target_is_at_exactly_one_horizon(dataset) -> None:
    """Not merely later — at the configured horizon. A target drifted by a row
    would satisfy the first test and be wrong all the same."""
    horizon = dt.timedelta(seconds=dataset.config.target_seconds[0])
    for row in dataset.rows:
        for instant in row.target_instants.values():
            if instant is not None:
                assert instant - row.instant == horizon


# --------------------------------------------------------------------------- #
# LEAKAGE 3 — no column is both a feature and a target
# --------------------------------------------------------------------------- #


def test_leakage_3_the_feature_and_target_column_sets_are_disjoint(dataset) -> None:
    """The target must never enter the feature matrix. The `target_` prefix makes
    this checkable by a string test as well as by construction, and the registry
    refuses to build a feature name carrying that prefix."""
    features = set(dataset.feature_columns)
    targets = set(dataset.target_columns)
    assert features & targets == set()
    assert all(not name.startswith("target_") for name in features)
    assert all(name.startswith("target_") for name in targets)


def test_leakage_3_the_feature_matrix_has_no_target_column(built, dataset) -> None:
    """Checked on the matrix a consumer actually receives, not on the declared
    list. A row whose values dict happened to carry a target would slip past a
    column-name check entirely."""
    for row in dataset.rows:
        assert not any(name.startswith("target_") for name in row.values)
        assert set(row.values) == set(dataset.feature_columns)
        assert len(dataset.feature_matrix()[dataset.rows.index(row)]) == len(
            dataset.feature_columns
        )


# --------------------------------------------------------------------------- #
# LEAKAGE 4 — no imputation, forward-fill or interpolation
# --------------------------------------------------------------------------- #


def test_leakage_4_every_absent_value_is_a_recorded_absence_not_a_fill(built, dataset) -> None:
    """Absence must be visible. A feature matrix with a plausible number where the
    data was missing is worse than a `None`, because nothing downstream can tell
    the difference — and every one of those numbers was produced by borrowing an
    observation from the future."""
    filled = []
    for row in dataset.rows:
        for name, value in row.values.items():
            if value is None and name not in row.absent_reasons:
                filled.append((row.entity, row.instant, name))
    assert filled == [], filled[:3]


def test_leakage_4_a_missing_lag_is_absent_and_not_filled_from_its_neighbour(built, dataset) -> None:
    """The tempting fix — carry the last observation forward until the lag is
    satisfiable — is forward-fill, and it is leakage with a clean-looking column
    name. A hole in the middle of a series must stay a hole.

    The fixture has no holes, so one is cut deliberately: rainfall at hour 20 is
    removed, and the 1-hour lag at hour 21 must be absent.
    """
    holed = sample()
    kept = tuple(
        r
        for r in holed.train + holed.validation + holed.test
        if not (
            r.location_reference == "F1"
            and r.domain == "rainfall"
            and r.observed_at.startswith("2024-01-01T20")
        )
    )
    result = pipeline.build_features(
        Phase2Result(train=kept[:60], validation=kept[60:66], test=kept[66:]), FeatureConfig()
    )
    row = next(
        (r for r in result.dataset.rows if r.instant == at(21)),
        None,
    )
    assert row is not None
    assert row.values["rainfall_lag_1h"] is None
    assert row.absent_reasons["rainfall_lag_1h"] == temporal.CAUSE_MISSING_SOURCE


def test_leakage_4_the_policy_is_asserted_by_construction_not_by_detection(built) -> None:
    """The audit cannot *detect* a fill, so it says so rather than claiming a
    check it does not perform. Stating the limit of a check is part of the check."""
    audit = built.report.leakage
    record = next(r for r in audit.records if r[0] == "imputation_absent")
    assert record[1] is True
    assert "cannot detect a fill" in record[2]


# --------------------------------------------------------------------------- #
# LEAKAGE 5 — no row crosses a split boundary with its target
# --------------------------------------------------------------------------- #


def test_leakage_5_a_target_instant_never_lands_in_another_split(dataset) -> None:
    """Phase 2 splits the *records*. Phase 3 adds a second question: does a
    feature row's own target instant fall inside the same split as the row? If
    not, a training row is being asked to predict a value that belongs to the
    test period — which makes the eventual score meaningless without ever looking
    like cheating.

    Such rows are retained but have their target withheld, so the check is on the
    rows that *do* carry a target.
    """
    index = pipeline.build_split_index(pipeline.split_parts(sample()))
    offenders = []
    for row in dataset.rows:
        labels = index[row.entity].labels
        for name, instant in row.target_instants.items():
            if instant is None:
                continue  # absent target, not a misplaced one
            assert labels.get(instant, row.split) == row.split, (
                row.entity,
                row.instant,
                name,
                instant,
            )
    assert offenders == []


def test_leakage_5_a_crossing_target_is_withheld_rather_than_kept() -> None:
    """The other half: rows whose target would cross a boundary are kept as rows
    and lose their target. Deleting them would shrink the feature grid, which is
    information a forecaster still wants — the grid at that instant is real even
    if the answer is not available yet.
    """
    result = pipeline.build_features(sample(), FeatureConfig())
    withheld = [r for r in result.dataset.rows if not any(v is not None for v in r.targets.values())]
    assert withheld, "the tail of the series cannot be supervised"
    for row in withheld:
        assert all(v is None for v in row.targets.values())


def test_leakage_5_the_split_order_is_train_then_validation_then_test(dataset) -> None:
    """Checked on the instants rather than on the labels, because labels can be
    assigned in any order while instants cannot go backwards."""
    order = {pipeline.SPLIT_TRAIN: 0, pipeline.SPLIT_VALIDATION: 1, pipeline.SPLIT_TEST: 2}
    for split in ("train", "validation", "test"):
        instants = [r.instant for r in dataset.by_split(split)]
        assert instants == sorted(instants)
    firsts = [dataset.by_split(s)[0].instant for s in ("train", "validation", "test")]
    assert firsts == sorted(firsts)
    assert len(set(firsts)) == 3
    assert order["train"] < order["validation"] < order["test"]


def test_leakage_5_the_three_splits_partition_the_rows_exactly(dataset) -> None:
    """No row unaccounted for, no row counted twice. A row in two splits would be
    trained on and evaluated at once."""
    total = sum(len(dataset.by_split(s)) for s in ("train", "validation", "test"))
    assert total == len(dataset.rows)
    keys = [
        (r.entity, r.instant) for s in ("train", "validation", "test") for r in dataset.by_split(s)
    ]
    assert len(set(keys)) == len(keys)


# --------------------------------------------------------------------------- #
# LEAKAGE 6 — entity isolation
# --------------------------------------------------------------------------- #


def test_leakage_6_one_entities_features_are_unaffected_by_another() -> None:
    """The strongest form of the isolation claim: perturb station B and check that
    every value at station A is byte-identical.

    A filter applied after the fact would pass a structural test — the keys are
    right, the scopes are right — while still letting the wrong reading in. Only a
    perturbation test can tell the difference.
    """
    base = sample()
    doubled = Phase2Result(
        train=base.train,
        validation=base.validation,
        test=base.test
        + tuple(
            Observation(
                domain=r.domain,
                location_reference="F2",
                observed_at=r.observed_at,
                measurements=r.measurements,
            )
            for r in base.test
        ),
    )
    left = pipeline.build_features(base, FeatureConfig()).dataset
    right = pipeline.build_features(doubled, FeatureConfig()).dataset

    def at_f1(ds):
        return {
            (r.entity, r.instant): (r.values, r.targets)
            for r in ds.rows
            if r.entity == "F1"
        }

    assert at_f1(right) == at_f1(left)


def test_leakage_6_a_rainfall_lag_cannot_resolve_to_a_water_level_reading() -> None:
    """Two series at the same station and the same instants. Nothing but the
    three-level measurement key stands between them, so the check is that the two
    feature families read from their own keys."""
    result = pipeline.build_features(sample(), FeatureConfig())
    units = result.dataset.units
    rainfall = next(k for k in units if k.endswith("|rainfall|rainfall"))
    level = next(k for k in units if k.endswith("|water_level|water_level"))
    assert rainfall != level
    definitions = {d.name: d for d in result.dataset.registry.definitions}
    assert definitions["rainfall_lag_1h"].source_quantity == "rainfall"
    assert definitions["water_level_lag_1h"].source_quantity == "water_level"
    assert definitions["rainfall_lag_1h"].entity_scope == "measurement"


# --------------------------------------------------------------------------- #
# LEAKAGE 7 — no resampling, no re-gap-filling, no re-splitting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", PHASE3_MODULES)
def test_leakage_7_phase_three_does_not_resample_anything(module: str) -> None:
    """Phase 2 owns cadence. Re-deriving it here would give two answers to one
    question and quietly invalidate Phase 2's work, so Phase 3 reads the cadence
    Phase 2 inferred and never infers, resamples or fills its own."""
    assert not (identifiers(module) & RESAMPLING_VERBS), module


@pytest.mark.parametrize("module", PHASE3_MODULES)
def test_leakage_7_phase_three_never_writes_a_value_into_a_gap(module: str) -> None:
    """Forward-fill is the most tempting thing to add to a feature pipeline and
    the most damaging: it borrows a future observation to fill a hole, and the
    resulting column looks complete. The verb check above covers the library
    spellings; this covers the arithmetic one, which needs no library."""
    source = module_source(module)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert name not in {"nan_to_num", "fill_between"}, (module, name)
    # `previous` / `last` as a *source of a feature value* is the same move spelled
    # in prose. The temporal module may hold a previous instant for a cutoff, but
    # it must never hand one to an operation as a value.
    temporal_tree = ast.parse(module_source("feature_temporal.py"))
    calls = {
        (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        for node in ast.walk(temporal_tree)
        if isinstance(node, ast.Call)
    }
    assert "latest_at_or_before" in calls  # present: the cutoff fallback needs it
    assert not calls & {"fill", "carry_forward", "last_known"}


def test_leakage_7_the_cadence_reported_is_the_cadence_phase_two_inferred() -> None:
    """`resolve_cadence` asks Phase 2's own `infer_base_interval` rather than
    parsing Phase 2's prose report. Two sources of truth for a cadence is how a
    dataset ends up with features that disagree with its own preprocessing."""
    from app.engines.hydro.preprocess_temporal import infer_base_interval

    records = tuple(
        r for r in sample().train + sample().validation + sample().test
    )
    resolved = pipeline.resolve_cadence(records)
    assert resolved, "cadence must be resolved for the series that exist"
    for cadence in resolved.values():
        _location, domain = cadence.series.split("|", 1)
        same_domain = [r for r in records if r.domain == domain]
        assert cadence.seconds == infer_base_interval(same_domain).seconds, cadence.series


def test_leakage_7_phase_three_does_not_move_a_boundary_between_splits() -> None:
    """Every record in the input must appear in exactly one output split, at the
    same instant. A row that migrated from test to train would be trained on data
    the split was built to exclude."""
    result = pipeline.build_features(sample(), FeatureConfig())
    index = pipeline.build_split_index(pipeline.split_parts(sample()))
    for entity, split_index in index.items():
        instants = sorted(split_index.labels)
        assert instants == sorted(
            r.instant for r in result.dataset.rows if r.entity == entity
        )[: len(instants)]
        assert set(split_index.labels.values()) <= {
            pipeline.SPLIT_TRAIN,
            pipeline.SPLIT_VALIDATION,
            pipeline.SPLIT_TEST,
        }


def test_leakage_7_a_colliding_boundary_is_reported_rather_than_resolved_quietly() -> None:
    """Where two splits claim the same instant, the earlier label wins and the
    collision is reported. Preferring the *later* one silently would let a test
    instant masquerade as a training instant.

    The check is on the instant that actually collides — hours 32 to 39, which
    the fixture puts in validation and test alike. Hour 0 is uninteresting: only
    train claims it.
    """
    base = sample()
    overlapping = Phase2Result(train=base.train, validation=base.validation, test=base.validation)
    parts = pipeline.split_parts(overlapping)

    collisions = pipeline.split_collisions(parts)
    assert collisions, "an overlap between splits must be reported"

    index = pipeline.build_split_index(parts)
    entity = next(iter(index))
    labels = index[entity].labels
    instant = dt.datetime(2024, 1, 2, 8, tzinfo=UTC)  # 32h in: validation and test
    assert instant in labels
    assert labels[instant] == pipeline.SPLIT_VALIDATION  # earliest in SPLITS order


def test_leakage_7_an_overlapping_split_is_reported_at_error_severity() -> None:
    """A dataset whose splits are not disjoint cannot support a feature matrix
    that means anything: training and evaluation would share instants.

    It is reported at `error` severity rather than raised, which is the
    distinction this package draws throughout — raising when the output would be
    empty and unusable, reporting when the output exists but cannot be trusted.
    A caller that never reads `report.errors` can still get a dataset out of a
    broken one, so the guarantee is stated as a checkable property of the report
    rather than as an exception that happens not to fire.
    """
    base = sample()
    overlapping = Phase2Result(train=base.train, validation=base.validation, test=base.validation)
    result = pipeline.build_features(overlapping, FeatureConfig())
    errors = [note for note in result.report.errors]
    assert errors, "an overlapping split must reach error severity"
    assert any("claimed by" in note.message for note in errors), [n.message for n in errors]
    # The default run of the same fixture has no such error, so the severity is
    # caused by the collision and not by the fixture.
    clean = pipeline.build_features(sample(), FeatureConfig())
    assert not [n for n in clean.report.errors if "claimed by" in n.message]


# --------------------------------------------------------------------------- #
# Row policies
# --------------------------------------------------------------------------- #


def test_the_default_retains_rather_than_drops(dataset) -> None:
    """Dropping rows is the one irreversible thing this package does, so it is
    never the default and the retained count must equal the built count."""
    assert len(dataset.rows) == 48
    assert dataset.dropped == {}


def test_a_drop_policy_reports_exactly_what_it_dropped_and_why() -> None:
    """Opt-in and counted. A drop policy nobody can audit is a filter."""
    result = pipeline.build_features(sample(), FeatureConfig(warmup_policy=WARMUP_DROP_ROWS))
    dropped = result.dataset.dropped
    assert dropped, "a drop policy must actually drop something to be observable"
    assert len(result.dataset.rows) + sum(dropped.values()) == 48
    assert all(isinstance(reason, str) and reason for reason in dropped)


def test_no_policy_ever_returns_an_empty_dataset() -> None:
    """Checked across the policy space rather than one configuration, because the
    failure mode is a policy combination rather than a single setting.

    The guarantee is not that rows survive — a drop policy asked to drop is
    obliged to drop — but that the caller is never handed an empty dataset
    without being told why. A refusal naming the two policies is a better
    outcome than an empty matrix, and a far better one than an empty matrix with
    no explanation.
    """
    for missing in ("retain", MISSING_DROP_ROWS):
        for warmup in ("retain", WARMUP_DROP_ROWS):
            config = FeatureConfig(missing_policy=missing, warmup_policy=warmup)
            try:
                result = pipeline.build_features(sample(), config)
            except pipeline.FeatureError as refusal:
                message = str(refusal)
                assert "retained none of them" in message, message
                assert "missing_policy" in message and "warmup_policy" in message, message
            else:
                assert result.dataset.rows, (missing, warmup)


def test_rows_without_a_target_are_counted_and_kept() -> None:
    """The tail of the series cannot be supervised, but it is still a row a
    consumer may want to forecast from. Deleting it would silently shrink the
    feature grid."""
    result = pipeline.build_features(sample(), FeatureConfig())
    assert result.report.rows_without_target > 0
    assert len(result.dataset.rows) == 48


def test_supervised_rows_are_an_explicit_opt_in_view(dataset) -> None:
    """`supervised()` filters; it does not build something different. A consumer
    that forgets to call it gets every row, which is the safe default because the
    alternative is silently training on rows with no answer."""
    assert len(dataset.supervised()) < len(dataset.rows)
    assert all(
        all(v is not None for v in row.targets.values()) for row in dataset.supervised()
    )
    total = sum(len(v) for v in dataset.supervised_by_split().values())
    assert total == len(dataset.supervised())


# --------------------------------------------------------------------------- #
# Features that have no source
# --------------------------------------------------------------------------- #


def test_a_feature_with_no_source_is_declared_rather_than_silently_omitted(dataset) -> None:
    """The column exists, its value is `None`, and the reason says there is no
    discharge series. An absent column is invisible; a declared-unavailable one is
    a gap a reviewer can ask about."""
    assert "discharge_lag_1h" in dataset.feature_columns
    row = dataset.rows[0]
    assert row.values["discharge_lag_1h"] is None
    assert row.absent_reasons["discharge_lag_1h"] == temporal.CAUSE_NO_SOURCE


def test_a_feature_with_no_source_names_why_in_the_dataset(dataset) -> None:
    """The reason travels with the dataset, not only with the run's log. A
    consumer reading the dataset months later sees *why* a column is empty, which
    is the difference between a known gap and a suspected bug."""
    assert dataset.unavailable["discharge_lag_1h"]
    assert "no discharge" in dataset.unavailable["discharge_lag_1h"]
    assert "No substitute was invented" in dataset.unavailable["discharge_lag_1h"]


def test_the_unbuildable_catalogue_declares_what_this_dataset_lacks() -> None:
    """Nine features Phase 3 will not build for any input: six static ones with no
    source field anywhere, and three derived ones whose relationship has not been
    established.

    Including the rating-curve entry is the point. Inferred discharge from a water
    level is *not* built, because inventing it would look like data; it is
    declared, so a reader learns the capability is deliberately absent rather
    than merely missing.
    """
    catalogue = registry.UNAVAILABLE_STATIC_CATALOGUE
    assert len(catalogue.names) == registry.UNAVAILABLE_FEATURE_COUNT
    by_status: dict[str, list] = {}
    for name in catalogue.names:
        definition = catalogue.get(name)
        by_status.setdefault(definition.availability_requirement, []).append(definition)
    assert set(by_status) == {
        registry.AVAILABLE_NO_SOURCE,
        registry.AVAILABLE_NO_APPROVED_RELATIONSHIP,
    }
    # Six have no source field at all; three would need a relationship nobody has
    # established. The two counts are kept apart because they call for different
    # responses: one needs new data, the other needs an approved method.
    assert registry.UNAVAILABLE_STATIC_COUNT == len(by_status[registry.AVAILABLE_NO_SOURCE]) == 6
    assert len(by_status[registry.AVAILABLE_NO_APPROVED_RELATIONSHIP]) == 3
    assert registry.UNAVAILABLE_STATIC_COUNT < registry.UNAVAILABLE_FEATURE_COUNT
    assert any(n.startswith("static_") for n in catalogue.names)
    assert any(n.startswith("derived_") for n in catalogue.names)
    for name in catalogue.names:
        definition = catalogue.get(name)
        assert definition.availability_requirement != registry.AVAILABLE, name
        assert definition.rationale.strip(), name
        assert definition.description.strip(), name
        # The source is named as absent rather than left blank, so a reader can see
        # that the omission is a known gap and not an oversight.
        assert registry.NOT_AVAILABLE in definition.source_domain, (
            name,
            definition.source_domain,
        )


def test_the_report_counts_features_built_against_features_declared(built) -> None:
    """32 of 56 on the demo fixture. The gap is the finding, so it is reported
    against the whole rather than as a list of successes — and a count of 32
    printed on its own would read as a success."""
    counts = built.report.feature_counts
    assert len(counts) == len(built.dataset.registry.names) == 56
    built_names = {name for name, present in counts.items() if present}

    # The fixture carries rainfall and water level only, so 24 of the 56 declared
    # features have a source and 32 have none. The declared total is what a reader
    # compares against, so reporting only the successes would misrepresent this
    # dataset as better covered than it is.
    assert len(built_names) == 24
    assert len(built.dataset.registry.names) - len(built_names) == 32
    assert len(built.dataset.unavailable) == 32
    for family, expected_built, expected_total in (
        ("rainfall_", 12, 12),
        ("water_level_", 8, 8),
        ("calendar_", 4, 4),
        ("discharge_", 0, 8),
        ("temperature_", 0, 8),
        ("humidity_", 0, 8),
        ("inflow_", 0, 8),
    ):
        declared = [n for n in counts if n.startswith(family)]
        assert len(declared) == expected_total, family
        assert sum(1 for n in declared if n in built_names) == expected_built, family
        assert built_names & set(declared) or expected_built == 0, family


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def test_an_undetermined_unit_blocks_rates_but_not_copies() -> None:
    """Dividing an amount of unstated units by an hour yields a quantity whose
    units nobody can name. A lag is a copy and needs no interpretation, and a
    difference cancels the unit entirely."""
    result = pipeline.build_features(
        Phase2Result(
            train=tuple(
                record(h, float(h), quantity="inflow", domain="inflow", unit="UNDETERMINED")
                for h in range(12)
            )
        ),
        FeatureConfig(),
    )
    row = result.dataset.rows[5]
    assert row.values["inflow_lag_1h"] is not None  # a copy needs no unit
    assert row.values["inflow_change_1h"] is not None  # a difference cancels
    assert not [
        name for name in result.dataset.feature_columns if name.startswith("inflow_accum")
    ], "accumulating levels is not a quantity, so the operation is never offered"


def test_the_report_names_which_units_it_could_not_interpret(built) -> None:
    """Only fires where a unit is actually uninterpretable, so it needs its own
    fixture: the default sample has `mm` and `m`, both of which are understood."""
    result = pipeline.build_features(
        Phase2Result(
            train=tuple(
                record(h, float(h), quantity="inflow", domain="inflow", unit="UNDETERMINED")
                for h in range(12)
            )
        ),
        FeatureConfig(),
    )
    codes = {note.code for note in result.report.notes}
    assert pipeline.CODE_UNIT_UNDETERMINED in codes, sorted(codes)
    assert not pipeline.CODE_UNIT_UNDETERMINED in {
        note.code for note in built.report.notes
    }, "an understood unit must not be reported as uninterpretable"


def test_units_travel_with_the_dataset_and_are_never_rewritten(dataset) -> None:
    """mm stays mm. Phase 3 performs no conversion, so the unit in the output is
    the unit in the input, character for character."""
    assert dataset.units["F1|rainfall|rainfall"] == "mm"
    assert dataset.units["F1|water_level|water_level"] == "m"


def test_the_datum_limitation_is_stated_rather_than_resolved(built) -> None:
    """Two gauges' water levels are not comparable until someone establishes the
    datum. Phase 3 records that and does not convert."""
    codes = {note.code for note in built.report.notes}
    assert pipeline.CODE_DATUM_LIMITATION in codes


# --------------------------------------------------------------------------- #
# Synthetic labelling
# --------------------------------------------------------------------------- #


def test_a_dataset_with_no_descriptor_is_unverified_not_real(built) -> None:
    """The absence of a descriptor is not evidence of authenticity. With no
    provenance the only honest claim is that the values are unverified."""
    dataset = built.dataset
    assert dataset.is_synthetic is False
    assert "UNVERIFIED" in dataset.disclaimer()
    assert "must not be presented as a real observation" in dataset.disclaimer()


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_the_same_input_twice_gives_an_identical_dataset() -> None:
    """Including the report, the notes and their order. A dataset that is stable
    in its values but reorders its warnings is not reproducible, because nobody can
    then diff two runs to see what changed."""
    first = pipeline.build_features(sample(), FeatureConfig())
    second = pipeline.build_features(sample(), FeatureConfig())
    assert first.dataset.to_dict() == second.dataset.to_dict()
    assert first.report.to_dict() == second.report.to_dict()
    assert [n.to_dict() for n in first.report.notes] == [
        n.to_dict() for n in second.report.notes
    ]


def test_permuting_the_input_records_within_a_split_changes_nothing() -> None:
    """Input permutation must not alter the result after canonical ordering.

    Permuted *within* each split, deliberately. Re-partitioning the records would
    change which instants belong to which split, and a different split is a
    different dataset — the permutation guarantee is about the order records
    arrive in, not about where the boundaries are, and the boundary claim is
    tested separately.
    """
    base = sample()
    variants = {
        "reversed": Phase2Result(
            train=tuple(reversed(base.train)),
            validation=tuple(reversed(base.validation)),
            test=tuple(reversed(base.test)),
        ),
        "interleaved": Phase2Result(
            train=tuple(base.train[i] for i in _evens_then_odds(len(base.train))),
            validation=tuple(base.validation[i] for i in _evens_then_odds(len(base.validation))),
            test=tuple(base.test[i] for i in _evens_then_odds(len(base.test))),
        ),
        "sorted_by_instant": Phase2Result(
            train=tuple(sorted(base.train, key=lambda r: r.observed_at)),
            validation=tuple(sorted(base.validation, key=lambda r: r.observed_at)),
            test=tuple(sorted(base.test, key=lambda r: r.observed_at)),
        ),
    }
    expected = pipeline.build_features(base, FeatureConfig())
    baseline_notes = [n.to_dict() for n in expected.report.notes]
    for label, variant in variants.items():
        got = pipeline.build_features(variant, FeatureConfig())
        assert got.dataset.to_dict() == expected.dataset.to_dict(), label
        assert [n.to_dict() for n in got.report.notes] == baseline_notes, label


def _evens_then_odds(length: int) -> list[int]:
    """Every even index, then every odd one. An order no sort would produce."""
    return list(range(0, length, 2)) + list(range(1, length, 2))


def test_column_order_is_the_registry_order_not_an_accident_of_construction(dataset) -> None:
    """Published as part of the contract, so it comes from one ordered declaration
    rather than from dict or set iteration."""
    assert dataset.feature_columns == dataset.registry.names
    assert dataset.feature_columns[0] == "rainfall_lag_1h"
    assert dataset.feature_columns[-1] == "calendar_doy_cos"


def test_row_order_is_entity_then_instant(dataset) -> None:
    keys = [(r.entity, r.instant) for r in dataset.rows]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


# --------------------------------------------------------------------------- #
# The Phase 4 contract
# --------------------------------------------------------------------------- #


def test_the_model_ready_dataset_carries_no_fitted_anything() -> None:
    """A fitted scaler, imputer or encoder on these rows would put test
    information into the model's inputs, which is why none of it exists yet. That
    belongs to Phase 4, after the split.

    Checked against identifiers, not against the text: the docstring says "no
    fitted scaler, no fitted imputer", and a substring search would fail on the
    sentence stating the guarantee.
    """
    import dataclasses
    import importlib

    module = importlib.import_module("app.engines.hydro.feature_pipeline")
    ready = module.ModelReadyDataset
    fields = {f.name for f in dataclasses.fields(ready)}
    assert fields == {"dataset", "contract_version"}, fields

    tree = ast.parse(inspect.getsource(ready))
    forbidden = {"fit", "fit_transform", "partial_fit", "scaler", "imputer", "encoder"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            assert name not in forbidden, name

    # The contract is derived from the dataset on every call, never cached from a
    # previous one, so it cannot carry state forward.
    first = ready(dataset=build_default().dataset).to_dict()
    second = ready(dataset=build_default().dataset).to_dict()
    assert first == second
    assert not hasattr(ready, "cache")


def build_default():
    """The standard fixture build, for tests that need a dataset inline."""
    return pipeline.build_features(sample(), FeatureConfig())


def test_the_contract_publishes_columns_units_and_lineage() -> None:
    ready = pipeline.ModelReadyDataset(
        dataset=pipeline.build_features(sample(), FeatureConfig()).dataset
    )
    payload = ready.to_dict()
    assert payload["contract_version"] == registry.FEATURE_CONTRACT_VERSION
    assert payload["feature_columns"]
    assert payload["target_columns"]
    assert payload["lineage"]
    assert payload["target_lineage"]
    assert payload["disclaimer"]
    assert "samples" in payload
    json.dumps(payload)  # a contract that cannot be serialized is not a contract


def test_the_contract_samples_are_real_rows_not_illustrations() -> None:
    """A worked example built by hand would drift from the data and would not be
    caught by any test. These come from the dataset, so a consumer checking the
    contract is checking the real shape."""
    ready = pipeline.ModelReadyDataset(
        dataset=pipeline.build_features(sample(), FeatureConfig()).dataset
    )
    payload = ready.to_dict()
    for split, rows in payload["samples"].items():
        assert rows, split
        for row in rows:
            assert set(row) >= {"entity", "instant", "split", "features", "targets"}
            assert set(row["features"]) == set(ready.feature_columns)
            assert set(row["targets"]) == set(ready.target_columns)


def test_target_lineage_says_the_target_is_not_available_at_prediction_time(built) -> None:
    """The one thing every target's lineage must say. A target that was available
    at prediction time would not be a target, and a consumer reading the contract
    has no other way to tell."""
    assert built.dataset.target_lineage
    for name, lineage in built.dataset.target_lineage.items():
        assert lineage["available_at_prediction_time"] is False, name
        assert lineage["alignment"] == "exact", name
        assert lineage["horizon_seconds"] > 0, name


def test_target_lineage_names_the_source_it_comes_from(built) -> None:
    """`target_water_level_6h` traces to a water-level series six hours ahead. The
    lineage is what lets a consumer check that the target is the thing they
    meant, rather than trusting the column name."""
    lineage = built.dataset.target_lineage["target_water_level_6h"]
    assert lineage["source"] == "water_level"
    assert lineage["quantity"] == "water_level"
    assert lineage["horizon_label"] == "6h"
    assert lineage["unit"] == "m"


# --------------------------------------------------------------------------- #
# Scope guards — read the source with `ast`
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", PHASE3_MODULES)
def test_phase_three_imports_no_machine_learning_framework(module: str) -> None:
    """The forbidden list, stated first because it is the one that would change the
    shape of the project: an ML dependency here would mean Phase 3 had started
    being Phase 4."""
    assert not (imported_roots(module) & FORBIDDEN_IMPORTS)


def test_phase_three_imports_nothing_outside_the_standard_library() -> None:
    """Stronger than the forbidden list: the four modules import only `__future__`
    and the standard library. A convenience dependency added later — pandas for a
    rolling mean, say — is caught here even though it would have worked.

    Checked with `ast` rather than by inspecting `sys.modules`, because importing
    any `hydro` submodule runs the package `__init__`, which already loads NumPy
    through the pre-Phase-1 synthetic generator. A runtime check would flag that
    pre-existing behaviour as a Phase 3 regression, which would be both wrong and
    a reason to stop looking. What matters is what *this module* says it imports.
    """
    for module in PHASE3_MODULES:
        roots = imported_roots(module)
        allowed = _STDLIB | {"__future__"}
        unexpected = roots - allowed
        assert not unexpected, (module, sorted(unexpected))


def test_phase_three_never_fits_a_model() -> None:
    """No `fit`, no `predict`, no estimator, anywhere in the four modules.

    `PHASE 3 DOES NOT TRAIN MODELS` is a scope boundary, and a boundary that is
    only written in a document is a boundary that erodes.
    """
    fitting = frozenset({"fit", "fit_transform", "predict", "train_test_split"})
    for module in PHASE3_MODULES:
        for node in ast.walk(ast.parse(module_source(module))):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                assert name not in fitting, (module, name)


def test_phase_three_reports_no_accuracy_metric() -> None:
    """No RMSE, MAE, R², accuracy or information criterion. Phase 3 evaluates
    nothing, and publishing an accuracy number here would be an invented metric."""
    banned = ("rmse", "mean_absolute_error", "r2_score", "r_squared", "accuracy_score")
    for module in PHASE3_MODULES:
        lowered = module_source(module).lower()
        for term in banned:
            assert term not in lowered, (module, term)


def test_phase_three_does_not_import_the_legacy_feature_layer() -> None:
    """`features.py` is the pre-Phase-1 pandas layer, consumed by `training.py`
    and `engine.py`. Phase 3 is a parallel record-based path; importing the other
    one would couple a new module to code this project has decided not to extend.
    """
    for module in PHASE3_MODULES:
        tree = ast.parse(module_source(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "features", module
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "features", module


def test_phase_three_does_not_reach_into_another_teams_module() -> None:
    """Phase 3 reads Phase 1 and Phase 2 and nothing else. Reaching for the API,
    the ORM or the model layer would be an integration done by editing someone
    else's code, which this project does not do.
    """
    foreign = ("app.api", "app.models", "app.schemas", "app.db", "app.core")
    for module in PHASE3_MODULES:
        for node in ast.walk(ast.parse(module_source(module))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(foreign), (module, node.module)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(foreign), (module, alias.name)


@pytest.mark.parametrize("module", PHASE3_MODULES)
def test_every_exported_name_is_actually_defined(module: str) -> None:
    """A stale `__all__` entry is an `ImportError` in production that no reviewer
    would see and no other test would catch. Resolved by importing the module and
    asking whether the name is there.
    """
    imported = importlib.import_module(f"app.engines.hydro.{module[:-3]}")
    assert imported.__all__, f"{module} has no __all__"
    missing = [name for name in imported.__all__ if not hasattr(imported, name)]
    assert missing == [], (module, missing)
    assert len(set(imported.__all__)) == len(imported.__all__), "duplicate export"


def test_the_phase_three_modules_are_importable_without_the_team_contract() -> None:
    """The four modules must not pull in the Pydantic schemas or the engine.

    `hydro.__init__` resolves `HydroForecastEngine` lazily, and that name needs
    `app.schemas.models`, which is a teammate's file. Phase 3 depending on it
    would make the feature pipeline unimportable wherever the API layer is absent.
    """
    for module in PHASE3_MODULES:
        imported = importlib.import_module(f"app.engines.hydro.{module[:-3]}")
        source = inspect_source(imported)
        assert "app.schemas" not in source
        assert "app.engines.hydro.engine" not in source


def inspect_source(module) -> str:
    import inspect

    try:
        return inspect.getsource(module)
    except OSError:  # pragma: no cover - source is always available in-tree
        return module_source(module.__name__.rsplit(".", 1)[-1] + ".py")
