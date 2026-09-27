# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.models`.

The registry is the place where a project is most tempted to lie — by listing a
model it cannot run, or by reporting a score for a network that was never
trained. These tests hold it to: every key is buildable, every unavailable
dependency is reported honestly, and the unimplemented roadmap stays separate
from the executable registry.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.engines.hydro.models import (
    FUTURE_MODEL_ROADMAP,
    MODEL_CANDIDATES,
    ModelError,
    ModelUnavailableError,
    build_model,
    candidate,
    describe_registry,
    registry_keys,
    unavailable_models,
)


def _x(n: int = 60, features: int = 3) -> np.ndarray:
    rng = np.linspace(0.0, 1.0, n)[:, None]
    return np.hstack([rng**i for i in range(1, features + 1)])


def _y(x: np.ndarray) -> np.ndarray:
    """A target from a 3-feature linear law with a non-zero intercept."""
    return x[:, :3] @ np.array([2.0, -1.0, 0.5]) + 0.25


def _registry() -> set[str]:
    return {entry.key for entry in MODEL_CANDIDATES}


# --- registry honesty --------------------------------------------------------


def test_every_registry_key_is_buildable():
    """Only keys advertised as available may be built without a dependency.

    `registry_keys(available_only=False)` also returns keys whose dependency is
    absent; building those is *supposed* to fail, and `test_available_keys_are_
    exactly_the_buildable_ones` asserts that.
    """
    available = registry_keys(available_only=True)
    assert available, "at least one model must be executable with numpy alone"
    for key in available:
        model = build_model(key)
        assert model.key == key
        assert model.display_name
        assert model.algorithm


def test_available_keys_are_exactly_the_buildable_ones():
    available = set(registry_keys(available_only=True))
    for key in available:
        build_model(key)  # must not raise
    for key in set(registry_keys(available_only=False)) - available:
        with pytest.raises(ModelUnavailableError):
            build_model(key)


def test_pure_numpy_candidates_are_always_available():
    """`linear` and `ridge` have no third-party dependency at all."""
    for key in ("linear", "ridge"):
        assert key in registry_keys(available_only=True)
        assert candidate(key).requires == ()


def test_unavailable_models_names_the_missing_import():
    for key, missing in unavailable_models().items():
        assert key in _registry()
        assert missing
        # The reason is a dotted import path, so an operator can act on it.
        assert "." in missing


def test_no_optional_candidate_is_silently_unavailable():
    """An unavailable model must say why, and the report must list it.

    A model that is quietly skipped looks identical to a model that was scored
    and lost, which would make an incomplete sweep read as a complete one.
    """
    for key, missing in unavailable_models().items():
        entry = candidate(key)
        assert entry.requires, f"{key} is unavailable but declares no requirement"
        assert entry.requires[0] == missing
        assert f"[unavailable" in describe_registry()
        assert key in describe_registry()


def test_building_an_unavailable_model_raises_with_the_reason():
    for key, missing in unavailable_models().items():
        with pytest.raises(ModelUnavailableError) as excinfo:
            build_model(key)
        assert missing in str(excinfo.value)


def test_unknown_model_key_is_rejected():
    with pytest.raises(ModelError, match="unknown model"):
        build_model("gpt-flood-9000")


# --- the roadmap is not part of the registry ---------------------------------


def test_future_roadmap_models_are_not_in_the_registry():
    """LSTM / GRU / QML are documented future work, never selectable.

    Asking for one is refused with the documented reason rather than as an
    unknown key, so a caller who reaches for an LSTM learns it is unimplemented
    instead of concluding it was never considered.
    """
    registry = _registry()
    for entry, reason in FUTURE_MODEL_ROADMAP.items():
        assert entry not in registry, f"{entry} is documented as future work but is selectable"
        with pytest.raises(ModelError) as excinfo:
            build_model(entry)
        message = str(excinfo.value)
        assert "NOT implemented" in message
        assert entry in message
        assert reason.split(";")[0].split("�")[0].strip() in message


