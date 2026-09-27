# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Deterministic SYNTHETIC/DEMO hydrological series generator.

EVERYTHING THIS MODULE PRODUCES IS SYNTHETIC.
SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION
DATA. The values are produced by a closed-form generator with a fixed seed; they
are not measurements, they carry no station identity, and no metric computed
from them is a hydrological result.

The generator exists so the pipeline is runnable and testable end-to-end before a
real dataset is supplied. It is not a substitute for one, and `dataset_type` for
anything it produces must be declared `synthetic` so provenance and every
downstream report label it correctly.

Generative model
----------------
A damped baseflow signal plus a rainfall-driven response:

* `baseflow(t)   = 3.0 + 1.1 * annual_sin(t) + 0.4 * semi_diurnal(t)`
* `rain(t)       = clip(seasonal envelope * bounded noise, 0, ...)`
* `water(t)      = baseflow(t) + rain_response(t)` where `rain_response` is a
  decaying accumulation of recent rainfall
* `inflow(t)     = 40 + 18 * water(t) + bounded noise`, floored at 0

`random_state` makes the output byte-reproducible, so a test asserting on the
series cannot flake.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from .provenance import (
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
    file_checksum,
)

#: Reference used by every synthetic artifact. The `synthetic://` scheme makes
#: the provenance of a demo row visible in a database dump.
SYNTHETIC_REFERENCE_PREFIX = "synthetic://"

#: Column names produced by the generator.
SYNTHETIC_COLUMNS = ("timestamp", "water_level", "inflow", "rainfall_mm")


@dataclass(frozen=True)
class SyntheticSeriesSpec:
    """Parameters of the synthetic generator. All are demo parameters."""

    n_rows: int = 8760
    start: str = "2023-01-01T00:00:00Z"
    interval_hours: int = 1
    random_state: int = 20260101
    base_level: float = 3.0
    annual_amplitude: float = 1.1
    rain_peak_mm_per_hour: float = 6.0
    noise_scale: float = 0.08

    def __post_init__(self) -> None:
        if self.n_rows < 24:
            raise ValueError(f"n_rows must be at least 24, got {self.n_rows}")
        if self.interval_hours < 1:
            raise ValueError(f"interval_hours must be >= 1, got {self.interval_hours}")
        if self.random_state < 0:
            raise ValueError("random_state must be >= 0")


def _timestamps(spec: SyntheticSeriesSpec) -> pd.DatetimeIndex:
    start = datetime.fromisoformat(spec.start.replace("Z", "+00:00")).astimezone(timezone.utc)
    index = pd.date_range(
        start=start, periods=spec.n_rows, freq=pd.Timedelta(hours=spec.interval_hours)
    )
    return index.tz_localize(None)


def generate_synthetic_series(spec: SyntheticSeriesSpec | None = None) -> pd.DataFrame:
    """Generate a deterministic synthetic `water_level` / `inflow` / `rainfall` frame.

    The returned frame has exactly the columns `SYNTHETIC_COLUMNS` and is safe to
    feed through `preprocessing.prepare_frame` for a demo run. It carries no
    station identity: the synthetic station reference used by the demo config is
    `SYNTHETIC-STATION-0001`, which is obviously not a real gauge.
    """
    spec = spec or SyntheticSeriesSpec()
    index = _timestamps(spec)
    n = spec.n_rows
    rng = np.random.default_rng(spec.random_state)

    hours = np.arange(n, dtype="float64") * spec.interval_hours
    day_of_year = ((index.dayofyear.to_numpy(dtype="float64") - 1.0) / 365.25) * 2.0 * math.pi
    hour_of_day = index.hour.to_numpy(dtype="float64")

    baseflow = (
        spec.base_level
        + spec.annual_amplitude * np.sin(day_of_year - 0.6)
        + 0.4 * np.sin(2.0 * math.pi * hour_of_day / 24.0)
    )

    # Rainfall: seasonal envelope (wet season) times a heavy-tailed noise draw.
    wet_season = 0.55 + 0.45 * np.sin(day_of_year + 1.2)
    exponential = rng.exponential(scale=1.0, size=n)
    pulse = (rng.random(n) < 0.18).astype("float64")
    rain = np.clip(wet_season * spec.rain_peak_mm_per_hour * (0.25 * pulse + 0.75 * exponential), 0.0, None)

    # Rainfall response: decaying accumulation (a simple linear reservoir).
    decay = 0.86
    response = np.zeros(n, dtype="float64")
    accumulator = 0.0
    for i in range(n):
        accumulator = decay * accumulator + rain[i] / 12.0
        response[i] = accumulator
    response /= max(float(response.max()), 1e-9)

    water = baseflow + 3.4 * response + rng.normal(0.0, spec.noise_scale, size=n)
    inflow = np.clip(40.0 + 18.0 * water + rng.normal(0.0, 1.2, size=n), 0.0, None)

    frame = pd.DataFrame(
        {
            "timestamp": index,
            "water_level": np.round(water, 4),
            "inflow": np.round(inflow, 3),
            "rainfall_mm": np.round(rain, 4),
        }
    )
    return frame


