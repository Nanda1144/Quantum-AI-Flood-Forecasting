# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""forecasting-module-owned forecast output and the forecast → optimization contract.

This module is a **specification plus a serialiser**, deliberately kept outside
every team-owned file. It defines:

1. `ForecastOutput` — the structured internal forecast record. Fields that are
   not actually available are `None`; nothing is defaulted into existence.
2. `OptimizationHandoff` — the forecast-derived payload a downstream consumer
   would receive, with a strictly backward-compatible projection onto the
   `forecast_id`-only payload the running optimizer accepts today.
3. `CandidateRiskAttribution` — the station/reach → candidate-location risk
   mapping specification. It is a *specification* because no verified
   station-to-candidate mapping exists in this repository; the only concrete
   implementation shipped here is a clearly labelled synthetic demo.

The contract statement that must accompany every use of this module
--------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: Version tag written into every forecast payload produced by this pipeline.
FORECAST_CONTRACT_VERSION = "hydro-forecast/v1"

#: The required integration statement. It is a module constant so the wording
#: cannot drift between the code, the documentation and the API description.
INTEGRATION_STATEMENT = (
    "Existing optimization currently requires forecast_id. "
    "Additional forecast-derived risk fields require team-owner integration."
)

#: Fields of the running `POST /api/optimization/from-forecast` request body
#: (see `backend/src/services/optimization.service.ts`, owned by Nanda). This is
#: the exact, backward-compatible subset the forecast side may rely on today.
EXISTING_HANDOFF_FIELDS = (
    "forecast_id",
    "risk_score",
    "priority",
    "candidate_locations_available",
    "resource_constraints_available",
)

#: Fields the optimizer requires to accept forecast-derived risk. None of these
#: exist in the running contract; each needs an owner-approved change.
FIELDS_REQUIRING_TEAM_OWNER_INTEGRATION = (
    "station_reference",
    "predicted_water_level",
    "predicted_inflow",
    "flood_probability",
    "risk_level",
    "forecast_horizon",
    "forecast_timestamp",
    "provenance_reference",
)

#: Risk levels the running backend accepts, mirroring
#: `backend/src/types/contract.ts` → `RiskLevel`.
SUPPORTED_RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Priorities the running backend accepts, mirroring
#: `optimization.service.ts` → `OptimizationReference['priority']`.
SUPPORTED_PRIORITIES = ("low", "medium", "high", "critical")


class ContractError(ValueError):
    """Raised when a forecast or handoff payload would be dishonest or invalid."""


