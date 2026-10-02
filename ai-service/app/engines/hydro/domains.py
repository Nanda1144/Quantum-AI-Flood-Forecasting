# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 1 — record schemas for the data domains the forecasting pipeline needs.

Scope
-----
This module is the **data / schema foundation**. It defines the shape of a
single ingested record for each domain the pipeline will eventually consume, and
nothing else. It does not compute, impute, aggregate, model or score anything:

* no rainfall accumulation (Phase 3 feature work),
* no resampling, filling or smoothing (Phase 2 preprocessing),
* no forecast, no risk arithmetic (Phases 5 and 6).

Why records, and not more columns
---------------------------------
`preprocessing.py` already validates and cleans a *wide* `DataFrame` whose
columns are named by `config.DatasetSpec`. That is the right shape for training.
It is the wrong shape for the things this repository still has to be able to say
"no, we do not have that": a gauge network that reports a level but no discharge,
a catchment with no rainfall record, an event register that does not exist.

A record schema makes each of those absences *representable and queryable*
instead of invisible. It is the contract between "a source has told us
something" and "the pipeline may use it".

Domains
-------
| Domain | What one record is | Canonical quantity |
| --- | --- | --- |
| `weather` | one instant at one location, with any number of declared quantities | open (temperature, humidity, ...) |
| `rainfall` | one measurement interval at one location | `rainfall` |
| `water_level` | one instant at one location | `water_level` |
| `discharge` | one instant at one location | `discharge` |
| `inflow` | one instant at one location | `inflow` |
| `flood_event` | one event at one area | — (no measurement) |
| `forecast` | **not defined here** — `contract.ForecastOutput` already owns it | — |
| `risk_score` | one assessed area, optionally tied to a forecast | — |

Provenance
----------
Every record carries the `dataset_type` vocabulary that `provenance.py` already
defines (`real` / `synthetic` / `unknown`) and a `provenance_reference`. There is
deliberately **no second provenance system**: the disclaimer text is imported
from `provenance`, and a `synthetic` or `unknown` record cannot be constructed
without the mandatory warning being attached.

Honesty invariants enforced here
-------------------------------
1. A timestamp must be an explicit, timezone-qualified instant. A naive
   timestamp is refused, not assumed to be UTC — that assumption is exactly how
   a series silently shifts by an offset.
2. `dataset_type` must be one of the three canonical values, and a non-real
   record always carries a disclaimer.
3. A unit must be present. It is *not* checked against a whitelist, because this
   repository has no authority over which units a foreign dataset uses (`cusecs`,
   `ft`, `m3/s`, and the deliberately-worded `UNDETERMINED (...)` demo unit are
   all legitimate strings). An unrecognised unit is a quality *warning*, never a
   rejection, and it is never converted.
4. Values must be finite. `NaN` is not a measurement and cannot be serialised.
5. `bool` is not a number. `Measurement(value=True)` is a type error.
6. Nothing here invents an identifier, a coordinate, a station or a threshold.
   An unknown fact is `None`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .contract import (
    SUPPORTED_PRIORITIES,
    SUPPORTED_RISK_LEVELS,
    priority_for_risk_level,
)
from .provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    SYNTHETIC_DATA_DISCLAIMER,
    UNVERIFIED_DATA_DISCLAIMER,
    combine_disclaimers,
)

# --------------------------------------------------------------------------- #
# Domain vocabulary
# --------------------------------------------------------------------------- #

#: Atmospheric / site conditions at an instant. Open-ended by design: a source
#: may report temperature and humidity, or pressure and wind speed, or both, and
#: this repository must not decide which of those a real dataset will contain.
DOMAIN_WEATHER = "weather"

#: Precipitation depth or intensity over a measurement window.
DOMAIN_RAINFALL = "rainfall"

#: Gauge stage. The vertical datum is NOT part of this schema, because no datum
#: has been supplied: `water_level` values from two gauges are not comparable
#: until their datums are, and no datum is invented here.
DOMAIN_WATER_LEVEL = "water_level"

#: Volume per unit time past a section.
DOMAIN_DISCHARGE = "discharge"

#: Volume per unit time entering a storage or reach. Distinct from `discharge`:
#: inflow forecasting is an explicit project requirement and a discharge gauge
#: does not measure it.
DOMAIN_INFLOW = "inflow"

#: A dated, located flood occurrence. Event registers do not exist in this
#: repository; the schema exists so that their *absence* is explicit.
DOMAIN_FLOOD_EVENT = "flood_event"

#: Persisted risk assessment. Schema only — the risk engine is Phase 6.
DOMAIN_RISK_SCORE = "risk_score"

#: Every domain this module can represent. `forecast` is absent on purpose: it
#: belongs to `contract.ForecastOutput`, and duplicating it here would create a
#: second, divergent forecast record.
DATA_DOMAINS = (
    DOMAIN_WEATHER,
    DOMAIN_RAINFALL,
    DOMAIN_WATER_LEVEL,
    DOMAIN_DISCHARGE,
    DOMAIN_INFLOW,
    DOMAIN_FLOOD_EVENT,
    DOMAIN_RISK_SCORE,
)

#: Domains that carry a numeric measurement. The other two do not.
MEASUREMENT_DOMAINS = (
    DOMAIN_WEATHER,
    DOMAIN_RAINFALL,
    DOMAIN_WATER_LEVEL,
    DOMAIN_DISCHARGE,
    DOMAIN_INFLOW,
)

# --------------------------------------------------------------------------- #
# Quantity vocabulary
# --------------------------------------------------------------------------- #

#: Canonical quantity for each single-quantity measurement domain. `weather` is
#: deliberately absent: it accepts any non-blank declared quantity.
CANONICAL_QUANTITY = {
    DOMAIN_RAINFALL: "rainfall",
    DOMAIN_WATER_LEVEL: "water_level",
    DOMAIN_DISCHARGE: "discharge",
    DOMAIN_INFLOW: "inflow",
}