def write_synthetic_csv(
    path: str,
    spec: SyntheticSeriesSpec | None = None,
) -> dict[str, Any]:
    """Write a synthetic series to `path` and return its provenance.

    The returned mapping carries `dataset_type="synthetic"`, the file checksum
    and the mandatory disclaimer, so a caller cannot accidentally record the
    file as a real dataset.
    """
    spec = spec or SyntheticSeriesSpec()
    frame = generate_synthetic_series(spec)
    frame.to_csv(path, index=False)
    return {
        "path": path,
        "dataset_reference": f"{SYNTHETIC_REFERENCE_PREFIX}hydrology/{spec.random_state}/{spec.n_rows}rows",
        "dataset_type": DATASET_TYPE_SYNTHETIC,
        "dataset_license": "none — synthetic data has no license because it is not real data",
        "dataset_checksum": file_checksum(path),
        "sampling_interval": f"{spec.interval_hours}h",
        "columns": list(SYNTHETIC_COLUMNS),
        "n_rows": int(len(frame)),
        "disclaimer": SYNTHETIC_DATA_DISCLAIMER,
    }


def synthetic_dataset_spec(config: Any) -> Any:
    """Return a copy of `config.dataset` marked as synthetic and demo-sourced.

    Used by the demo/training entrypoint so the provenance of a demo run is
    declared rather than implied.

    The dataset reference is also forced onto the `synthetic://` scheme when it
    is missing or does not already say "synthetic". Without this, a demo run that
    was pointed at a local file would carry a reference like
    `unrecorded://local-file`, and an audit could not tell from the reference
    alone that the numbers came from a simulator.
    """
    from dataclasses import replace

    existing = config.dataset.reference
    if not existing or not existing.startswith(SYNTHETIC_REFERENCE_PREFIX):
        existing = f"{SYNTHETIC_REFERENCE_PREFIX}hydrology/demo"
    return replace(
        config.dataset,
        dataset_type=DATASET_TYPE_SYNTHETIC,
        reference=existing,
        license=config.dataset.license
        or "none — synthetic data has no license because it is not real data",
        sampling_interval=config.dataset.sampling_interval or "1h",
        station_reference=config.dataset.station_reference or "SYNTHETIC-STATION-0001",
    )


def synthetic_target_spec(config: Any) -> Any:
    """Return a copy of `config.target` with demo units declared.

    Declaring units is required for a runnable demo: a forecast whose units are
    unknown can never be audited. For a real dataset the units must come from the
    dataset supplier, not from here.
    """
    from dataclasses import replace

    units = config.target.units
    if units is None:
        # Both branches carry the same "this is a demo assumption, not a
        # verified unit" framing. A bare placeholder like `demo-units` reads as
        # though the units had been established, which is exactly the wrong
        # impression for a value nobody has verified.
        #
        # For `inflow` no physical unit is invented: choosing m3/s would be a
        # guess about the source, and the generator's own scale is arbitrary, so
        # the honest answer is to say the unit is undetermined.
        units = (
            "m (demo assumption — NOT a datum-verified unit; gauge datum and datum "
            "conversion are UNKNOWN)"
            if config.target.column == "water_level"
            else "UNDETERMINED (demo — no unit assigned; a real dataset's inflow unit "
            "must be supplied by the dataset owner, typically m3/s, along with the "
            "rating curve used to derive it)"
        )
    return replace(config.target, units=units)
