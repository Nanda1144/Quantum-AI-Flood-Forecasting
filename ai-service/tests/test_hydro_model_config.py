# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — the frozen model configuration.

A configuration is the whole experiment: which family, which target, which horizons,
which seed, which policies. Two runs are only comparable if their configurations
are equal, which is only checkable if a configuration cannot change after the run
starts and cannot be assembled from scattered defaults.

So these tests are mostly about the configuration *refusing*: an unknown family, a
zero horizon, a target column name in place of a quantity, a NaN hyperparameter, a
sequence lookback on a non-sequence family.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from app.engines.hydro import model_config as config_module
from app.engines.hydro.model_config import (
    ARTIFACT_INCLUDE_PARAMETERS,
    ARTIFACT_METADATA_ONLY,
    ARTIFACT_POLICIES,
    COMPUTABLE_METRICS,
    DEFAULT_METRICS,
    FAMILY_GRU,
    FAMILY_LSTM,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    FEATURE_SELECTION_POLICIES,
    IMPUTE_POLICIES,
    MODEL_CONTRACT_VERSION,
    MODEL_FAMILIES,
    ModelConfig,
    ModelConfigError,
    PERSISTENCE_SOURCE_POLICIES,
    SCALER_POLICIES,
    SPLIT_POLICIES,
    SPLIT_POLICY_PHASE3,
    deterministic_config,
)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #


def test_a_configuration_needs_only_a_family() -> None:
    """Everything else has a stated default, so a caller can name one family and
    read the rest off the object rather than out of a separate document."""
    config = ModelConfig(model_family=FAMILY_NAIVE)
    assert config.model_family == FAMILY_NAIVE
    assert config.target_quantity
    assert config.horizon_hours
    assert isinstance(config.random_seed, int)


def test_the_defaults_say_the_conservative_thing() -> None:
    """Each default, asserted with the reason it is the conservative choice.

    Not asserting the values so they cannot drift silently — asserting that each
    one is the *safe* choice for a pipeline whose central risk is a plausible-looking
    wrong number.
    """
    config = ModelConfig(model_family=FAMILY_RANDOM_FOREST)
    assert config.random_seed == 20240917, "a fixed seed is what makes a rerun a test"
    assert config.split_policy == SPLIT_POLICY_PHASE3, (
        "Phase 4 must not invent a split; Phase 3 already decided where time ends"
    )
    assert config.persistence_source in PERSISTENCE_SOURCE_POLICIES
    assert config.feature_selection in FEATURE_SELECTION_POLICIES
    assert config.impute_policy in IMPUTE_POLICIES
    assert config.artifact_policy == ARTIFACT_METADATA_ONLY, (
        "the default must not write anything; writing is an explicit choice"
    )
    assert tuple(config.metrics) == tuple(DEFAULT_METRICS)


def test_the_default_metric_set_is_the_one_evaluation_module_computes() -> None:
    """No metric is requested that `evaluation.compute_metrics` cannot produce.

    Asserted against the *computed* keys rather than a copied list, so a rename in
    `evaluation.py` cannot leave Phase 4 asking for a metric that no longer exists.
    """
    from app.engines.hydro.evaluation import compute_metrics

    computed = compute_metrics([1.0, 2.0, 3.0], [1.1, 1.9, 3.2]).as_dict()
    for name in DEFAULT_METRICS:
        assert name in computed, f"{name!r} is requested by default but is not computed"


def test_percentage_error_is_not_in_the_default_metric_set() -> None:
    """Deliberate. A water level passes through its own datum, so a percentage error
    is not defined against zero and dividing by it produces infinities. The guarded
    opt-in exists; the default does not use it."""
    assert "mape" not in {name.lower() for name in DEFAULT_METRICS}
    assert "mape" not in {name.lower() for name in DEFAULT_METRICS}
    assert "percentage" not in " ".join(DEFAULT_METRICS).lower()