#: Quantities called out by name because the project brief names them. They are
#: *examples of what a source may declare*, not a closed list and not a claim
#: that any source reports them.
QUANTITY_TEMPERATURE = "temperature"
QUANTITY_HUMIDITY = "humidity"
WEATHER_QUANTITIES = (QUANTITY_TEMPERATURE, QUANTITY_HUMIDITY)

#: Units this repository has seen declared. Used **only** to raise a warning for
#: an unrecognised unit, never to reject or convert one.
KNOWN_UNITS = frozenset(
    {
        # length / stage
        "m",
        "cm",
        "mm",
        "ft",
        # rainfall depth and rate
        "mm/h",
        "cm/h",
        "in",
        "in/h",
        # volumetric flow
        "m3/s",
        "m^3/s",
        "m3s-1",
        "cumecs",
        "cusecs",
        "ft3/s",
        # atmospheric
        "degC",
        "C",
        "degF",
        "F",
        "K",
        "%",
        "percent",
        "hPa",
        "mb",
        "Pa",
    }
)

#: Suffixes that make a unit a *rate* rather than an amount. A rate recorded
#: without a measurement window cannot be accumulated unambiguously, which is an
#: advisory for Phase 3 — not a computation performed here.
RATE_UNIT_SUFFIXES = ("/h", "/hr", "per_hour", "perhour")

# --------------------------------------------------------------------------- #
# Quality status vocabulary (record-level, orthogonal to provenance)
# --------------------------------------------------------------------------- #

#: The record passed every structural check.
QUALITY_OK = "ok"
#: The record is usable but something about it is unverified — typically a
#: missing source reference or an unrecognised unit.
QUALITY_SUSPECT = "suspect"
#: The supplier declared the value missing. Distinct from a null value: a null is
#: an absent fact, this is a declared absence.
QUALITY_MISSING = "missing"
#: The record failed a structural check and must not be used.
QUALITY_REJECTED = "rejected"
#: No quality assessment has been performed. The default, because asserting
#: `ok` without checking would be a claim this module cannot support.
QUALITY_UNKNOWN = "unknown"

QUALITY_STATUSES = (
    QUALITY_OK,
    QUALITY_SUSPECT,
    QUALITY_MISSING,
    QUALITY_REJECTED,
    QUALITY_UNKNOWN,
)

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class SchemaError(ValueError):
    """Raised when a record cannot be constructed honestly.

    This covers *shape* only — a missing identity, an unparseable instant, a
    non-finite value, an out-of-vocabulary status. Domain *plausibility* is not
    decided here; it is reported by `quality.py` so a caller can see every
    finding at once instead of dying on the first one.
    """


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant that carries an explicit UTC offset.

    A naive timestamp is refused rather than assumed to be UTC. Guessing the
    zone is how a series silently shifts by an offset, which would then corrupt
    every chronological boundary downstream — and nothing would report it.
    """
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"timestamp must be a non-empty ISO-8601 string, got {value!r}")
    text = value.strip()
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise SchemaError(
            f"timestamp {value!r} is not a parseable ISO-8601 instant "
            "(expected e.g. 2024-01-01T00:00:00Z)"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise SchemaError(
            f"timestamp {value!r} has no UTC offset; supply an explicit zone "
            "(e.g. 2024-01-01T00:00:00Z). A naive timestamp is refused rather "
            "than assumed to be UTC."
        )
    return parsed


def to_instant_iso(moment: datetime) -> str:
    """Render an aware `datetime` as ISO-8601 UTC with a trailing `Z`.

    Normalised to UTC so two records written from two different offsets compare
    correctly. The original offset is preserved in `observed_at`, which is what
    is stored; this helper exists for building payloads.
    """
    if moment.tzinfo is None:
        raise SchemaError("cannot render a timezone-naive datetime as an instant")
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def unit_is_known(unit: str) -> bool:
    """True when `unit` is one this repository has seen declared.

    Purely advisory: an unrecognised unit is still a legitimate unit, and this
    function never converts, normalises or guesses one.
    """
    return unit.strip() in KNOWN_UNITS


def unit_is_rate(unit: str) -> bool:
    """True when the unit denotes a per-hour rate rather than an amount."""
    lowered = unit.strip().lower()
    return any(lowered.endswith(suffix) for suffix in RATE_UNIT_SUFFIXES)


# --------------------------------------------------------------------------- #
# Measurements
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Measurement:
    """One numeric quantity with its unit, as reported by a source.

    `value` must be a finite real number. `unit` must be a non-blank string but is
    **not** validated against a whitelist, for the reason documented above.
    """

    quantity: str
    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, str) or not self.quantity.strip():
            raise SchemaError(f"quantity must be a non-empty string, got {self.quantity!r}")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise SchemaError(
                f"measurement {self.quantity!r} must declare a unit; an unlabelled number "
                "cannot be compared, converted or audited"
            )
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise SchemaError(
                f"measurement {self.quantity!r} value must be a real number, "
                f"got {type(self.value).__name__}"
            )
        if not math.isfinite(float(self.value)):
            raise SchemaError(
                f"measurement {self.quantity!r} value must be finite, got {self.value!r}; "
                "NaN and infinity are not measurements"
            )

    @property
    def unit_is_recognised(self) -> bool:
        return unit_is_known(self.unit)

    @property
    def is_rate(self) -> bool:
        return unit_is_rate(self.unit)

    def to_dict(self) -> dict[str, Any]:
        return {"quantity": self.quantity, "value": float(self.value), "unit": self.unit}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Measurement":
        if not isinstance(payload, Mapping):
            raise SchemaError(f"measurement payload must be a mapping, got {type(payload).__name__}")
        missing = [key for key in ("quantity", "value", "unit") if key not in payload]
        if missing:
            raise SchemaError(f"measurement payload is missing key(s): {missing}")
        return cls(
            quantity=payload["quantity"],
            value=payload["value"],
            unit=payload["unit"],
        )


# --------------------------------------------------------------------------- #
# Provenance mix-in
# --------------------------------------------------------------------------- #


def _check_dataset_type(value: Any) -> str:
    if value not in (DATASET_TYPE_REAL, DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN):
        raise SchemaError(
            f"dataset_type must be one of "
            f"{(DATASET_TYPE_REAL, DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN)!r}, got {value!r}"
        )
    return value


def _required_disclaimer(dataset_type: str) -> str | None:
    """The mandatory warning for a dataset type, or `None` for real data.

    Imported from `provenance` so there is exactly one copy of this sentence in
    the tree. A `real` record must not carry it: a genuine observation that is
    dismissed as fake is its own kind of dishonesty.
    """
    if dataset_type == DATASET_TYPE_SYNTHETIC:
        return SYNTHETIC_DATA_DISCLAIMER
    if dataset_type == DATASET_TYPE_UNKNOWN:
        return UNVERIFIED_DATA_DISCLAIMER
    return None


def _merge_disclaimer(dataset_type: str, supplied: str | None) -> str | None:
    """Attach the mandatory warning exactly once.

    Three rules, in order:

    * **real** — the mandatory warning is `None`, so it is not added. A caller
      that supplies one anyway is refused, because the database constraint in
      `010_navya_forecast_provenance.up.sql` requires `disclaimer IS NULL` for
      real data, and a record the schema accepts but the database rejects is a
      latent insert failure.
    * **non-real with no disclaimer** — the mandatory warning is attached.
    * **non-real with a disclaimer** — attached only if it is not already there.
      The containment check is what makes `to_dict()` → `from_dict()` round-trip
      instead of doubling the sentence on every hop, which is a real failure mode
      for a field that gets serialised on the way into a database and read back
      out of one.
    """
    required = _required_disclaimer(dataset_type)
    text = _check_optional_reference(supplied, "disclaimer")
    if dataset_type == DATASET_TYPE_REAL:
        if text is not None:
            raise SchemaError(
                "a record with dataset_type 'real' must not carry a disclaimer: real data may "
                "not be labelled as synthetic, and the storage constraint requires NULL"
            )
        return None
    if text is None:
        return required
    if required is not None and required in text:
        return text
    return combine_disclaimers(required, text)


def _check_optional_reference(value: Any, name: str) -> str | None:
    """Normalise an optional identifier: blanks become `None`, never `''`."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaError(f"{name} must be a string or None, got {type(value).__name__}")
    text = value.strip()
    return text or None


