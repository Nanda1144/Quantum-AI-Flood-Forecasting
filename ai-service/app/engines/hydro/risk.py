# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Configurable flood-risk assessment.

The single most important rule in this module: **there is no default flood
threshold.** The `8.0` value in `app.engines.reference` is a demo placeholder
owned by Nanda and is deliberately NOT reused here. Until an authority supplies a
flood stage, its datum and its risk-band policy, `RiskPolicy.flood_threshold` is
`None` and this module returns an *unavailable* assessment rather than a number
nobody can defend.

What is legitimately calculable
-------------------------------
A exceedance probability is a real quantity once two measured inputs exist:

    P(target > threshold) = 1 - Phi((threshold - predicted) / sigma)

* `predicted` — the point forecast from the model.
* `threshold` — the configured flood stage, in the target's units.
* `sigma`    — the **measured** residual standard deviation, computed from real
  validation or test residuals. Without a measured `sigma` there is no
  distribution to integrate over, so the probability is `None`. It is never
  substituted with a hand-picked constant.

The normal form is a stated modelling assumption, not a hydrological law, and is
recorded on every result as `method` so a reviewer sees exactly what was assumed.
A team that prefers an empirical exceedance frequency or a calibrated classifier
can replace the estimator without touching the rest of the pipeline.

Risk bands
----------
Band edges and labels are configuration. With no approved policy, `risk_level` is
`None` — never a value borrowed from the reference engine, and never presented as
official policy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .config import RiskPolicy
from .provenance import PENDING_THRESHOLD_DISCLAIMER

#: Label used in reports for a risk level that could not be assigned.
UNAVAILABLE = "unavailable"

#: Method tag recorded on every exceedance probability produced here.
NORMAL_APPROXIMATION = "normal_approximation_measured_sigma"


class RiskError(ValueError):
    """Raised when a risk calculation is requested that cannot be done honestly."""


@dataclass(frozen=True)
class RiskAssessment:
    """Outcome of a risk assessment, with every optional field honestly empty.

    `flood_probability` and `risk_level` are `None` whenever the policy or the
    measured residual spread required to compute them is unavailable.
    """

    flood_probability: float | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    threshold: float | None = None
    threshold_source: str | None = None
    threshold_policy: str = "pending"
    method: str | None = None
    residual_sigma: float | None = None
    policy_approved: bool = False
    notes: str = ""

    @property
    def is_available(self) -> bool:
        """True only when a probability AND a band were actually assigned."""
        return self.flood_probability is not None and self.risk_level is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "flood_probability": self.flood_probability,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "threshold": self.threshold,
            "threshold_source": self.threshold_source,
            "threshold_policy": self.threshold_policy,
            "method": self.method,
            "residual_sigma": self.residual_sigma,
            "policy_approved": self.policy_approved,
            "notes": self.notes,
        }