@dataclass(frozen=True)
class ForecastOutput:
    """the structured forecast record.

    Every optional field is `None` when it was not actually produced. In
    particular `predicted_inflow` stays `None` unless an inflow target was
    configured, and `flood_probability`/`risk_level` stay `None` unless a
    threshold policy and a measured residual spread were available.
    """

    forecast_id: str
    forecast_timestamp: str
    forecast_horizon: str
    model_id: str
    model_version: str
    status: str = "completed"
    station_reference: str | None = None
    reach_reference: str | None = None
    target: str | None = None
    target_units: str | None = None
    predicted_value: float | None = None
    predicted_water_level: float | None = None
    predicted_inflow: float | None = None
    flood_probability: float | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    threshold: float | None = None
    threshold_policy: str = "pending"
    residual_sigma: float | None = None
    lead_time_rows: int | None = None
    provenance_reference: str | None = None
    contract_version: str = FORECAST_CONTRACT_VERSION
    disclaimer: str | None = None
    evaluation_metrics: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if not self.forecast_id.strip():
            raise ContractError("forecast_id must not be blank")
        if self.flood_probability is not None and not 0.0 <= self.flood_probability <= 1.0:
            raise ContractError(
                f"flood_probability must be in [0, 1], got {self.flood_probability!r}"
            )
        if self.risk_level is not None and self.risk_level not in SUPPORTED_RISK_LEVELS:
            raise ContractError(
                f"risk_level {self.risk_level!r} is not one of {SUPPORTED_RISK_LEVELS}"
            )
        if self.status not in ("completed", "pending", "failed"):
            raise ContractError(f"unsupported forecast status {self.status!r}")

    @property
    def location_reference(self) -> str | None:
        """Station reference, falling back to the reach reference.

        A single `location/station reference` field is what the downstream
        contract asks for; the platform has no agreed choice between the two, so
        both are carried and the station wins when both are known.
        """
        return self.station_reference or self.reach_reference

    def available_fields(self) -> tuple[str, ...]:
        """Names of the contract fields that actually carry a value."""
        candidates = (
            "station_reference",
            "reach_reference",
            "target",
            "target_units",
            "predicted_value",
            "predicted_water_level",
            "predicted_inflow",
            "flood_probability",
            "risk_level",
            "risk_score",
            "threshold",
            "residual_sigma",
            "lead_time_rows",
            "provenance_reference",
        )
        return tuple(name for name in candidates if getattr(self, name) is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "forecast_timestamp": self.forecast_timestamp,
            "forecast_horizon": self.forecast_horizon,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "status": self.status,
            "location_reference": self.location_reference,
            "station_reference": self.station_reference,
            "reach_reference": self.reach_reference,
            "target": self.target,
            "target_units": self.target_units,
            "predicted_value": self.predicted_value,
            "predicted_water_level": self.predicted_water_level,
            "predicted_inflow": self.predicted_inflow,
            "flood_probability": self.flood_probability,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "threshold": self.threshold,
            "threshold_policy": self.threshold_policy,
            "residual_sigma": self.residual_sigma,
            "lead_time_rows": self.lead_time_rows,
            "provenance_reference": self.provenance_reference,
            "contract_version": self.contract_version,
            "disclaimer": self.disclaimer,
            "evaluation_metrics": dict(self.evaluation_metrics)
            if self.evaluation_metrics is not None
            else None,
            "integration_statement": INTEGRATION_STATEMENT,
        }


def priority_for_risk_level(risk_level: str | None) -> str:
    """Map a risk level onto the running backend's priority vocabulary.

    Mirrors the mapping the existing `ForecastSyncService` already applies, so a
    handoff built here is consistent with what the platform already stores. With
    no risk level, `low` is used and the caller is expected to rely on the
    explicit `risk_score` instead of an implied severity.
    """
    return {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
    }.get(risk_level or "", "low")


