# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""`HydroForecastEngine` — Navya's live forecasting engine behind the team seam.

Wiring
------
`app/engines/factory.py` resolves the active engine from `FORECAST_ENGINE` and
constructs it with **zero arguments**, so `HydroForecastEngine()` reads its
configuration from the environment (see `config.py`). The service is started
from the `ai-service/` directory (`uvicorn app.main:app`), which makes `app` the
top-level package, so the resolver value is:

    FORECAST_ENGINE=app.engines.hydro.engine:HydroForecastEngine

`ReferenceEngine` is untouched and remains selectable as the labelled
demo/fallback engine.

Honest-by-construction refusals
-------------------------------
The running `ForecastPrediction` contract (Nanda-owned) requires a `flood_probability`
in 0..1, a `risk_level` from LOW/MEDIUM/HIGH/CRITICAL, and a non-negative
`predicted_water_level`. Those three fields cannot be filled without facts the
repository does not contain. Rather than borrow the reference engine's demo
threshold, this engine **refuses to serve** and says exactly what is missing:

* No configured flood stage or risk-band edges → refuses (`is_usable`).
* No *measured* residual spread → refuses, because there is no distribution to
  integrate over and any probability would be invented.
* A target that is not `water_level` → refuses, because the team schema has no
  `predicted_inflow` field; serving an inflow forecast through
  `predicted_water_level` would be a mislabel. Training and evaluation support
  an inflow target; only *serving* through the current contract is blocked.

When the threshold policy is configured but not formally approved, forecasts are
still served with `status="pending"` (a value the schema already allows) and the
risk assessor records that the bands are configured rather than official.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from app.schemas.models import (
    ForecastPoint,
    ForecastPrediction,
    ModelInfo,
    ModelMetrics,
    ModelStatus,
    PredictionRecord,
    RiskAnalytics,
    RiskDistribution,
    RiskLevel,
    RiskSummary,
    TrendDirection,
    TrendPoint,
)

from .config import HydroConfig, load_config
from .contract import (
    FORECAST_CONTRACT_VERSION,
    INTEGRATION_STATEMENT,
    ForecastOutput,
    OptimizationHandoff,
)
from .evaluation import EvaluationReport
from .provenance import PENDING_THRESHOLD_DISCLAIMER, ProvenanceRecord, utc_now_iso
from .risk import RiskAssessor, RiskError, residual_sigma
from .training import SplitMatrices, TrainResult, TrainingError, _model_version, train

#: Engine name reported on `/health` and used in artifact references.
ENGINE_NAME = "navya-hydro"

#: Default model identifier reported in the forecast payload. Configurable via
#: `HYDRO_MODEL_ID`; it identifies the *pipeline*, not a trained release (the
#: release identity lives in `model_version` plus the artifact checksum).
DEFAULT_MODEL_ID = "NAVYA-HYDRO-001"

#: Map the team's `RiskLevel` enum onto the configured band labels. The running
#: schema only accepts these four, so a configured label outside the set is
#: refused rather than coerced.
_TEAM_RISK_LEVELS = {
    "LOW": RiskLevel.LOW,
    "MEDIUM": RiskLevel.MEDIUM,
    "HIGH": RiskLevel.HIGH,
    "CRITICAL": RiskLevel.CRITICAL,
}


class EngineNotReadyError(RuntimeError):
    """Raised when a forecast cannot be served without inventing a value.

    The AI service maps an exception raised inside an engine to a
    `502 FORECAST_ENGINE_ERROR` (see `app/api/routes.py`), so this surfaces as a
    structured error rather than a fabricated forecast.
    """


@dataclass(frozen=True)
class BacktestPoint:
    """One out-of-sample prediction paired with its observation."""

    timestamp: str
    origin_timestamp: str
    predicted: float
    observed: float
    probability: float | None
    risk_level: str | None


@dataclass
class EngineState:
    """Trained pipeline plus the artefacts the serving methods need."""

    result: TrainResult
    assessor: RiskAssessor
    backtest: tuple[BacktestPoint, ...]
    residual_sigma: float