# --------------------------------------------------------------------------- #
# Observations (weather, rainfall, water level, discharge, inflow)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Observation:
    """One measurement record for one domain at one location at one instant.

    `dataset_type` defaults to `unknown`, which is the honest default for a
    record nobody has classified. With that default the mandatory "unverified"
    disclaimer is attached automatically, so an unlabelled record cannot travel
    further than one field.
    """

    domain: str
    location_reference: str
    observed_at: str
    measurements: tuple[Measurement, ...]
    measurement_window: str | None = None
    source_reference: str | None = None
    provenance_reference: str | None = None
    dataset_type: str = DATASET_TYPE_UNKNOWN
    dataset_reference: str | None = None
    quality_status: str = QUALITY_UNKNOWN
    disclaimer: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.domain not in DATA_DOMAINS:
            raise SchemaError(
                f"unknown domain {self.domain!r}; expected one of {DATA_DOMAINS}"
            )
        if self.domain not in MEASUREMENT_DOMAINS:
            raise SchemaError(
                f"domain {self.domain!r} does not carry measurements; build a "
                f"{'FloodEvent' if self.domain == DOMAIN_FLOOD_EVENT else 'RiskScoreRecord'} instead"
            )
        location = _check_optional_reference(self.location_reference, "location_reference")
        if location is None:
            raise SchemaError(
                "location_reference is required and must be a non-empty string; an "
                "observation with no location cannot be attributed to a station, a "
                "reach or a catchment"
            )
        object.__setattr__(self, "location_reference", location)

        parse_instant(self.observed_at)

        measurements = tuple(self.measurements)
        if not measurements:
            raise SchemaError(
                f"a {self.domain} observation must carry at least one measurement; "
                "an empty measurement tuple is a gap, not a reading"
            )
        for item in measurements:
            if not isinstance(item, Measurement):
                raise SchemaError(
                    f"measurements must be Measurement instances, got {type(item).__name__}"
                )
        quantities = [item.quantity for item in measurements]
        duplicates = sorted({q for q in quantities if quantities.count(q) > 1})
        if duplicates:
            raise SchemaError(
                f"duplicate quantity/quantities in one observation: {duplicates}; "
                "two values for one quantity at one instant are ambiguous"
            )
        canonical = CANONICAL_QUANTITY.get(self.domain)
        if canonical is not None:
            unexpected = [q for q in quantities if q != canonical]
            if unexpected:
                raise SchemaError(
                    f"domain {self.domain!r} accepts only the {canonical!r} quantity, "
                    f"got {unexpected}"
                )
        object.__setattr__(self, "measurements", measurements)

        for name in ("measurement_window", "source_reference", "provenance_reference", "dataset_reference"):
            object.__setattr__(self, name, _check_optional_reference(getattr(self, name), name))

        _check_dataset_type(self.dataset_type)

        if self.quality_status not in QUALITY_STATUSES:
            raise SchemaError(
                f"quality_status must be one of {QUALITY_STATUSES}, got {self.quality_status!r}"
            )

        object.__setattr__(self, "disclaimer", _merge_disclaimer(self.dataset_type, self.disclaimer))

    # --- accessors ---------------------------------------------------------

    @property
    def instant(self) -> datetime:
        """The parsed observation instant."""
        return parse_instant(self.observed_at)

    @property
    def is_synthetic(self) -> bool:
        return self.dataset_type == DATASET_TYPE_SYNTHETIC

    @property
    def may_be_presented_as_observation_data(self) -> bool:
        """True only when provenance permits showing the value as an observation.

        `unknown` provenance is deliberately **not** enough, and neither is a
        clean structure check. This mirrors `backend/src/navya/forecasting/
        provenance.ts` → `isPresentableAsRealResult` so the rule is the same on
        both sides of the wire.
        """
        return self.dataset_type == DATASET_TYPE_REAL and self.disclaimer is None

    def value_for(self, quantity: str) -> float | None:
        """The value of `quantity`, or `None` when this record does not carry it."""
        for item in self.measurements:
            if item.quantity == quantity:
                return float(item.value)
        return None

    def unit_for(self, quantity: str) -> str | None:
        for item in self.measurements:
            if item.quantity == quantity:
                return item.unit
        return None

    def quantity(self) -> str | None:
        """The canonical quantity of a single-quantity domain, else `None`."""
        return CANONICAL_QUANTITY.get(self.domain)

    def with_quality_status(self, status: str) -> "Observation":
        """A copy carrying a different quality status.

        Exists so that validation *records* an assessment rather than the
        validator silently upgrading or rewriting the supplier's declaration.
        """
        if status not in QUALITY_STATUSES:
            raise SchemaError(f"quality_status must be one of {QUALITY_STATUSES}, got {status!r}")
        return Observation(
            domain=self.domain,
            location_reference=self.location_reference,
            observed_at=self.observed_at,
            measurements=self.measurements,
            measurement_window=self.measurement_window,
            source_reference=self.source_reference,
            provenance_reference=self.provenance_reference,
            dataset_type=self.dataset_type,
            dataset_reference=self.dataset_reference,
            quality_status=status,
            disclaimer=self.disclaimer,
            notes=self.notes,
        )

    # --- forecast hand-off (schema-level only) ---------------------------

    def forecast_inputs(self) -> dict[str, Any]:
        """The `contract.ForecastOutput` fields this record can honestly supply.

        This is a *mapping of facts*, not a forecast. Every key is the name of a
        real `ForecastOutput` field, asserted as a subset relation in
        `test_hydro_domains.py`, so Phase 5 cannot quietly invent a
        differently-spelled one. Anything the record does not know is absent from
        the mapping rather than filled with a default.

        `dataset_type` is deliberately **not** here: `ForecastOutput` has no such
        field. It travels beside the forecast in `ProvenanceRecord` and in the
        proposed handoff payload — see `forecast_provenance_inputs()`.
        """
        quantity = self.quantity()
        inputs: dict[str, Any] = {
            "station_reference": self.location_reference,
            "target": quantity,
            "target_units": self.unit_for(quantity) if quantity else None,
            "provenance_reference": self.provenance_reference,
        }
        return {key: value for key, value in inputs.items() if value is not None}

    def forecast_provenance_inputs(self) -> dict[str, Any]:
        """Facts that travel *with* a forecast rather than inside it.

        These are the fields the provenance record and the proposed
        optimization handoff need. Kept apart from `forecast_inputs()` because
        mixing them would suggest `ForecastOutput` carries a `dataset_type` field
        it does not have — and a reader who believed that would look for it in the
        forecast payload and not find it.
        """
        return {
            "dataset_type": self.dataset_type,
            "dataset_reference": self.dataset_reference,
            "disclaimer": self.disclaimer,
        }

    def missing_forecast_inputs(self) -> tuple[str, ...]:
        """Contract fields a forecast built from this record could not supply.

        An empty tuple means the record carries enough to populate the contract's
        identifying fields. It says nothing about whether a model exists, a
        threshold is approved, or the forecast is servable — those are Phase 5
        concerns and `config.HydroConfig.readiness()` already governs them.
        """
        supplied = self.forecast_inputs()
        return tuple(name for name in ("station_reference", "target", "target_units") if name not in supplied)

    # --- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "location_reference": self.location_reference,
            "observed_at": self.observed_at,
            "measurements": [item.to_dict() for item in self.measurements],
            "measurement_window": self.measurement_window,
            "source_reference": self.source_reference,
            "provenance_reference": self.provenance_reference,
            "dataset_reference": self.dataset_reference,
            "dataset_type": self.dataset_type,
            "quality_status": self.quality_status,
            "disclaimer": self.disclaimer,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Observation":
        if not isinstance(payload, Mapping):
            raise SchemaError(f"observation payload must be a mapping, got {type(payload).__name__}")
        missing = [
            key
            for key in ("domain", "location_reference", "observed_at", "measurements")
            if key not in payload
        ]
        if missing:
            raise SchemaError(f"observation payload is missing key(s): {missing}")
        raw_measurements = payload["measurements"]
        if not isinstance(raw_measurements, Sequence) or isinstance(raw_measurements, (str, bytes)):
            raise SchemaError("observation 'measurements' must be a sequence of mappings")
        return cls(
            domain=payload["domain"],
            location_reference=payload["location_reference"],
            observed_at=payload["observed_at"],
            measurements=tuple(Measurement.from_dict(item) for item in raw_measurements),
            measurement_window=payload.get("measurement_window"),
            source_reference=payload.get("source_reference"),
            provenance_reference=payload.get("provenance_reference"),
            dataset_reference=payload.get("dataset_reference"),
            dataset_type=payload.get("dataset_type", DATASET_TYPE_UNKNOWN),
            quality_status=payload.get("quality_status", QUALITY_UNKNOWN),
            disclaimer=payload.get("disclaimer"),
            notes=payload.get("notes", ""),
        )