def test_an_unknown_key_is_distinguishable_from_a_roadmap_key():
    """A typo must not be answered with a roadmap entry, and a roadmap entry must
    not be answered as a typo: the two mean different things to the caller."""
    with pytest.raises(ModelError) as unknown:
        build_model("lstm_typo")
    assert "unknown model" in str(unknown.value)

    with pytest.raises(ModelError) as roadmap:
        build_model("lstm")
    assert "unknown model" not in str(roadmap.value)


def test_future_roadmap_never_claims_implementation():
    """Every roadmap entry must appear in the registry report as NOT implemented.

    A future model that is merely unmentioned could later be quietly added; being
    listed explicitly is what makes the gap visible rather than latent.
    """
    text = describe_registry()
    for entry, reason in FUTURE_MODEL_ROADMAP.items():
        assert entry in text
        assert "NOT implemented" in text
        assert "not implemented" in reason.lower()


def test_describe_registry_marks_unavailable_and_unimplemented():
    text = describe_registry()
    assert "actually executable" in text
    assert "NOT implemented" in text
    for key in unavailable_models():
        assert f"[unavailable" in text


# --- the linear baseline -----------------------------------------------------


def test_linear_recovers_an_exact_linear_relationship():
    x = _x()
    model = build_model("linear").fit(x, _y(x))
    # `lstsq` solves [1 | X] y = target, so the full design has 4 columns.
    assert model.rank == 4
    assert np.allclose(np.asarray(model.coefficients), [2.0, -1.0, 0.5], atol=1e-8)
    assert model.intercept == pytest.approx(0.25, abs=1e-8)
    assert np.allclose(model.predict(x), _y(x), atol=1e-8)


def test_linear_predict_before_fit_is_refused():
    with pytest.raises(ModelError, match="not fitted"):
        build_model("linear").predict(_x())


def test_ridge_recovers_an_exact_linear_relationship_at_alpha_zero():
    """At alpha = 0 ridge is unregularised least squares.

    The unpenalised intercept is the target mean, so a centred design is required
    for the no-intercept term to reproduce the law exactly — which is the
    standard ridge formulation, and why the test uses a centred design rather
    than asserting exactness on arbitrary input.
    """
    x = _x()
    x = x - x.mean(axis=0)
    y = x @ np.array([2.0, -1.0, 0.5])
    model = build_model("ridge", {"alpha": 0.0}).fit(x, y)
    assert np.allclose(model.predict(x), y, atol=1e-8)


def test_ridge_shrinks_a_coefficient_towards_zero():
    x = _x(60, 12)
    truth = np.zeros(12)
    truth[:3] = [2.0, -1.0, 0.5]
    y = x @ truth + np.linspace(0, 0.01, 60)
    weak = np.asarray(build_model("ridge", {"alpha": 1e-6}).fit(x, y).coefficients)
    strong = np.asarray(build_model("ridge", {"alpha": 1e6}).fit(x, y).coefficients)
    # L2 regularisation must reduce the coefficient norm.
    assert np.linalg.norm(strong) < np.linalg.norm(weak)
    # A huge penalty must collapse the coefficients towards the origin, not
    # merely shrink them slightly.
    assert np.linalg.norm(strong) < 0.5


def test_ridge_handles_a_rank_deficient_matrix():
    x = _x(40, 4)
    x = np.hstack([x, x[:, :1]])  # duplicate column -> singular
    model = build_model("ridge", {"alpha": 1.0}).fit(x, _y(x[:, :4]))
    assert np.all(np.isfinite(np.asarray(model.coefficients)))
    assert np.all(np.isfinite(model.predict(x)))


def test_a_singular_ols_matrix_raises_rather_than_returning_nonsense():
    """OLS refuses a rank-deficient design instead of picking one solution.

    `np.linalg.lstsq` silently returns the minimum-norm solution when the design
    is singular. Presenting that arbitrary pick as "the coefficients" would be a
    fabricated fit, so the model stops and points at the regularised alternative.
    """
    x = _x(40, 4)
    x = np.hstack([x, x[:, :1]])  # duplicate column -> singular
    with pytest.raises(ModelError, match="not uniquely determined"):
        build_model("linear").fit(x, _y(x[:, :4]))