@dataclass(frozen=True)
class OptimizationHandoff:
    """Forecast-derived payload for the downstream sensor-placement optimizer.

    This is the **proposed** full contract. The running optimizer accepts only
    `forecast_id` plus four optional scalars, so `to_existing_payload()` produces
    the exactly-compatible subset and `to_proposed_payload()` produces the whole
    record for a future, version-aware consumer.
    """

    forecast: ForecastOutput
    candidate_locations_available: bool | None = False
    resource_constraints_available: bool | None = False

    @property
    def forecast_id(self) -> str:
        return self.forecast.forecast_id

    def to_existing_payload(self) -> dict[str, Any]:
        """Payload accepted by the running `POST /api/optimization/from-forecast`.

        Only fields that already exist on the team contract are emitted. A field
        with no value is omitted rather than sent as `null`, because the running
        zod schema distinguishes "absent" from "provided".

        **The two availability flags are sent explicitly as `false`, and that is
        deliberate.** The running `OptimizationService.createFromForecast` reads
        them as `payload.candidate_locations_available ?? true`, so *omitting* them
        makes the platform record that candidate locations and resource
        constraints are available. They are not: this repository contains no
        authoritative candidate-location set and no resource-constraint source, so
        asserting availability would fabricate a capability. Sending `false`
        records the honest answer and makes the downstream job report itself as
        not-ready instead of failing later for an unrelated-looking reason.

        The two are still `None`-able so a caller that has genuinely sourced this
        data can say so.
        """
        payload: dict[str, Any] = {"forecast_id": self.forecast.forecast_id}
        if self.forecast.risk_score is not None:
            payload["risk_score"] = float(self.forecast.risk_score)
        if self.forecast.risk_level is not None:
            payload["priority"] = priority_for_risk_level(self.forecast.risk_level)
        if self.candidate_locations_available is not None:
            payload["candidate_locations_available"] = bool(self.candidate_locations_available)
        if self.resource_constraints_available is not None:
            payload["resource_constraints_available"] = bool(self.resource_constraints_available)
        return payload

    def to_proposed_payload(self) -> dict[str, Any]:
        """Full forecast contract, including the fields that need team integration."""
        payload = {
            "contract_version": self.forecast.contract_version,
            "forecast_id": self.forecast.forecast_id,
            "forecast_timestamp": self.forecast.forecast_timestamp,
            "forecast_horizon": self.forecast.forecast_horizon,
            "location_reference": self.forecast.location_reference,
            "station_reference": self.forecast.station_reference,
            "reach_reference": self.forecast.reach_reference,
            "target": self.forecast.target,
            "target_units": self.forecast.target_units,
            "predicted_value": self.forecast.predicted_value,
            "predicted_water_level": self.forecast.predicted_water_level,
            "predicted_inflow": self.forecast.predicted_inflow,
            "flood_probability": self.forecast.flood_probability,
            "risk_level": self.forecast.risk_level,
            "risk_score": self.forecast.risk_score,
            "threshold": self.forecast.threshold,
            "threshold_policy": self.forecast.threshold_policy,
            "provenance_reference": self.forecast.provenance_reference,
            "status": self.forecast.status,
            "integration_statement": INTEGRATION_STATEMENT,
        }
        if self.candidate_locations_available is not None:
            payload["candidate_locations_available"] = bool(self.candidate_locations_available)
        if self.resource_constraints_available is not None:
            payload["resource_constraints_available"] = bool(self.resource_constraints_available)
        return payload

    def fields_requiring_integration(self) -> tuple[str, ...]:
        """Which proposed fields the running optimizer cannot receive today."""
        available = set(self.to_existing_payload())
        return tuple(
            name
            for name in FIELDS_REQUIRING_TEAM_OWNER_INTEGRATION
            if name not in available and getattr(self.forecast, name, None) is not None
        )

    def describe(self) -> str:
        lines = [
            "FORECAST -> OPTIMIZATION HANDOFF",
            f"  contract_version : {self.forecast.contract_version}",
            f"  {INTEGRATION_STATEMENT}",
            "  payload accepted by the running optimizer today:",
        ]
        for key, value in sorted(self.to_existing_payload().items()):
            lines.append(f"    {key} = {value!r}")
        pending = self.fields_requiring_integration()
        lines.append("  proposed fields pending team-owner integration:")
        if pending:
            lines.extend(f"    {name}" for name in pending)
        else:
            lines.append("    (none — this forecast only carries fields the running contract accepts)")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Candidate-specific risk attribution
# --------------------------------------------------------------------------- #

#: Disclaimer attached to every synthetic candidate mapping.
SYNTHETIC_MAPPING_DISCLAIMER = (
    "SYNTHETIC CANDIDATE MAPPING — station/reach identifiers and risk values are "
    "generated for demonstration. NOT a verified GIS mapping and NOT real site data."
)

#: Disclaimers for the two unverified inputs of the attribution step.
UNVERIFIED_INPUT_NOTICES = (
    "No verified station-to-candidate mapping exists in this repository; "
    "a real deployment requires an authoritative GIS join supplied by the GIS owner.",
    "CandidateLocation.floodRisk is currently produced by a deterministic stand-in "
    "generator, not by any hydrological model.",
)