# --------------------------------------------------------------------------- #
# Flood events
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FloodEvent:
    """One flood occurrence at one area.

    **This repository contains no flood event register, and this class creates
    none.** It exists so that the absence is a representable, queryable fact and
    so that a future register has a schema to land in without a redesign.

    `severity` and `status` are free text on purpose. There is no approved
    severity scale or event-status vocabulary in this project, and inventing one
    would present this project's guess as a standard. Whatever vocabulary a real
    register uses is carried verbatim in `severity`/`status`, with
    `severity_source` naming the authority.
    """

    event_reference: str
    area_reference: str
    started_at: str
    ended_at: str | None = None
    severity: str | None = None
    severity_source: str | None = None
    status: str = "unknown"
    source_reference: str | None = None
    provenance_reference: str | None = None
    dataset_reference: str | None = None
    dataset_type: str = DATASET_TYPE_UNKNOWN
    disclaimer: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("event_reference", "area_reference"):
            value = _check_optional_reference(getattr(self, name), name)
            if value is None:
                raise SchemaError(f"{name} is required and must be a non-empty string")
            object.__setattr__(self, name, value)

        start = parse_instant(self.started_at)
        end_text = _check_optional_reference(self.ended_at, "ended_at")
        if end_text is not None:
            end = parse_instant(end_text)
            if end < start:
                raise SchemaError(
                    f"ended_at {end_text!r} precedes started_at {self.started_at!r}"
                )
        object.__setattr__(self, "ended_at", end_text)

        for name in ("severity", "severity_source", "source_reference", "provenance_reference", "dataset_reference"):
            object.__setattr__(self, name, _check_optional_reference(getattr(self, name), name))

        status = _check_optional_reference(self.status, "status")
        object.__setattr__(self, "status", status or "unknown")

        _check_dataset_type(self.dataset_type)
        object.__setattr__(self, "disclaimer", _merge_disclaimer(self.dataset_type, self.disclaimer))

    @property
    def is_ongoing(self) -> bool:
        """True when the event has no recorded end.

        Deliberately weak: it means "no end was recorded", which is not the same
        as "the flood is still happening", and the difference matters when the
        record is read by someone deciding whether to issue a warning.
        """
        return self.ended_at is None

    @property
    def is_synthetic(self) -> bool:
        return self.dataset_type == DATASET_TYPE_SYNTHETIC

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": DOMAIN_FLOOD_EVENT,
            "event_reference": self.event_reference,
            "area_reference": self.area_reference,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "severity": self.severity,
            "severity_source": self.severity_source,
            "status": self.status,
            "source_reference": self.source_reference,
            "provenance_reference": self.provenance_reference,
            "dataset_reference": self.dataset_reference,
            "dataset_type": self.dataset_type,
            "disclaimer": self.disclaimer,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FloodEvent":
        if not isinstance(payload, Mapping):
            raise SchemaError(f"flood-event payload must be a mapping, got {type(payload).__name__}")
        missing = [
            key for key in ("event_reference", "area_reference", "started_at") if key not in payload
        ]
        if missing:
            raise SchemaError(f"flood-event payload is missing key(s): {missing}")
        return cls(
            event_reference=payload["event_reference"],
            area_reference=payload["area_reference"],
            started_at=payload["started_at"],
            ended_at=payload.get("ended_at"),
            severity=payload.get("severity"),
            severity_source=payload.get("severity_source"),
            status=payload.get("status", "unknown"),
            source_reference=payload.get("source_reference"),
            provenance_reference=payload.get("provenance_reference"),
            dataset_reference=payload.get("dataset_reference"),
            dataset_type=payload.get("dataset_type", DATASET_TYPE_UNKNOWN),
            disclaimer=payload.get("disclaimer"),
            notes=payload.get("notes", ""),
        )