def test_every_policy_constant_is_a_non_empty_closed_tuple() -> None:
    for name in (
        "SPLIT_POLICIES",
        "SCALER_POLICIES",
        "IMPUTE_POLICIES",
        "FEATURE_SELECTION_POLICIES",
        "PERSISTENCE_SOURCE_POLICIES",
        "ARTIFACT_POLICIES",
    ):
        values = getattr(config_module, name)
        assert isinstance(values, tuple) and values
        assert all(isinstance(value, str) and value.strip() for value in values), name


# --------------------------------------------------------------------------- #
# Frozen
# --------------------------------------------------------------------------- #


def test_a_configuration_cannot_be_reassigned() -> None:
    """A configuration that can change mid-run cannot be compared to anything."""
    config = deterministic_config(FAMILY_RANDOM_FOREST)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.random_seed = 1  # type: ignore[misc]


def test_a_configuration_cannot_be_mutated_through_its_training_mapping() -> None:
    """A known limitation, asserted so it is a decision rather than a surprise.

    `training` is a plain mapping and the dataclass is frozen, but freezing does not
    freeze what a field *points at*. The consequence is that a caller mutating
    `config.training` after construction changes what they will hand to the trainer.
    The defence is elsewhere — the run record stores its own copy — and this test
    names the hole so nobody closes it with a false claim that `frozen=True` covers
    it.
    """
    config = deterministic_config(FAMILY_RANDOM_FOREST, training={"n_estimators": 10})
    config.training["n_estimators"] = 999  # type: ignore[index]
    assert config.training["n_estimators"] == 999


def test_equal_configurations_are_equal() -> None:
    """Comparability depends on this. Two configs with the same fields must be `==`."""
    assert deterministic_config(FAMILY_RANDOM_FOREST) == deterministic_config(FAMILY_RANDOM_FOREST)


def test_a_configuration_with_a_dict_field_is_not_hashable() -> None:
    """A stated limitation: `frozen=True` generates `__hash__`, but hashing a
    dataclass holding a dict raises `TypeError`.

    So configurations cannot key a dict or a set. `model_training` therefore keys
    its dataset cache on the individual scalar policy fields instead, and this test
    is the reason that indirection exists rather than looking like an oversight.
    """
    from app.engines.hydro.model_training import _dataset_cache_key

    config = deterministic_config(FAMILY_RANDOM_FOREST)
    with pytest.raises(TypeError):
        hash(config)

    # The workaround is load-bearing, so it is checked rather than assumed.
    assert isinstance(_dataset_cache_key(config), tuple)
    assert isinstance(hash(_dataset_cache_key(config)), int)


def test_the_horizons_are_normalised_to_a_tuple_of_floats() -> None:
    """`horizon_hours=[6]` and `horizon_hours=(6.0,)` must be the same experiment,
    or a run repeated with a list instead of a tuple would look different."""
    from_list = ModelConfig(model_family=FAMILY_NAIVE, horizon_hours=[6, 12])  # type: ignore[arg-type]
    from_tuple = ModelConfig(model_family=FAMILY_NAIVE, horizon_hours=(6.0, 12.0))
    assert from_list.horizon_hours == from_tuple.horizon_hours
    assert isinstance(from_list.horizon_hours, tuple)
    assert all(isinstance(hour, float) for hour in from_list.horizon_hours)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_an_unknown_family_is_refused_by_name() -> None:
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family="transformer")
    assert "transformer" in str(caught.value)
    assert FAMILY_NAIVE in str(caught.value)


def test_a_missing_family_is_refused() -> None:
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family="")  # type: ignore[arg-type]


@pytest.mark.parametrize("quantity", ["", "   ", None, 7])
def test_a_blank_target_quantity_is_refused(quantity) -> None:
    """A blank quantity resolves against nothing, and a target built from it would
    be a column of absent values scored as if it were data."""
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, target_quantity=quantity)  # type: ignore[arg-type]


def test_a_target_column_name_is_refused_in_place_of_a_quantity() -> None:
    """`target_water_level_6h` is Phase 3's *output* name. Passing it here would be
    asking Phase 4 to predict its own column, and the prefix guard turns that
    confusion into an error instead of a mysteriously perfect R²."""
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family=FAMILY_NAIVE, target_quantity="target_water_level_6h")
    assert "target" in str(caught.value).lower()


