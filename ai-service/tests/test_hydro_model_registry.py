# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — the model registry.

The registry is what every other Phase 4 module reads to learn which model
families exist, what each is for, and what has to be installed before it can run.
If it is wrong, everything downstream is confidently wrong.

Most of these tests are about refusals: an unknown family is named rather than
approximated, an absent dependency reports *which* symbol could not be imported,
and nothing is ever marked production-ready.
"""

from __future__ import annotations

import json

import pytest

from app.engines.hydro import model_registry as registry
from app.engines.hydro.model_config import (
    FAMILY_GRU,
    FAMILY_LSTM,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    MODEL_FAMILIES,
    ROLE_BASELINE,
)

EXPECTED_FAMILIES = (
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    FAMILY_LSTM,
    FAMILY_GRU,
)

REQUIRED_ROW_FIELDS = frozenset(
    {
        "model_family",
        "display_name",
        "role",
        "implementation",
        "requires",
        "tunable",
        "supports_importances",
        "supports_early_stopping",
        "is_sequence",
        "minimum_train_rows",
        "minimum_lookback",
        "default_training",
        "production_ready_claimed",
        "notes",
        "available_here",
        "blocked_reason",
        "runtime_versions",
        "dependency_reports",
        "default_artifact_policy",
    }
)


# --------------------------------------------------------------------------- #
# Membership
# --------------------------------------------------------------------------- #


def test_the_registry_holds_exactly_the_five_declared_families() -> None:
    """All five, and no others.

    A sixth family nobody reviewed would be reachable by configuration; a family
    missing from the registry would still be reachable by a config that names it.
    """
    assert set(MODEL_FAMILIES) == set(EXPECTED_FAMILIES)
    assert {spec.model_family for spec in registry.MODEL_REGISTRY} == set(EXPECTED_FAMILIES)


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_every_family_has_a_spec(family: str) -> None:
    assert registry.spec_for(family).model_family == family


def test_spec_for_names_an_unknown_family_instead_of_guessing() -> None:
    """`KeyError` with the known names in it — not a silent nearest match."""
    with pytest.raises(KeyError) as caught:
        registry.spec_for("transformer")
    message = str(caught.value)
    assert "transformer" in message
    assert FAMILY_NAIVE in message


def test_validate_family_names_lists_every_offender() -> None:
    """Not just the first. Someone fixing a list of families needs all of it."""
    with pytest.raises(KeyError) as caught:
        registry.validate_family_names((FAMILY_NAIVE, "transformer", "svm"))
    message = str(caught.value)
    assert "transformer" in message
    assert "svm" in message


def test_validate_family_names_accepts_the_declared_set() -> None:
    registry.validate_family_names(EXPECTED_FAMILIES)


# --------------------------------------------------------------------------- #
# Roles, and the claim that is never made
# --------------------------------------------------------------------------- #


def test_exactly_one_family_carries_the_baseline_role() -> None:
    """A comparison with two yardsticks has no floor to measure against."""
    baselines = [
        family for family in EXPECTED_FAMILIES if registry.spec_for(family).role == ROLE_BASELINE
    ]
    assert baselines == [FAMILY_NAIVE]


def test_the_baseline_needs_nothing_beyond_the_standard_library() -> None:
    """A yardstick that can be blocked is not a yardstick.

    It could not be compared against anything on a machine where it happened to be
    unavailable, and a missing baseline is how a run quietly loses its floor.
    """
    spec = registry.spec_for(FAMILY_NAIVE)
    assert spec.requires == ()
    assert spec.is_available()
    assert spec.dependency_reports() == ()


def test_only_the_baseline_is_a_baseline_and_only_sequences_are_sequences() -> None:
    sequence_families = {f for f in EXPECTED_FAMILIES if registry.spec_for(f).is_sequence}
    assert sequence_families == {FAMILY_LSTM, FAMILY_GRU}


def test_nothing_is_marked_production_ready() -> None:
    """The refusal is asserted on every spec, not only on the blocked ones.

    A future edit that set this `True` on whichever family happened to train
    successfully would otherwise go unnoticed on a machine where nothing trained.
    """
    offenders = [
        spec.model_family
        for spec in registry.MODEL_REGISTRY
        if spec.production_ready_claimed
    ]
    assert offenders == []


def test_a_family_that_happens_to_be_available_here_is_still_not_production_ready() -> None:
    """Training successfully is not a qualification."""
    available = registry.available_families()
    assert available, "no family is available in this environment"
    for family in available:
        assert registry.spec_for(family).production_ready_claimed is False


# --------------------------------------------------------------------------- #
# Dependency requirements
# --------------------------------------------------------------------------- #


def test_every_requirement_states_what_it_is_for() -> None:
    """`module` alone does not tell a reader whether they need it."""
    for spec in registry.MODEL_REGISTRY:
        for requirement in spec.requires:
            assert requirement.purpose.strip(), (
                f"{spec.model_family} requires {requirement.module!r} without saying why"
            )


def test_naive_has_no_requirement_and_xgboost_requires_xgboost() -> None:
    naive = registry.spec_for(FAMILY_NAIVE)
    xgboost = registry.spec_for(FAMILY_XGBOOST)
    assert naive.requires == ()
    modules = {requirement.module for requirement in xgboost.requires}
    assert "xgboost" in modules


@pytest.mark.parametrize("family", (FAMILY_LSTM, FAMILY_GRU))
def test_the_sequence_families_name_a_runtime_they_actually_use(family: str) -> None:
    """Otherwise a build with no runtime could quietly substitute something else.

    `models.build_model` refuses `lstm`/`gru` by name for the same reason; a
    registry that listed neither would leave that refusal with nothing to consult.
    """
    modules = {requirement.module for requirement in registry.spec_for(family).requires}
    assert modules & {"keras", "tensorflow", "torch"}, (
        f"{family} names no deep-learning runtime: {sorted(modules)}"
    )


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_probing_a_family_reports_every_requirement(family: str) -> None:
    spec = registry.spec_for(family)
    reports = spec.availability()
    assert len(reports) == len(spec.requires)
    assert tuple(spec.requires) == tuple(report.requirement for report in reports)


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_an_absent_dependency_explains_itself(family: str) -> None:
    """The blocked reason must name the thing that could not be imported.

    "xgboost unavailable" is a status. "'xgboost.XGBRegressor' is not importable
    (ModuleNotFoundError)" is something a reader can act on.
    """
    spec = registry.spec_for(family)
    for report in spec.dependency_reports():
        if report.installed:
            assert not report.blocked_reason, (
                f"{report.import_path} is installed yet reports a blocker"
            )
            assert report.version
        else:
            assert report.blocked_reason
            assert report.requirement.module in report.blocked_reason


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_availability_agrees_with_the_probe(family: str) -> None:
    """`is_available()` must not be a cached opinion that drifts from reality."""
    spec = registry.spec_for(family)
    expected = all(report.installed for report in spec.dependency_reports())
    assert spec.is_available() is expected
    if expected:
        assert spec.blocker_text() is None
    else:
        assert spec.blocker_text()


def test_the_naive_baseline_is_available_whatever_else_is_missing() -> None:
    assert registry.spec_for(FAMILY_NAIVE).is_available()


# --------------------------------------------------------------------------- #
# Probing one requirement
# --------------------------------------------------------------------------- #


def test_probing_an_installed_module_reports_a_version() -> None:
    report = registry.probe(
        registry.DependencyRequirement("json", "dumps", "stdlib probe fixture")
    )
    assert report.installed is True
    assert report.version
    assert report.blocked_reason is None


def test_probing_an_absent_module_names_it_rather_than_raising() -> None:
    """Probing exists so a caller can *report* absence. It must not raise."""
    report = registry.probe(
        registry.DependencyRequirement(
            "navya_package_that_does_not_exist", "thing", "deliberately absent probe fixture"
        )
    )
    assert report.installed is False
    assert "navya_package_that_does_not_exist" in report.blocked_reason
    assert report.version is None


def test_a_missing_symbol_in_an_installed_module_is_still_a_blocker() -> None:
    """An old package can be present and lack the API.

    `DependencyRequirement.symbol` exists precisely for this, so a probe that only
    checked the package would report `installed` and then fail at fit time.
    """
    report = registry.probe(
        registry.DependencyRequirement(
            "json", "a_function_that_does_not_exist", "deliberately absent symbol fixture"
        )
    )
    assert report.installed is False
    assert report.blocked_reason


def test_probe_all_probes_exactly_what_it_is_given() -> None:
    """Order preserved, duplicates not collapsed: a caller listing a requirement
    twice should see it probed twice, not quietly deduplicated."""
    requirements = [
        registry.DependencyRequirement("json", "dumps", "stdlib probe fixture"),
        registry.DependencyRequirement(
            "navya_package_that_does_not_exist", "thing", "absent probe fixture"
        ),
        registry.DependencyRequirement("json", "dumps", "stdlib probe fixture"),
    ]
    reports = registry.probe_all(requirements)
    assert [report.requirement for report in reports] == requirements
    assert [report.installed for report in reports] == [True, False, True]


def test_probe_all_covers_every_requirement_in_the_registry() -> None:
    every = [
        requirement
        for spec in registry.MODEL_REGISTRY
        for requirement in spec.requires
    ]
    expected = {
        (requirement.module, requirement.symbol, requirement.purpose) for requirement in every
    }
    seen = {
        (report.requirement.module, report.requirement.symbol, report.requirement.purpose)
        for report in registry.probe_all(every)
    }
    assert seen == expected


def test_a_requirement_round_trips_through_its_dict() -> None:
    requirement = registry.DependencyRequirement("numpy", "ndarray", "probe fixture")
    assert registry.DependencyRequirement(**requirement.to_dict()) == requirement


def test_a_report_round_trips_the_fields_a_reader_needs() -> None:
    report = registry.probe(registry.DependencyRequirement("json", "dumps", "probe fixture"))
    payload = report.to_dict()
    assert set(payload) == {"import_path", "purpose", "installed", "version", "blocked_reason"}


# --------------------------------------------------------------------------- #
# Capabilities, stated as booleans
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_a_family_cannot_report_feature_importances_without_supporting_them(family: str) -> None:
    """Feature importance attributed to a model that has none is an invented column."""
    spec = registry.spec_for(family)
    if spec.supports_importances:
        assert spec.tunable, (
            f"{family} reports feature importances but declares nothing tunable"
        )


def test_only_the_families_that_can_be_held_out_report_early_stopping() -> None:
    """`xgboost` can. The persistence baseline cannot, and saying otherwise would
    invite a validation set handed to something that silently ignores it."""
    assert registry.spec_for(FAMILY_XGBOOST).supports_early_stopping is True
    assert registry.spec_for(FAMILY_NAIVE).supports_early_stopping is False


def test_minimum_rows_and_lookback_are_sane_where_declared() -> None:
    for spec in registry.MODEL_REGISTRY:
        assert spec.minimum_train_rows >= 1, (
            f"{spec.model_family} declares {spec.minimum_train_rows} minimum training rows"
        )
        if spec.is_sequence:
            assert spec.minimum_lookback >= 1, (
                f"{spec.model_family} is a sequence family with lookback "
                f"{spec.minimum_lookback}; a window of no length models nothing"
            )


def test_a_tunable_family_declares_its_default_hyperparameters() -> None:
    """A tunable family with no declared defaults means the defaults are whatever
    the third-party library happens to use this month."""
    for spec in registry.MODEL_REGISTRY:
        if spec.tunable:
            assert spec.default_training, f"{spec.model_family} is tunable but declares nothing"


# --------------------------------------------------------------------------- #
# Statuses are a closed vocabulary
# --------------------------------------------------------------------------- #


def test_training_statuses_distinguish_the_real_outcomes() -> None:
    """Five distinct reasons a model produced no numbers.

    "never ran" and "ran and failed" are different facts and a caller must be able
    to tell them apart; "not enough data" differs from both again.
    """
    assert set(registry.TRAINING_STATUSES) == {
        registry.STATUS_TRAINED,
        registry.STATUS_DEPENDENCY_UNAVAILABLE,
        registry.STATUS_TARGET_UNAVAILABLE,
        registry.STATUS_INSUFFICIENT_DATA,
        registry.STATUS_EVALUATION_UNAVAILABLE,
        registry.STATUS_FAILED_TRAINING,
    }


def test_evaluation_statuses_are_closed() -> None:
    assert set(registry.EVALUATION_STATUSES) == {
        registry.EVALUATION_DONE,
        registry.EVALUATION_NOT_RUN,
        registry.EVALUATION_INSUFFICIENT_ROWS,
        registry.EVALUATION_FAILED,
    }


def test_artifact_statuses_distinguish_metadata_from_parameters_from_nothing() -> None:
    assert set(registry.ARTIFACT_STATUSES) == {
        registry.ARTIFACT_STATUS_METADATA,
        registry.ARTIFACT_STATUS_WITH_PARAMETERS,
        registry.ARTIFACT_STATUS_NOT_WRITTEN,
    }


def test_synthetic_data_has_its_own_status_distinct_from_measured() -> None:
    """The two must never be confusable: one is a claim, the other is a refusal."""
    assert registry.DATA_STATUS_SYNTHETIC_DEMO != registry.DATA_STATUS_MEASURED
    assert registry.DATA_STATUS_SYNTHETIC_DEMO == "synthetic_demo"
    assert registry.DATA_STATUS_MEASURED == "measured"
    assert registry.DATA_STATUS_UNKNOWN == "unknown"


# --------------------------------------------------------------------------- #
# Machine-readable rows
# --------------------------------------------------------------------------- #


def test_registry_rows_carry_every_declared_field() -> None:
    """The dict form is what a document or a downstream service reads instead of
    the Python objects, so a field that exists only on the dataclass is invisible."""
    rows = registry.registry_rows()
    assert len(rows) == len(EXPECTED_FAMILIES)
    for row in rows:
        missing = REQUIRED_ROW_FIELDS - set(row)
        assert not missing, f"registry row for {row['model_family']} lacks {sorted(missing)}"


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_a_registry_row_never_claims_production_readiness(family: str) -> None:
    row = next(r for r in registry.registry_rows() if r["model_family"] == family)
    assert row["production_ready_claimed"] is False


def test_an_unavailable_family_says_why_in_its_row() -> None:
    """A row reading `available_here: false` and nothing else is not actionable."""
    rows = {row["model_family"]: row for row in registry.registry_rows()}
    for family, row in rows.items():
        if row["available_here"] is False:
            assert row["blocked_reason"], f"{family} is unavailable with no stated reason"


def test_available_and_blocked_partition_the_registry() -> None:
    available = set(registry.available_families())
    blocked = set(registry.blocked_families())
    assert available | blocked == set(EXPECTED_FAMILIES)
    assert not (available & blocked), f"families claimed both: {sorted(available & blocked)}"


def test_rows_are_json_serialisable() -> None:
    """A dict form whose whole purpose is to be read by something else."""
    payload = json.loads(json.dumps(registry.registry_rows(), sort_keys=True, default=str))
    assert len(payload) == len(EXPECTED_FAMILIES)


def test_runtime_versions_lists_only_the_packages_that_are_present() -> None:
    """A dict either way — the baseline's is legitimately empty because it needs
    nothing — but it must never invent a version for an absent package.

    Listing `xgboost: None` would let a reader conclude xgboost is installed at an
    unknown version rather than absent.
    """
    for spec in registry.MODEL_REGISTRY:
        versions = spec.runtime_versions()
        assert isinstance(versions, dict)
        installed = {
            report.requirement.import_path
            for report in spec.dependency_reports()
            if report.installed
        }
        assert set(versions) == installed
        assert all(version != "unknown" for version in versions.values())


def test_every_family_carries_a_note_a_reviewer_can_read() -> None:
    """A spec with an empty note keeps its caveats only in its author's head."""
    for spec in registry.MODEL_REGISTRY:
        assert spec.notes.strip(), f"{spec.model_family} has no note"
        assert spec.display_name.strip()
        assert spec.role.strip()
        assert spec.implementation.strip()


@pytest.mark.parametrize("family", EXPECTED_FAMILIES)
def test_a_spec_round_trips_through_its_dict(family: str) -> None:
    spec = registry.spec_for(family)
    payload = spec.to_dict()
    assert payload["model_family"] == family
    assert json.loads(json.dumps(payload, sort_keys=True, default=str))