# --------------------------------------------------------------------------- #
# Risk score records
# --------------------------------------------------------------------------- #

#: Lifecycle of a persisted risk record. Deliberately separate from
#: `contract.ForecastOutput.status` ("completed"/"pending"/"failed"), which
#: describes a *forecast*. A risk record that borrows the forecast's vocabulary
#: would conflate "the forecast failed" with "the assessment was not made".
RISK_STATUS_PENDING = "pending"
RISK_STATUS_RECORDED = "recorded"
RISK_STATUS_WITHHELD = "withheld"
RISK_STATUSES = (RISK_STATUS_PENDING, RISK_STATUS_RECORDED, RISK_STATUS_WITHHELD)


@dataclass(frozen=True)
class RiskScoreRecord:
    """One assessed area, optionally attributable to a forecast.

    Schema only. The risk *engine* is Phase 6 and the exposure model that would
    put a population or an asset behind this score does not exist in this
    repository — so this record carries no population, no asset count, no
    coordinates and no elevation, and nothing here fabricates them.

    `risk_level` and `priority` are restricted to the platform vocabularies
    declared in `contract.py` rather than to a new list, so the two cannot drift.
    `priority` is derived from `risk_level` when it is not supplied, which is the
    same mapping the running backend already applies.
    """

    area_reference: str
    risk_score: float | None = None
    risk_level: str | None = None
    priority: str | None = None
    forecast_reference: str | None = None
    assessed_at: str | None = None
    status: str = RISK_STATUS_PENDING
    threshold: float | None = None
    threshold_policy: str = "pending"
    threshold_source: str | None = None
    provenance_reference: str | None = None
    dataset_reference: str | None = None
    dataset_type: str = DATASET_TYPE_UNKNOWN
    disclaimer: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        area = _check_optional_reference(self.area_reference, "area_reference")
        if area is None:
            raise SchemaError("area_reference is required and must be a non-empty string")
        object.__setattr__(self, "area_reference", area)

        if self.risk_score is not None:
            if isinstance(self.risk_score, bool) or not isinstance(self.risk_score, (int, float)):
                raise SchemaError(
                    f"risk_score must be a real number or None, got {type(self.risk_score).__name__}"
                )
            score = float(self.risk_score)
            if not math.isfinite(score):
                raise SchemaError(f"risk_score must be finite, got {self.risk_score!r}")
            if not 0.0 <= score <= 1.0:
                # The optimizer's objective reads a [0, 1] risk term; a score
                # outside that band is a scale error, not a high risk.
                raise SchemaError(
                    f"risk_score must lie in [0, 1] to be usable by the optimizer's "
                    f"objective, got {self.risk_score!r}"
                )
            object.__setattr__(self, "risk_score", score)

        if self.risk_level is not None and self.risk_level not in SUPPORTED_RISK_LEVELS:
            raise SchemaError(
                f"risk_level {self.risk_level!r} is not one of {SUPPORTED_RISK_LEVELS}"
            )

        if self.priority is not None and self.priority not in SUPPORTED_PRIORITIES:
            raise SchemaError(
                f"priority {self.priority!r} is not one of {SUPPORTED_PRIORITIES}"
            )
        if self.priority is None:
            object.__setattr__(self, "priority", priority_for_risk_level(self.risk_level))

        if self.threshold is not None:
            if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)):
                raise SchemaError("threshold must be a real number or None")
            if not math.isfinite(float(self.threshold)):
                raise SchemaError(f"threshold must be finite, got {self.threshold!r}")

        if self.threshold_policy not in ("pending", "approved"):
            raise SchemaError(
                f"threshold_policy must be 'pending' or 'approved', got {self.threshold_policy!r}"
            )
        if self.threshold_policy == "approved" and (
            self.threshold is None
            or _check_optional_reference(self.threshold_source, "threshold_source") is None
        ):
            # Mirrors 010_navya_forecast_provenance.up.sql: approval is a claim
            # about provenance and requires evidence. Silence is not approval.
            raise SchemaError(
                "threshold_policy='approved' requires both a threshold and a "
                "threshold_source; an approved threshold with no citation is not approval"
            )

        if self.status not in RISK_STATUSES:
            raise SchemaError(f"status must be one of {RISK_STATUSES}, got {self.status!r}")

        assessed = _check_optional_reference(self.assessed_at, "assessed_at")
        if assessed is not None:
            parse_instant(assessed)
        object.__setattr__(self, "assessed_at", assessed)

        for name in ("forecast_reference", "threshold_source", "provenance_reference", "dataset_reference"):
            object.__setattr__(self, name, _check_optional_reference(getattr(self, name), name))

        _check_dataset_type(self.dataset_type)
        object.__setattr__(self, "disclaimer", _merge_disclaimer(self.dataset_type, self.disclaimer))

    @property
    def is_available(self) -> bool:
        """True when a score *and* a level were actually assigned.

        A pending record with no score is the honest state, and it must not be
        rendered as a zero risk — an unassessed area is not a safe area.
        """
        return self.risk_score is not None and self.risk_level is not None

    def missing_fields(self) -> tuple[str, ...]:
        """Fields a reader would need in order to treat this as a result."""
        checks = {
            "area_reference": self.area_reference or None,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "priority": self.priority,
            "forecast_reference": self.forecast_reference,
            "assessed_at": self.assessed_at,
            "provenance_reference": self.provenance_reference,
            "dataset_reference": self.dataset_reference,
        }
        return tuple(name for name, value in checks.items() if value in (None, ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": DOMAIN_RISK_SCORE,
            "area_reference": self.area_reference,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "priority": self.priority,
            "forecast_reference": self.forecast_reference,
            "assessed_at": self.assessed_at,
            "status": self.status,
            "threshold": self.threshold,
            "threshold_policy": self.threshold_policy,
            "threshold_source": self.threshold_source,
            "provenance_reference": self.provenance_reference,
            "dataset_reference": self.dataset_reference,
            "dataset_type": self.dataset_type,
            "disclaimer": self.disclaimer,
            "missing_fields": list(self.missing_fields()),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RiskScoreRecord":
        if not isinstance(payload, Mapping):
            raise SchemaError(f"risk-record payload must be a mapping, got {type(payload).__name__}")
        if "area_reference" not in payload:
            raise SchemaError("risk-record payload is missing key(s): ['area_reference']")
        known = {
            "domain",  # echoed by to_dict(), not a constructor argument
            "area_reference",
            "risk_score",
            "risk_level",
            "priority",
            "forecast_reference",
            "assessed_at",
            "status",
            "threshold",
            "threshold_policy",
            "threshold_source",
            "provenance_reference",
            "dataset_reference",
            "dataset_type",
            "disclaimer",
            "notes",
            "missing_fields",  # derived by to_dict(), not a constructor argument
        }
        unknown = sorted(set(payload) - known)
        if unknown:
            raise SchemaError(f"risk-record payload has unknown key(s): {unknown}")
        return cls(
            area_reference=payload["area_reference"],
            risk_score=payload.get("risk_score"),
            risk_level=payload.get("risk_level"),
            priority=payload.get("priority"),
            forecast_reference=payload.get("forecast_reference"),
            assessed_at=payload.get("assessed_at"),
            status=payload.get("status", RISK_STATUS_PENDING),
            threshold=payload.get("threshold"),
            threshold_policy=payload.get("threshold_policy", "pending"),
            threshold_source=payload.get("threshold_source"),
            provenance_reference=payload.get("provenance_reference"),
            dataset_reference=payload.get("dataset_reference"),
            dataset_type=payload.get("dataset_type", DATASET_TYPE_UNKNOWN),
            disclaimer=payload.get("disclaimer"),
            notes=payload.get("notes", ""),
        )


# --------------------------------------------------------------------------- #
# Domain registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DomainSpec:
    """What one domain is for, and what a record of it must carry.

    Exists so that "which domains exist, and what does each require?" is data
    rather than prose scattered across three modules. Adding a domain later is
    an entry here plus a record class, not a change to every consumer.
    """

    name: str
    record_type: str
    requires_measurement: bool
    canonical_quantity: str | None = None
    open_quantities: tuple[str, ...] = ()
    non_negative_quantities: tuple[str, ...] = ()
    #: Whether Phase 2/3 may accumulate this domain over a window. Recorded as a
    #: capability note, not an implementation: no accumulation is computed here.
    accumulable: bool = False
    #: Whether this repository holds any record of this kind today.
    present_in_repository: bool = False
    #: What is missing, in the project's documented marker style.
    availability_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "record_type": self.record_type,
            "requires_measurement": self.requires_measurement,
            "canonical_quantity": self.canonical_quantity,
            "open_quantities": list(self.open_quantities),
            "non_negative_quantities": list(self.non_negative_quantities),
            "accumulable": self.accumulable,
            "present_in_repository": self.present_in_repository,
            "availability_note": self.availability_note,
        }


#: `NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`, the project's
#: documented marker for an absent human-supplied fact. Used verbatim so the
#: absence reads the same here as it does in `02_Architecture/`.
NOT_AVAILABLE = "NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED"

DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec(
        name=DOMAIN_WEATHER,
        record_type="Observation",
        requires_measurement=True,
        open_quantities=WEATHER_QUANTITIES,
        present_in_repository=False,
        availability_note=(
            "No weather dataset (temperature, humidity, pressure, wind) exists in this "
            "repository. " + NOT_AVAILABLE
        ),
    ),
    DomainSpec(
        name=DOMAIN_RAINFALL,
        record_type="Observation",
        requires_measurement=True,
        canonical_quantity="rainfall",
        accumulable=True,
        present_in_repository=True,
        availability_note=(
            "Only SYNTHETIC/DEMO values from the committed generator exist. Rainfall is "
            "synthetic until a real record is supplied. "
            "Accumulation is Phase 3 feature work and is NOT computed here."
        ),
    ),
    DomainSpec(
        name=DOMAIN_WATER_LEVEL,
        record_type="Observation",
        requires_measurement=True,
        canonical_quantity="water_level",
        present_in_repository=True,
        availability_note=(
            "Only SYNTHETIC/DEMO values exist, and their vertical datum is fictional. "
            "No official gauge datum or flood stage has been supplied. " + NOT_AVAILABLE
        ),
    ),
    DomainSpec(
        name=DOMAIN_DISCHARGE,
        record_type="Observation",
        requires_measurement=True,
        canonical_quantity="discharge",
        non_negative_quantities=("discharge",),
        present_in_repository=False,
        availability_note=(
            "No discharge record and no rating curve exist in this repository. "
            + NOT_AVAILABLE
        ),
    ),
    DomainSpec(
        name=DOMAIN_INFLOW,
        record_type="Observation",
        requires_measurement=True,
        canonical_quantity="inflow",
        non_negative_quantities=("inflow",),
        present_in_repository=True,
        availability_note=(
            "Only SYNTHETIC/DEMO values exist, with an UNDETERMINED unit. No real "
            "inflow measurement or unit has been supplied. " + NOT_AVAILABLE
        ),
    ),
    DomainSpec(
        name=DOMAIN_FLOOD_EVENT,
        record_type="FloodEvent",
        requires_measurement=False,
        present_in_repository=False,
        availability_note=(
            "No flood event register exists in this repository, and none may be "
            "invented. " + NOT_AVAILABLE
        ),
    ),
    DomainSpec(
        name=DOMAIN_RISK_SCORE,
        record_type="RiskScoreRecord",
        requires_measurement=False,
        present_in_repository=False,
        availability_note=(
            "Schema only. The risk engine is Phase 6, and no exposure data (population, "
            "assets, elevation) exists here. " + NOT_AVAILABLE
        ),
    ),
)