def test_a_singular_ols_matrix_is_still_fittable_with_ridge():
    """The same design fits cleanly once the penalty makes it invertible."""
    x = _x(40, 4)
    x = np.hstack([x, x[:, :1]])
    model = build_model("ridge", {"alpha": 1.0}).fit(x, _y(x[:, :4]))
    assert np.all(np.isfinite(np.asarray(model.coefficients)))


def test_fit_rejects_a_mismatched_target_length():
    with pytest.raises(ModelError):
        build_model("linear").fit(_x(20), np.zeros(5))


def test_fit_rejects_non_finite_features():
    """A NaN feature must stop the fit, not become a NaN "forecast".

    The pipeline fits a train-only imputer before this point, so a NaN reaching
    here means the caller bypassed it — and silently returning NaN would look
    like a value on the wire.
    """
    for key in ("linear", "ridge"):
        bad = _x(20)
        bad[0, 0] = np.nan
        with pytest.raises(ModelError, match="non-finite"):
            build_model(key).fit(bad, _y(bad))


def test_predict_rejects_non_finite_features_after_fitting():
    x = _x(40, 3)
    model = build_model("ridge").fit(x, _y(x))
    bad = _x(3, 3)
    bad[1, 2] = np.inf
    with pytest.raises(ModelError, match="non-finite"):
        model.predict(bad)


def test_fit_rejects_an_empty_design_matrix():
    with pytest.raises(ModelError):
        build_model("linear").fit(np.zeros((0, 3)), np.zeros(0))


def test_predict_rejects_a_width_mismatch_after_fitting():
    x = _x(40, 3)
    model = build_model("ridge").fit(x, _y(x))
    with pytest.raises(ModelError, match="feature"):
        model.predict(_x(5, 4))


# --- serialisation -----------------------------------------------------------


def test_linear_round_trips_through_a_parameter_dict():
    x = _x()
    model = build_model("linear").fit(x, _y(x))
    restored = build_model("linear").from_parameter_dict(model.to_parameter_dict())
    assert np.allclose(restored.coefficients, model.coefficients)
    assert restored.intercept == pytest.approx(model.intercept)
    assert np.allclose(restored.predict(x), model.predict(x))


def test_ridge_round_trips_and_keeps_alpha():
    x = _x()
    model = build_model("ridge", {"alpha": 3.5}).fit(x, _y(x))
    restored = build_model("ridge").from_parameter_dict(model.to_parameter_dict())
    assert restored.alpha == pytest.approx(3.5)
    assert np.allclose(restored.predict(x), model.predict(x))


def test_parameter_dict_is_json_friendly():
    import json

    payload = build_model("ridge", {"alpha": 2.0}).fit(_x(), _y(_x())).to_parameter_dict()
    text = json.dumps(payload)  # must not raise
    assert "numpy" not in text.lower()


def test_restoring_from_an_empty_dict_is_refused():
    """An artifact with no coefficients is corruption, not an unfitted model.

    The refusal has to happen at restore time, so the error names the artifact
    rather than surfacing later as a confusing "not fitted" on the first
    prediction call.
    """
    for key in ("linear", "ridge"):
        with pytest.raises(ModelError, match="no coefficients"):
            build_model(key).from_parameter_dict({})


# --- optional scikit-learn candidates ---------------------------------------


def test_sklearn_candidates_fit_and_predict_when_available():
    for key in ("random_forest", "gradient_boosting"):
        if key not in registry_keys(available_only=True):
            continue
        x = _x(80, 3)
        model = build_model(key).fit(x, _y(x))
        predictions = model.predict(x)
        assert len(predictions) == len(x)
        assert np.all(np.isfinite(predictions))