def normal_cdf(x: float) -> float:
    """Standard normal CDF via `math.erf` (no SciPy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def exceedance_probability(
    predicted_value: float,
    threshold: float,
    residual_sigma: float,
) -> float:
    """P(observation > threshold) under a normal residual assumption.

    `residual_sigma` must be a measured standard deviation of real residuals. A
    non-positive or non-finite sigma is rejected: with no spread there is no
    distribution, and returning a confident 0 or 1 would be a fabrication.
    """
    if not math.isfinite(predicted_value):
        raise RiskError("predicted value must be finite")
    if not math.isfinite(threshold):
        raise RiskError("flood threshold must be finite")
    if not math.isfinite(residual_sigma) or residual_sigma <= 0:
        raise RiskError(
            f"residual_sigma must be a positive finite measurement, got {residual_sigma!r}"
        )
    z = (threshold - predicted_value) / residual_sigma
    return min(1.0, max(0.0, 1.0 - normal_cdf(z)))


def residual_sigma(residuals: Sequence[float]) -> float:
    """Measured residual standard deviation (ddof=1) from real predictions."""
    values = [float(value) for value in residuals]
    if len(values) < 2:
        raise RiskError(
            f"at least 2 residuals are required to measure a residual spread, got {len(values)}"
        )
    if not all(math.isfinite(value) for value in values):
        raise RiskError("residuals contain non-finite values")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0.0:
        raise RiskError(
            "residuals are all identical; the residual spread is zero and no exceedance "
            "probability can be computed"
        )
    return math.sqrt(variance)


def classify_risk_level(
    probability: float,
    band_edges: Sequence[float],
    band_labels: Sequence[str],
) -> str | None:
    """Map an exceedance probability onto a configured risk band.

    `band_edges` may be either `len(labels) - 1` interior boundaries, or
    `len(labels)` values where the last one is the closed upper edge. Returns
    `None` when the configuration cannot be interpreted — an unassigned band is
    always better than a wrong one.
    """
    if not 0.0 <= probability <= 1.0:
        raise RiskError(f"probability must be in [0, 1], got {probability}")
    if not band_edges or not band_labels:
        return None

    edges = [float(edge) for edge in band_edges]
    if any(edges[i] >= edges[i + 1] for i in range(len(edges) - 1)):
        raise RiskError(f"band edges must be strictly ascending, got {band_edges}")
    if edges[0] < 0.0 or edges[-1] > 1.0:
        raise RiskError(f"band edges must lie inside [0, 1], got {band_edges}")

    if len(edges) == len(band_labels):
        interior = edges[:-1]
        upper_closed = edges[-1]
    elif len(edges) == len(band_labels) - 1:
        interior = edges
        upper_closed = 1.0
    else:
        return None

    for index, edge in enumerate(interior):
        if probability <= edge:
            return band_labels[index]
    if probability <= upper_closed:
        return band_labels[-1]
    return band_labels[-1]


class RiskAssessor:
    """Applies a `RiskPolicy` to a point forecast.

    The assessor never invents a threshold. Constructed with a policy whose
    threshold is `None`, every `assess()` call returns an unavailable result
    carrying the pending-policy note.
    """

    def __init__(self, policy: RiskPolicy) -> None:
        self.policy = policy

    @property
    def is_configured(self) -> bool:
        return self.policy.is_usable

    def missing_configuration(self) -> list[str]:
        """Exactly what an operator still has to supply."""
        missing: list[str] = []
        if self.policy.flood_threshold is None:
            missing.append("HYDRO_FLOOD_THRESHOLD (official flood stage in the target's units)")
        if not self.policy.band_edges:
            missing.append("HYDRO_RISK_BANDS (ascending probability band edges, e.g. 0.1,0.3,0.6)")
        if self.policy.policy_status != "approved":
            missing.append("HYDRO_RISK_THRESHOLD_POLICY=approved (formal sign-off on the band policy)")
        return missing

    def assess(
        self,
        predicted_value: float,
        *,
        residual_sigma: float | None = None,
        risk_score: float | None = None,
        probability: float | None = None,
        extra_notes: Sequence[str] = (),
    ) -> RiskAssessment:
        """Assess one point forecast.

        Exactly one of `probability` or `residual_sigma` should be supplied:

        * `residual_sigma` (preferred) — measured from real residuals, and the
          normal exceedance model is applied.
        * `probability` — a probability computed by a different, already-justified
          method (e.g. an empirical exceedance frequency). Recorded as such.

        With neither, and without an approved threshold, the result is
        unavailable. `risk_score` is passed through untouched for the
        optimization handoff; it defaults to the exceedance probability when one
        exists.
        """
        notes: list[str] = list(extra_notes)

        if not self.is_configured:
            notes.append(PENDING_THRESHOLD_DISCLAIMER)
            missing = self.missing_configuration()
            if missing:
                notes.append("missing: " + "; ".join(missing))
            return RiskAssessment(
                threshold=self.policy.flood_threshold,
                threshold_source=self.policy.threshold_source,
                threshold_policy=self.policy.policy_status,
                policy_approved=self.policy.policy_status == "approved",
                notes=" ".join(notes),
            )

        threshold = float(self.policy.flood_threshold)  # is_usable guarantees non-None
        method: str | None = None
        value = probability

        if value is None:
            if residual_sigma is None:
                notes.append(
                    "no measured residual spread supplied, so no exceedance probability could be "
                    "computed; risk level left unassigned"
                )
                return RiskAssessment(
                    threshold=threshold,
                    threshold_source=self.policy.threshold_source,
                    threshold_policy=self.policy.policy_status,
                    policy_approved=self.policy.policy_status == "approved",
                    notes=" ".join(notes),
                )
            value = exceedance_probability(predicted_value, threshold, residual_sigma)
            method = NORMAL_APPROXIMATION
        else:
            method = "supplied_probability"
            if not 0.0 <= float(value) <= 1.0:
                raise RiskError(f"supplied probability must be in [0, 1], got {value!r}")

        level = classify_risk_level(float(value), self.policy.band_edges, self.policy.band_labels)
        if level is None:
            notes.append(
                "risk band edges do not match the configured label count; no band assigned"
            )

        approved = self.policy.policy_status == "approved"
        if not approved:
            notes.append(
                "band labels below are configured, NOT official policy — the threshold policy "
                "is still pending approval"
            )

        return RiskAssessment(
            flood_probability=float(value),
            risk_level=level,
            risk_score=float(risk_score) if risk_score is not None else float(value),
            threshold=threshold,
            threshold_source=self.policy.threshold_source,
            threshold_policy=self.policy.policy_status,
            method=method,
            residual_sigma=float(residual_sigma) if residual_sigma is not None else None,
            policy_approved=approved,
            notes=" ".join(notes),
        )

    def policy_summary(self) -> str:
        """One-line status of the threshold policy, safe to log."""
        return self.policy.describe()


def demo_risk_policy(
    threshold: float,
    band_edges: Sequence[float] = (0.1, 0.3, 0.6, 0.9),
) -> RiskPolicy:
    """Build an explicitly-DEMO policy.

    Provided so tests and the synthetic demo can exercise the risk path without
    an official threshold. The `policy_status` is `pending` on purpose: a
    threshold chosen by a developer is not an approved flood stage, and this
    helper must never be used to produce a production risk level.
    """
    return RiskPolicy(
        flood_threshold=threshold,
        threshold_source="DEMO value chosen for the synthetic pipeline; NOT an official flood stage",
        policy_status="pending",
        band_edges=tuple(float(edge) for edge in band_edges),
    )