def domain_spec(domain: str) -> DomainSpec:
    """The registered spec for `domain`.

    Raises rather than returning a default: an unregistered domain is a bug, and
    a permissive default would let one through unnoticed.
    """
    for spec in DOMAIN_SPECS:
        if spec.name == domain:
            return spec
    raise SchemaError(
        f"unknown domain {domain!r}; registered domains are "
        f"{tuple(spec.name for spec in DOMAIN_SPECS)}"
    )


def domain_catalog() -> list[dict[str, Any]]:
    """Every registered domain, as plain data. Safe to serialise or document."""
    return [spec.to_dict() for spec in DOMAIN_SPECS]


def describe_domains() -> str:
    """Human-readable domain table, safe to print in a report or a log."""
    lines = ["DATA DOMAINS (Phase 1 schema foundation)", ""]
    width = max(len(spec.name) for spec in DOMAIN_SPECS)
    for spec in DOMAIN_SPECS:
        present = "present (synthetic/demo only)" if spec.present_in_repository else NOT_AVAILABLE
        lines.append(f"  {spec.name.ljust(width)}  record={spec.record_type}  {present}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Parsing a tabular source into records
# --------------------------------------------------------------------------- #

#: Column name → domain for the columns this repository knows about. A real
#: dataset will use different names; the mapping is supplied by the dataset owner
#: via `config.DatasetSpec`, never inferred from a header at random.
DEFAULT_COLUMN_DOMAINS: Mapping[str, str] = {
    "rainfall_mm": DOMAIN_RAINFALL,
    "rainfall": DOMAIN_RAINFALL,
    "water_level": DOMAIN_WATER_LEVEL,
    "discharge": DOMAIN_DISCHARGE,
    "inflow": DOMAIN_INFLOW,
    "temperature": DOMAIN_WEATHER,
    "humidity": DOMAIN_WEATHER,
}


@dataclass(frozen=True)
class ColumnBinding:
    """Declared mapping of one source column onto one domain quantity.

    The unit is a **declaration by the dataset owner**. Nothing infers it from a
    column name: `water_level` says nothing about metres versus feet, and
    guessing is how a whole dataset ends up analysed in the wrong units.
    """

    column: str
    domain: str
    quantity: str
    unit: str
    accumulates: bool = False

    def __post_init__(self) -> None:
        domain_spec(self.domain)
        for name in ("column", "quantity", "unit"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise SchemaError(f"ColumnBinding {name} must be a non-empty string")

    def to_measurement(self, value: Any) -> Measurement:
        """Build a `Measurement` from one source value.

        Raises `SchemaError` on a non-numeric or non-finite value rather than
        coercing it: `pd.to_numeric(errors="coerce")` would turn an unparseable
        cell into a silent NaN, and a silent NaN in a gauge record is a hole in
        the record that nobody is told about.
        """
        if value is None:
            raise SchemaError(f"column {self.column!r} has no value; use a "
                              "quality_status of 'missing' rather than a null reading")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise SchemaError(
                    f"column {self.column!r} holds {value!r}, which is not a number"
                ) from exc
            if math.isnan(parsed):
                raise SchemaError(f"column {self.column!r} holds NaN, which is not a measurement")
            return Measurement(quantity=self.quantity, value=parsed, unit=self.unit)
        return Measurement(quantity=self.quantity, value=value, unit=self.unit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "domain": self.domain,
            "quantity": self.quantity,
            "unit": self.unit,
            "accumulates": self.accumulates,
        }


def observations_from_row(
    row: Mapping[str, Any],
    bindings: Sequence[ColumnBinding],
    *,
    timestamp_column: str = "timestamp",
    location_reference: str,
    dataset_type: str = DATASET_TYPE_UNKNOWN,
    source_reference: str | None = None,
    provenance_reference: str | None = None,
    dataset_reference: str | None = None,
    measurement_window: str | None = None,
) -> list[Observation]:
    """Split one wide source row into one record per domain.

    A row that reports level *and* rainfall at one instant is two records, not
    one record with two quantities — because the two have different units, and a
    record with mixed units cannot be compared or converted without the caller
    re-parsing it. Grouping them here is the whole point.

    Columns that are absent from the row are skipped rather than defaulted: an
    absent column is a domain this source does not report, and it is reported
    that way by `quality.py`, not invented as zero.
    """
    if timestamp_column not in row:
        raise SchemaError(f"row has no {timestamp_column!r} column")

    # A bound column that the row does not carry is a domain this source does not
    # report for this row. It is skipped rather than defaulted, and reported by
    # `quality.validate_observation_payload` as an absent-column finding.
    grouped: dict[str, list[ColumnBinding]] = {}
    for binding in bindings:
        if binding.column in row:
            grouped.setdefault(binding.domain, []).append(binding)

    records: list[Observation] = []
    for domain, domain_bindings in grouped.items():
        measurements: list[Measurement] = []
        for binding in domain_bindings:
            value = row[binding.column]
            if value is None:
                # A declared gap is carried as an explicit absence (a record with
                # no measurement is refused), so it is skipped here and reported
                # by quality validation rather than becoming a zero reading.
                continue
            measurements.append(binding.to_measurement(value))
        if not measurements:
            continue
        records.append(
            Observation(
                domain=domain,
                location_reference=location_reference,
                observed_at=str(row[timestamp_column]),
                measurements=tuple(measurements),
                measurement_window=measurement_window,
                source_reference=source_reference,
                provenance_reference=provenance_reference,
                dataset_reference=dataset_reference,
                dataset_type=dataset_type,
            )
        )
    return records


def unknown_columns(
    row: Mapping[str, Any], bindings: Sequence[ColumnBinding], timestamp_column: str = "timestamp"
) -> tuple[str, ...]:
    """Columns present in `row` that no binding claims.

    Returned rather than ignored, so an unmapped column is visible. An unmapped
    column is usually a real observation this schema was not told about, and
    silently ignoring it is how a domain goes missing without anyone noticing.
    """
    claimed = {binding.column for binding in bindings} | {timestamp_column}
    return tuple(sorted(key for key in row if key not in claimed))


__all__ = [
    "CANONICAL_QUANTITY",
    "DATA_DOMAINS",
    "DEFAULT_COLUMN_DOMAINS",
    "DOMAIN_DISCHARGE",
    "DOMAIN_FLOOD_EVENT",
    "DOMAIN_INFLOW",
    "DOMAIN_RAINFALL",
    "DOMAIN_RISK_SCORE",
    "DOMAIN_SPECS",
    "DOMAIN_WATER_LEVEL",
    "DOMAIN_WEATHER",
    "KNOWN_UNITS",
    "MEASUREMENT_DOMAINS",
    "NOT_AVAILABLE",
    "QUALITY_MISSING",
    "QUALITY_OK",
    "QUALITY_REJECTED",
    "QUALITY_STATUSES",
    "QUALITY_SUSPECT",
    "QUALITY_UNKNOWN",
    "QUANTITY_HUMIDITY",
    "QUANTITY_TEMPERATURE",
    "RATE_UNIT_SUFFIXES",
    "RISK_STATUSES",
    "RISK_STATUS_PENDING",
    "RISK_STATUS_RECORDED",
    "RISK_STATUS_WITHHELD",
    "WEATHER_QUANTITIES",
    "ColumnBinding",
    "DomainSpec",
    "FloodEvent",
    "Measurement",
    "Observation",
    "RiskScoreRecord",
    "SchemaError",
    "describe_domains",
    "domain_catalog",
    "domain_spec",
    "observations_from_row",
    "parse_instant",
    "to_instant_iso",
    "unit_is_known",
    "unit_is_rate",
    "unknown_columns",
]