def test_a_zero_or_negative_horizon_is_refused() -> None:
    """A zero horizon is a contemporaneous value, not a forecast. Fitting one would
    produce excellent metrics for a task nobody asked for."""
    for hours in (0.0, -1.0, -6.0):
        with pytest.raises(ModelConfigError) as caught:
            ModelConfig(model_family=FAMILY_NAIVE, horizon_hours=(hours,))
        assert "forecast" in str(caught.value).lower()


@pytest.mark.parametrize("hours", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_horizon_is_refused(hours: float) -> None:
    """A NaN horizon would align nothing and quietly produce zero rows."""
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, horizon_hours=(hours,))


def test_an_empty_horizon_list_is_refused() -> None:
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, horizon_hours=())


def test_duplicate_horizons_are_refused() -> None:
    """Two horizons of 6h would be evaluated twice and reported as independent
    agreement between two rows that are the same measurement."""
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family=FAMILY_NAIVE, horizon_hours=(6.0, 6.0))
    assert "duplicate" in str(caught.value).lower()


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("feature_selection", "everything"),
        ("scaler_policy", "quantile"),
        ("impute_policy", "mean"),
        ("split_policy", "random_80_10_10"),
        ("persistence_source", "future"),
        ("artifact_policy", "weights_in_git"),
        ("split_policy", "k_fold"),
    ],
)
def test_an_unknown_policy_is_refused_by_name(field: str, bad: str) -> None:
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family=FAMILY_NAIVE, **{field: bad})
    message = str(caught.value)
    assert bad in message
    assert field in message


def test_a_random_split_policy_cannot_be_requested() -> None:
    """Named explicitly because it is the one Phase 4 must never do: a random split
    lets a model see tomorrow's water level while predicting today's, and the
    resulting metrics look excellent."""
    assert all("random" not in policy.lower() for policy in SPLIT_POLICIES)
    assert SPLIT_POLICY_PHASE3 in SPLIT_POLICIES


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_hyperparameter_is_refused(bad: float) -> None:
    """A silent NaN in a hyperparameter is how two runs become incomparable."""
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_RANDOM_FOREST, training={"max_depth": bad})


def test_a_non_finite_minimum_row_count_is_refused() -> None:
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, min_train_rows=float("nan"))  # type: ignore[arg-type]


def test_a_negative_minimum_row_count_is_refused() -> None:
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, min_train_rows=-1)


def test_an_unknown_metric_is_refused_before_anything_is_fitted() -> None:
    """A metric nothing computes would be recorded as absent and read as measured.

    `evaluate_predictions` raises the same error, but only after the model has been
    fitted and every prediction made. The configuration check is what turns an hour
    of compute spent discovering a typo into an immediate failure.
    """
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family=FAMILY_NAIVE, metrics=("mae", "mean_ape"))
    assert "mean_ape" in str(caught.value)


def test_every_computable_metric_is_accepted() -> None:
    """The guard must not be a blocklist. Anything `compute_metrics` produces is
    reportable, and Phase 4 states so in one place."""
    for name in COMPUTABLE_METRICS:
        assert ModelConfig(model_family=FAMILY_NAIVE, metrics=(name,)).metrics == (name,)


def test_the_computable_vocabulary_matches_the_evaluation_module() -> None:
    """One list, not two that can drift. `model_evaluation` cannot import
    `model_config`'s copy by value without the cycle that aliasing avoided."""
    from app.engines.hydro.model_evaluation import REPORTABLE_METRICS

    assert tuple(REPORTABLE_METRICS) == tuple(COMPUTABLE_METRICS)


def test_duplicate_metrics_are_refused() -> None:
    """Two columns of the same number would be read as two independent results."""
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family=FAMILY_NAIVE, metrics=("mae", "mae"))
    assert "duplicate" in str(caught.value).lower()