def _iso_z(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            return value.isoformat() + "Z"
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _forecast_id_for(timestamp: pd.Timestamp) -> str:
    """Build an id matching the team contract's `^FC-\\d{8}-\\d{1,6}$` pattern."""
    return f"FC-{timestamp.strftime('%Y%m%d')}-{int(timestamp.hour) * 60 + int(timestamp.minute):03d}"


def _residuals(points: Sequence[BacktestPoint]) -> list[float]:
    return [point.predicted - point.observed for point in points]


class HydroForecastEngine:
    """Navya's forecasting engine, conforming to `app.engines.base.ForecastEngine`.

    Construction is zero-argument by contract. An optional `config` and an
    optional in-memory `frame` exist for tests and for embedding the engine in a
    notebook; neither is required by the factory.
    """

    name = ENGINE_NAME

    def __init__(
        self,
        config: HydroConfig | None = None,
        frame: pd.DataFrame | None = None,
    ) -> None:
        self._config = config if config is not None else load_config()
        self._frame = frame
        self._state: EngineState | None = None
        self._model_id = self._config.model_id
        self._load_error: str | None = None

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    @property
    def config(self) -> HydroConfig:
        return self._config

    @property
    def model_id(self) -> str:
        return self._model_id

    def readiness(self) -> tuple[str, ...]:
        """Everything that blocks serving, as human-readable strings.

        Includes both the static configuration blockers and any training error,
        so an operator can diagnose the engine from a single call.
        """
        # An in-memory frame is a legitimate way to run the engine (notebook
        # embedding, tests), so the dataset-path blocker is replaced rather than
        # duplicated when one was supplied.
        blockers = [
            blocker
            for blocker in self._config.readiness()
            if not blocker.startswith("no dataset path configured")
        ]
        if not self._config.enabled:
            blockers.append("HYDRO_ENABLED=false — the engine is switched off")
        if self._config.dataset.path is None and self._frame is None:
            blockers.append(
                "no dataset available (HYDRO_DATASET_PATH unset and no in-memory frame supplied)"
            )
        if self._load_error:
            blockers.append(f"training failed: {self._load_error}")
        return tuple(blockers)

    def advisories(self) -> tuple[str, ...]:
        """Non-blocking notes about the current configuration."""
        return self._config.advisories()

    def is_ready(self) -> bool:
        """True when a forecast can be served without inventing any value."""
        if self.readiness():
            return False
        try:
            self._state_or_raise()
        except EngineNotReadyError:
            return False
        return True

    def readiness_report(self) -> str:
        """Multi-line readiness summary, safe to log or return on a debug route."""
        blockers = self.readiness()
        lines = [
            f"engine               : {self.name}",
            f"contract_version     : {FORECAST_CONTRACT_VERSION}",
            f"dataset_reference    : {self._config.dataset.reference or 'UNKNOWN'}",
            f"dataset_type         : {self._config.dataset.dataset_type}",
            f"target               : {self._config.target.describe()}",
            f"forecast_horizon     : {self._config.target.horizon_hours}h",
            f"risk policy          : {self._config.risk.describe()}",
            f"serving              : {'READY' if self.is_ready() else 'NOT READY'}",
        ]
        if blockers:
            lines.append("blockers (prevent serving a forecast):")
            lines.extend(f"  - {blocker}" for blocker in blockers)
        else:
            lines.append("blockers: none")
        notes = self.advisories()
        if notes:
            lines.append("advisories (do not block serving, but label the output):")
            lines.extend(f"  - {note}" for note in notes)
        lines.append(INTEGRATION_STATEMENT)
        return "\n".join(lines)

    def contract(self) -> ForecastOutput | None:
        """The current forecast as a Navya contract payload, or `None` if not ready.

        This is the entry point a team owner would call to obtain the
        forecast → optimization payload without touching any existing service.
        """
        try:
            return self._forecast_output()
        except EngineNotReadyError:
            return None

    def handoff(self) -> OptimizationHandoff | None:
        """The forecast → optimization handoff payload, or `None` if not ready."""
        output = self.contract()
        if output is None:
            return None
        return OptimizationHandoff(forecast=output)

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    def _state_or_raise(self) -> EngineState:
        if self._state is not None:
            return self._state
        if self._load_error is not None:
            raise EngineNotReadyError(self._load_error)
        try:
            result = train(self._config, frame=self._frame)
        except (TrainingError, ValueError) as exc:
            self._load_error = str(exc)
            raise EngineNotReadyError(f"forecasting pipeline could not start: {exc}") from exc
        self._state = self._build_state(result)
        return self._state

    def _build_state(self, result: TrainResult) -> EngineState:
        selected = result.selected
        if selected is None:
            raise EngineNotReadyError(
                "no candidate model was selected by the chronological comparison"
            )
        report = selected.test_report or selected.validation_report
        if report is None:
            raise EngineNotReadyError("the selected model has no evaluation report")

        # The assessor is constructed before the backtest so the backtest points
        # can be scored without reaching back into `self._state` (which does not
        # exist yet during the lazy load).
        assessor = RiskAssessor(self._config.risk)
        backtest = self._build_backtest(result, assessor)
        if len(backtest) < 2:
            raise EngineNotReadyError(
                f"the out-of-sample backtest has only {len(backtest)} point(s); at least 2 are "
                "required to measure a residual spread for the exceedance probability"
            )
        try:
            sigma = _residual_sigma(backtest)
        except RiskError as exc:
            raise EngineNotReadyError(str(exc)) from exc
        return EngineState(
            result=result,
            assessor=assessor,
            backtest=backtest,
            residual_sigma=sigma,
        )

    def _split_for(self, result: TrainResult) -> SplitMatrices:
        if "test" in result.supervised:
            return result.supervised["test"]
        if "validation" in result.supervised:
            return result.supervised["validation"]
        return result.supervised["train"]

    def _build_backtest(
        self, result: TrainResult, assessor: RiskAssessor
    ) -> tuple[BacktestPoint, ...]:
        """Recompute the held-out predictions and pair them with observations.

        The backtest is the actual out-of-sample prediction of the selected model
        on the chronologically latest split — not a fit to the full series. That
        is what makes the measured residual spread honest.
        """
        selected = result.selected
        if selected is None:
            return ()
        part = self._split_for(result)
        names = selected.feature_names
        imputed = selected.imputer.transform(part.features, names)
        matrix = imputed.to_numpy(dtype="float64", na_value=np.nan)
        if selected.scaler.is_fitted:
            matrix = selected.scaler.transform_matrix(matrix, names)
        predictions = np.asarray(selected.estimator.predict(matrix), dtype="float64")
        observed = np.asarray(part.target, dtype="float64")

        # First pass: collect the raw held-out predictions. The residual spread
        # is not known until every residual has been observed, so the
        # probabilities are computed in a second pass from the MEASURED spread.
        # A probability is never emitted from an assumed sigma.
        raw = [
            (float(predictions[i]), float(observed[i]))
            for i in range(len(part.target))
        ]
        try:
            sigma = residual_sigma([predicted - actual for predicted, actual in raw])
        except RiskError:
            sigma = None

        points: list[BacktestPoint] = []
        for index, (predicted, actual) in enumerate(raw):
            assessment = assessor.assess(predicted, residual_sigma=sigma)
            points.append(
                BacktestPoint(
                    timestamp=_iso_z(part.target_timestamps.iloc[index]),
                    origin_timestamp=_iso_z(part.timestamps.iloc[index]),
                    predicted=predicted,
                    observed=actual,
                    probability=assessment.flood_probability,
                    risk_level=assessment.risk_level,
                )
            )
        return tuple(points)

    # ------------------------------------------------------------------ #
    # ForecastEngine protocol
    # ------------------------------------------------------------------ #

    def _require_servable(self, horizon_hours: int) -> EngineState:
        state = self._state_or_raise()
        if not self._config.enabled:
            raise EngineNotReadyError("HYDRO_ENABLED=false; the engine is switched off")
        if self._config.target.column != "water_level":
            raise EngineNotReadyError(
                f"the configured target is {self._config.target.column!r}, but the running "
                "ForecastPrediction contract only has a predicted_water_level field and no "
                "inflow field. Serving an inflow forecast through predicted_water_level would be a "
                "mislabel. Required team-owner change: add predicted_inflow (and target_units) to "
                "app/schemas/models.py, backend/src/types/contract.ts and the forecasts table."
            )
        configured = self._config.target.horizon_hours
        if horizon_hours != configured:
            raise EngineNotReadyError(
                f"requested horizon {horizon_hours}h does not match the model's trained horizon "
                f"{configured}h. The lead time is baked into the supervised alignment, so a "
                f"different horizon requires a retrained model. Set HYDRO_FORECAST_HORIZON_HOURS="
                f"{horizon_hours} and retrain, or request {configured}h."
            )
        if not self._config.risk.is_usable:
            missing = state.assessor.missing_configuration()
            raise EngineNotReadyError(
                "refusing to emit a forecast: the contract requires flood_probability and "
                "risk_level, and this pipeline will not invent them. " + "; ".join(missing)
            )
        return state

    def _require_no_blockers(self) -> None:
        """Refuse to serve while any blocking readiness condition stands.

        Every serving method calls this, so `is_ready()` and the serving methods
        cannot disagree. A method that ignored a blocker would return data while
        the readiness report said the engine was not ready, and an operator
        reading only one of the two would be misled.

        `latest_forecast` additionally applies the target/horizon checks in
        `_require_servable`; this is the shared floor underneath all of them.
        """
        blockers = self.readiness()
        if blockers:
            raise EngineNotReadyError(
                "refusing to serve: " + "; ".join(blockers)
            )

    def latest_forecast(self, horizon_hours: int = 24) -> ForecastPrediction:
        """Forecast the configured horizon ahead of the most recent observation."""
        state = self._state_or_raise()
        state = self._require_servable(horizon_hours)
        result = state.result
        config = self._config

        features = self._tail_features(result)
        names = result.selected.feature_names  # type: ignore[union-attr]
        imputed = result.selected.imputer.transform(features, names)  # type: ignore[union-attr]
        matrix = imputed.to_numpy(dtype="float64", na_value=np.nan)
        if result.selected.scaler.is_fitted:  # type: ignore[union-attr]
            matrix = result.selected.scaler.transform_matrix(matrix, names)
        predicted = float(np.asarray(result.selected.estimator.predict(matrix), dtype="float64").reshape(-1)[0])  # type: ignore[union-attr]

        assessment = state.assessor.assess(predicted, residual_sigma=state.residual_sigma)
        if assessment.flood_probability is None or assessment.risk_level is None:
            raise EngineNotReadyError(
                "the risk assessment produced no probability or band; refusing to fabricate one. "
                + (assessment.notes or "")
            )
        risk_level = _TEAM_RISK_LEVELS.get(assessment.risk_level)
        if risk_level is None:
            raise EngineNotReadyError(
                f"configured risk band label {assessment.risk_level!r} is not one of the contract's "
                "LOW/MEDIUM/HIGH/CRITICAL values; refusing to coerce it"
            )

        ts_col = config.dataset.timestamp_column
        last_observed = pd.Timestamp(result.preprocessing.frame[ts_col].iloc[-1])
        target_timestamp = last_observed + pd.Timedelta(
            hours=config.target.horizon_hours
        )
        status = "completed" if assessment.policy_approved else "pending"
        return ForecastPrediction(
            forecast_id=_forecast_id_for(target_timestamp),
            flood_probability=float(assessment.flood_probability),
            risk_level=risk_level,
            predicted_water_level=predicted,
            forecast_horizon=f"{config.target.horizon_hours}h",
            model_id=self._model_id,
            model_version=_model_version(config, result.selected_key or "unknown"),
            prediction_timestamp=utc_now_iso(),
            status=status,  # type: ignore[arg-type]
        )

    def _tail_features(self, result: TrainResult) -> pd.DataFrame:
        """Feature row for the most recent observation, reduced to the plan.

        `build_features` returns the original observation columns *plus* the
        generated features. The imputer and scaler were fitted on the planned
        feature columns only, so the tail row is reduced to exactly
        `result.plan.names` before prediction. Passing the wider frame would send
        a column-count mismatch into the scaler.

        The engine forecasts from the tail of the loaded dataset. It is not
        connected to live telemetry: integrating a gauge feed requires the station
        source, which this repository does not contain.
        """
        from .features import build_features

        features, _plan = build_features(result.preprocessing.frame, self._config)
        tail = features.tail(1)
        return tail.loc[:, list(result.plan.names)]

    def forecast_series(self, hours: int = 24) -> list[ForecastPoint]:
        """Out-of-sample backtest points, oldest first, capped at `hours`.

        Each point pairs a real held-out prediction with its observation, so the
        series a dashboard charts is a genuine backtest rather than a fit to the
        full series or a synthetic curve.

        `hours` is a cap, not a demand: asking for more points than the held-out
        period contains returns the points that exist rather than failing, and
        `hours <= 0` returns none. The caller can always see how many it got.

        Every emitted point carries a measured `flood_probability`. If any point
        lacks one, the whole series is refused: the team contract makes the field
        non-nullable, so the only way to "fill" it would be to invent a number,
        and `0.0` in particular is a claim that flooding will not occur.
        """
        self._require_no_blockers()
        state = self._state_or_raise()
        points = state.backtest[-hours:] if hours > 0 else ()
        unavailable = [p.timestamp for p in points if p.probability is None]
        if unavailable:
            raise EngineNotReadyError(
                f"{len(unavailable)} of {len(points)} backtest point(s) have no measured "
                f"exceedance probability (first: {unavailable[0]}); ForecastPoint.flood_probability "
                "is non-nullable in the team contract and this engine will not substitute a "
                "number for one it does not have"
            )
        out: list[ForecastPoint] = []
        for point in points:
            out.append(
                ForecastPoint(
                    timestamp=point.timestamp,
                    predicted_water_level=float(max(0.0, point.predicted)),
                    observed_water_level=float(max(0.0, point.observed)),
                    flood_probability=float(point.probability),
                )
            )
        return out

    def risk_analytics(self) -> RiskAnalytics:
        """Risk trend, probability trend, distribution and overall trend.

        The flood stage is reported only when a threshold is configured, and is
        accompanied by the policy status so a consumer can tell an approved
        threshold from a configured-but-unapproved one.
        """
        self._require_no_blockers()
        state = self._state_or_raise()
        points = state.backtest
        probabilities: list[float] = [
            float(point.probability) for point in points if point.probability is not None
        ]
        if not probabilities:
            raise EngineNotReadyError(
                "no exceedance probability could be computed for any backtest point; "
                "the risk analytics endpoints refuse to report invented trends"
            )

        probability_trend = [
            TrendPoint(timestamp=point.timestamp, value=float(point.probability))
            for point in points
            if point.probability is not None
        ]
        # The risk trend is the same exceedance probability expressed on the
        # contract's trend shape; the two series are intentionally identical
        # rather than two differently-defined numbers.
        risk_trend = [
            TrendPoint(timestamp=point.timestamp, value=float(point.probability))
            for point in points
            if point.probability is not None
        ]

        counts = {label.value: 0 for label in RiskLevel}
        for point in points:
            level = _TEAM_RISK_LEVELS.get(point.risk_level or "")
            if level is not None:
                counts[level.value] += 1
        distribution = [
            RiskDistribution(risk_level=level, count=counts[level.value]) for level in RiskLevel
        ]
        summary = RiskSummary(
            high=counts["HIGH"],
            medium=counts["MEDIUM"],
            low=counts["LOW"],
            critical=counts["CRITICAL"],
        )
        overall = _overall_trend([point.value for point in risk_trend])

        threshold = self._config.risk.flood_threshold
        label = None
        if threshold is not None:
            label = self._config.risk.threshold_source or "configured flood stage"
            if self._config.risk.policy_status != "approved":
                label = f"{label} (policy PENDING — not official)"
        return RiskAnalytics(
            risk_trend=risk_trend,
            probability_trend=probability_trend,
            distribution=distribution,
            summary=summary,
            overall_trend=overall,
            threshold_level=threshold,
            threshold_label=label,
        )

    def models(self) -> list[ModelInfo]:
        """The single model this engine serves, with its measured metrics.

        `ModelMetrics` is filled only with values an executed evaluation actually
        produced. R² has no slot in the team schema, so it is omitted rather than
        smuggled into another field; it stays in the evaluation report and the
        artifact.
        """
        self._require_no_blockers()
        state = self._state_or_raise()
        result = state.result
        key = result.selected_key or "unknown"
        report = result.selected.best_report if result.selected else None
        selected = result.selected
        status = (
            ModelStatus.READY
            if report is not None and self._config.risk.policy_status == "approved"
            else ModelStatus.DEGRADED
        )
        metrics = ModelMetrics()
        if report is not None:
            metrics = ModelMetrics(
                rmse=report.metrics.rmse,
                mae=report.metrics.mae,
                nse=report.metrics.nse,
                accuracy=None,
            )
        info = ModelInfo(
            model_id=self._model_id,
            name=selected.estimator.display_name if selected else "unknown",
            version=_model_version(self._config, key),
            algorithm=selected.estimator.algorithm if selected else "unknown",
            status=status,
            last_trained_at=result.provenance.created_at if result.provenance else utc_now_iso(),
            last_evaluated_at=report.evaluated_at if report is not None else "",
            metrics=metrics,
        )
        return [info]

    def model_metrics(self, model_id: str) -> ModelInfo | None:
        """Return the model info when `model_id` matches this engine's model."""
        for info in self.models():
            if info.model_id == model_id:
                return info
        return None

    def recent_predictions(self, limit: int = 6) -> list[PredictionRecord]:
        """The most recent out-of-sample prediction records, newest last.

        Refuses, rather than returning a short list, when a backtest point cannot
        fill the record: `PredictionRecord` requires a `risk_level` and a
        `probability`, and quietly dropping the points that cannot supply them
        would leave a caller asking for six records holding an empty list with no
        way to tell that the data was withheld rather than absent.
        """
        self._require_no_blockers()
        state = self._state_or_raise()
        selected = state.backtest[-limit:] if limit > 0 else []
        unusable = [
            p.timestamp
            for p in selected
            if p.probability is None or _TEAM_RISK_LEVELS.get(p.risk_level or "") is None
        ]
        if unusable:
            raise EngineNotReadyError(
                f"{len(unusable)} of {len(selected)} backtest point(s) cannot fill a "
                f"PredictionRecord (first: {unusable[0]}); the record requires both a "
                "probability and a risk level, and this engine will not omit them silently"
            )
        records: list[PredictionRecord] = []
        for point in selected:
            level = _TEAM_RISK_LEVELS.get(point.risk_level or "")
            if level is None:  # pragma: no cover - guarded above
                continue
            records.append(
                PredictionRecord(
                    forecast_id=_forecast_id_for(pd.Timestamp(point.timestamp)),
                    timestamp=point.timestamp,
                    probability=float(point.probability),  # type: ignore[arg-type]
                    risk_level=level,
                    water_level=float(max(0.0, point.predicted)),
                    model_id=self._model_id,
                    status="completed",
                )
            )
        return records

    # ------------------------------------------------------------------ #
    # Navya contract projection
    # ------------------------------------------------------------------ #

    def _forecast_output(self) -> ForecastOutput:
        """Project the served forecast onto Navya's structured contract."""
        prediction = self.latest_forecast(self._config.target.horizon_hours)
        state = self._state_or_raise()
        result = state.result
        ts_col = self._config.dataset.timestamp_column
        last_observed = pd.Timestamp(result.preprocessing.frame[ts_col].iloc[-1])
        target_timestamp = last_observed + pd.Timedelta(
            hours=self._config.target.horizon_hours
        )
        assessment = state.assessor.assess(
            prediction.predicted_water_level, residual_sigma=state.residual_sigma
        )
        provenance: ProvenanceRecord | None = result.provenance
        report = result.selected.best_report if result.selected else None
        return ForecastOutput(
            forecast_id=prediction.forecast_id,
            forecast_timestamp=prediction.prediction_timestamp,
            forecast_horizon=prediction.forecast_horizon,
            model_id=prediction.model_id,
            model_version=prediction.model_version,
            status=prediction.status,
            station_reference=self._config.dataset.station_reference,
            target=self._config.target.column,
            target_units=self._config.target.units,
            predicted_value=prediction.predicted_water_level,
            predicted_water_level=prediction.predicted_water_level,
            predicted_inflow=None,
            flood_probability=prediction.flood_probability,
            risk_level=prediction.risk_level.value,
            risk_score=assessment.risk_score,
            threshold=assessment.threshold,
            threshold_policy=assessment.threshold_policy,
            residual_sigma=state.residual_sigma,
            lead_time_rows=result.lead_time_rows,
            provenance_reference=provenance.dataset_reference if provenance else None,
            contract_version=FORECAST_CONTRACT_VERSION,
            disclaimer=provenance.disclaimer if provenance else PENDING_THRESHOLD_DISCLAIMER,
            evaluation_metrics=report.metrics.as_dict() if report is not None else None,
        )


def _residual_sigma(points: Sequence[BacktestPoint]) -> float:
    """Standard deviation (ddof=1) of the measured backtest residuals."""
    return residual_sigma(_residuals(points))


def _overall_trend(values: Sequence[float]) -> TrendDirection:
    """Classify the direction of a series using the team's 0.06 tolerance."""
    if not values:
        return TrendDirection.FLAT
    first, last = values[0], values[-1]
    if last > first + 0.06:
        return TrendDirection.UP
    if last < first - 0.06:
        return TrendDirection.DOWN
    return TrendDirection.FLAT