@dataclass(frozen=True)
class CandidateRiskAttribution:
    """Forecast-derived risk attributed to one optimization candidate location.

    This is the specification of the step that closes the current gap:

        forecast / station / reach
            -> candidate location
            -> forecast-derived risk
            -> optimization input

    The optimizer's objective reads `CandidateLocation.floodRisk` (see
    `backend/src/lib/optimization/qubo.ts`, owned by Nanda). Nothing in the
    running pipeline currently writes a forecast-derived value into that field,
    so this dataclass defines the value a team owner would need to persist, and
    the guarantees that must hold before it is written.
    """

    candidate_location_id: str
    forecast_id: str
    station_reference: str | None
    reach_reference: str | None
    forecast_risk_score: float | None
    derived_flood_risk: float | None
    mapping_provenance: str
    is_synthetic: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_location_id.strip():
            raise ContractError("candidate_location_id must not be blank")
        if self.derived_flood_risk is not None and not 0.0 <= self.derived_flood_risk <= 1.0:
            # The optimizer expects floodRisk in [0, 1]; anything else would
            # silently distort the QUBO linear term.
            raise ContractError(
                f"derived_flood_risk must be in [0, 1] to be usable as CandidateLocation.floodRisk, "
                f"got {self.derived_flood_risk!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_location_id": self.candidate_location_id,
            "forecast_id": self.forecast_id,
            "station_reference": self.station_reference,
            "reach_reference": self.reach_reference,
            "forecast_risk_score": self.forecast_risk_score,
            "derived_flood_risk": self.derived_flood_risk,
            "mapping_provenance": self.mapping_provenance,
            "is_synthetic": self.is_synthetic,
            "notes": self.notes,
            "disclaimer": SYNTHETIC_MAPPING_DISCLAIMER if self.is_synthetic else None,
        }


@dataclass(frozen=True)
class CandidateRiskMappingSpec:
    """The mapping specification plus whatever concrete rows were built.

    `attributions` is empty in a real deployment until an authoritative GIS join
    exists. `synthetic` is `True` for every row this repository can produce, and
    `to_dict()` carries the disclaimer so a downstream consumer cannot mistake a
    demo mapping for a verified one.
    """

    forecast_id: str
    attributions: tuple[CandidateRiskAttribution, ...] = ()
    synthetic: bool = True
    source: str = "none"

    def validate(self) -> None:
        """Reject a mapping that mixes synthetic and verified rows silently."""
        if not self.attributions:
            return
        synthetic_flags = {row.is_synthetic for row in self.attributions}
        if len(synthetic_flags) > 1:
            raise ContractError(
                "a mapping must not mix synthetic and verified attributions; split them so the "
                "disclaimer stays accurate for every row"
            )
        ids = [row.candidate_location_id for row in self.attributions]
        if len(set(ids)) != len(ids):
            duplicates = sorted({item for item in ids if ids.count(item) > 1})
            raise ContractError(f"duplicate candidate_location_id in mapping: {duplicates}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "forecast_id": self.forecast_id,
            "synthetic": self.synthetic,
            "source": self.source,
            "attributions": [row.to_dict() for row in self.attributions],
            "unverified_inputs": list(UNVERIFIED_INPUT_NOTICES),
            "integration_statement": (
                "Writing derived_flood_risk into CandidateLocation.floodRisk requires a "
                "team-owner change in the GIS candidate store and the optimization request path. "
                "Until then the objective uses the stand-in generator's value."
            ),
        }


def normalize_candidate_risk(value: float | None) -> float | None:
    """Clamp a risk score into the `[0, 1]` band the optimizer expects.

    Returns `None` unchanged so a missing risk is never converted into a zero
    risk, which would make an unassessed site look safe.
    """
    if value is None:
        return None
    numeric = float(value)
    if numeric != numeric:
        raise ContractError("candidate risk must be a number, got NaN")
    return min(1.0, max(0.0, numeric))