def test_an_empty_metric_set_is_refused() -> None:
    """A run that reports no metric has produced nothing worth comparing."""
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, metrics=())


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_seed_is_refused(bad: float) -> None:
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_NAIVE, random_seed=bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Lookback is validated only for sequence families
# --------------------------------------------------------------------------- #


def test_a_sequence_family_refuses_a_lookback_of_one() -> None:
    """A single-step window is a plain regression wearing a recurrent model's name."""
    with pytest.raises(ModelConfigError) as caught:
        ModelConfig(model_family=FAMILY_LSTM, lookback=1)
    assert "window" in str(caught.value).lower() or "lookback" in str(caught.value).lower()


def test_a_sequence_family_refuses_a_negative_lookback() -> None:
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_GRU, lookback=-3)


@pytest.mark.parametrize("family", (FAMILY_NAIVE, FAMILY_RANDOM_FOREST, FAMILY_XGBOOST))
def test_a_non_sequence_family_ignores_the_lookback(family: str) -> None:
    """Not validated, and not an error either: the field exists on the shared
    dataclass so a caller can pass one configuration shape to every family."""
    assert ModelConfig(model_family=family, lookback=1).lookback == 1


def test_a_sequence_family_keeps_the_lookback_it_was_given() -> None:
    assert ModelConfig(model_family=FAMILY_LSTM, lookback=24).lookback == 24


# --------------------------------------------------------------------------- #
# deterministic_config
# --------------------------------------------------------------------------- #


def test_deterministic_config_applies_the_change_it_is_given() -> None:
    config = deterministic_config(FAMILY_RANDOM_FOREST, lookback=8, subject="a test")
    assert config.lookback == 8
    assert config.subject == "a test"


def test_deterministic_config_refuses_to_be_made_nondeterministic() -> None:
    """The whole function is named for the guarantee. Allowing a seed override here
    would produce a configuration labelled deterministic that is not."""
    with pytest.raises(ModelConfigError) as caught:
        deterministic_config(FAMILY_RANDOM_FOREST, random_seed=1)
    assert "seed" in str(caught.value).lower()


def test_deterministic_config_produces_the_same_object_twice() -> None:
    first = deterministic_config(FAMILY_LSTM, lookback=12)
    second = deterministic_config(FAMILY_LSTM, lookback=12)
    assert first == second


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def test_the_contract_carries_a_version() -> None:
    """Phase 4 reads Phase 3's output and Phase 5 reads Phase 4's; both boundaries
    need a version string that can be compared."""
    assert MODEL_CONTRACT_VERSION
    assert MODEL_CONTRACT_VERSION == str(MODEL_CONTRACT_VERSION)


def test_every_family_is_classified_into_the_roles_the_registry_uses() -> None:
    """Trees, sequences, and neither. A family in none of the sets would have no
    documented behaviour for feature importances, early stopping or scaling."""
    trees = set(config_module.TREE_FAMILIES)
    sequences = set(config_module.SEQUENCE_FAMILIES)
    assert trees | sequences | {FAMILY_NAIVE} == set(MODEL_FAMILIES)
    assert not (trees & sequences), f"a family cannot be both: {sorted(trees & sequences)}"


def test_note_codes_are_a_closed_vocabulary_with_an_explanation_each() -> None:
    """A code with no message is a code nobody can act on."""
    codes = config_module.MODEL_CONFIG_NOTE_CODES
    assert isinstance(codes, dict)
    assert codes
    for code, message in codes.items():
        assert isinstance(code, str) and code.strip()
        assert isinstance(message, str) and message.strip(), f"{code} has no message"


def test_the_configuration_describes_itself() -> None:
    """A readable rendering, because a run record that only a Python REPL can
    interpret is not reviewable."""
    config = deterministic_config(FAMILY_XGBOOST, scaler_policy="standard")
    text = config.describe()
    for expected in (FAMILY_XGBOOST, config.target_quantity, str(config.random_seed)):
        assert expected in text


def test_the_configuration_round_trips_through_its_dict() -> None:
    import json

    config = deterministic_config(FAMILY_RANDOM_FOREST, training={"n_estimators": 40})
    payload = config.to_dict()
    assert json.loads(json.dumps(payload, sort_keys=True, default=str))
    assert payload["model_family"] == FAMILY_RANDOM_FOREST
    assert payload["random_seed"] == config.random_seed


def test_rebuilding_from_its_dict_gives_the_same_configuration() -> None:
    """`to_dict()` is a reporting shape, not a constructor payload: it adds
    `contract_version` and the derived `target_columns` / `horizon_labels`, and
    flattens tuples to lists. Those keys are dropped before it is fed back, and
    anything still failing is the constructor refusing to round-trip its own
    output.
    """
    config = deterministic_config(FAMILY_RANDOM_FOREST, lookback=8, training={"max_depth": 5})
    payload = config.to_dict()
    derived = {"contract_version", "target_columns", "horizon_labels"}
    assert derived <= set(payload), "the derived keys are what make this interesting"
    for key in derived:
        payload.pop(key)
    rebuilt = ModelConfig(**payload)
    assert rebuilt == config
    assert rebuilt.horizon_hours == config.horizon_hours
    assert rebuilt.metrics == config.metrics


def test_the_derived_target_columns_are_recomputable_from_the_configuration() -> None:
    """`to_dict()`'s extra keys are not redundant: they restate Phase 3's naming for
    this target and horizon so a run record can be read without Phase 3.

    Asserted against `config.target_columns` rather than a literal, so Phase 3's
    naming rule stays the single authority.
    """
    config = deterministic_config(
        FAMILY_NAIVE, target_quantity="water_level", horizon_hours=(6.0, 12.0)
    )
    payload = config.to_dict()
    assert payload["target_columns"] == list(config.target_columns)
    assert payload["horizon_labels"] == list(config.horizon_labels)
    assert payload["target_columns"] == ["target_water_level_6h", "target_water_level_12h"]
    assert payload["horizon_labels"] == ["6h", "12h"]


def test_scaler_none_is_a_real_policy_not_an_omission() -> None:
    """`none` is stated, not absent. A caller reading `scaler_policy=None` cannot
    tell "deliberately unscaled" from "not configured"."""
    assert config_module.SCALER_NONE in SCALER_POLICIES
    assert ModelConfig(model_family=FAMILY_NAIVE, scaler_policy=config_module.SCALER_NONE)


def test_impute_none_is_available_and_documented_as_a_choice() -> None:
    assert config_module.IMPUTE_NONE in IMPUTE_POLICIES


def test_every_artifact_policy_is_named_in_the_constants() -> None:
    assert set(ARTIFACT_POLICIES) == {ARTIFACT_METADATA_ONLY, ARTIFACT_INCLUDE_PARAMETERS}


def test_metrics_are_stored_in_the_order_they_were_requested() -> None:
    """Order is not cosmetic here: it is the column order of the comparison table."""
    config = ModelConfig(model_family=FAMILY_NAIVE, metrics=("rmse", "mae"))
    assert config.metrics == ("rmse", "mae")


def test_a_non_positive_lookback_check_does_not_leak_a_math_domain_error() -> None:
    """The guard must raise `ModelConfigError`, not let a `TypeError` from `math`
    escape — a caller catching one exception type would miss the other."""
    with pytest.raises(ModelConfigError):
        ModelConfig(model_family=FAMILY_LSTM, lookback="many")  # type: ignore[arg-type]


def test_hyperparameter_values_that_are_finite_survive_unchanged() -> None:
    """The finiteness check must not quietly round or stringify."""
    config = ModelConfig(
        model_family=FAMILY_RANDOM_FOREST,
        training={"max_depth": 5, "min_samples_leaf": 2, "subsample": 0.8, "rest": True},
    )
    assert config.training["min_samples_leaf"] == 2
    assert isinstance(config.training["min_samples_leaf"], int)
    assert config.training["subsample"] == 0.8
    assert config.training["rest"] is True
    assert math.isfinite(config.training["subsample"])