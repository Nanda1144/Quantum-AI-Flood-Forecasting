# `data/` — SYNTHETIC/DEMO datasets

> ## ⚠️ THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.

**Owner:** forecasting module (ForecastingEngine seam) · **Module:** `ai-service`

Every file in this directory was produced by
`app.engines.hydro.synthetic.generate_synthetic_series`, a deterministic
numerical simulator. **No observation, gauge reading, rainfall record, water
level or discharge measurement in this repository came from a real hydrological
source**, because no real dataset is available in this repository.

---

## Contents

| File | Rows | Interval | Generator seed | SHA-256 |
| --- | ---: | --- | ---: | --- |
| `synthetic_hydrology_sample.csv` | 2160 | 1h | `20240101` | `56f4b7c5b4122b5d9b61db256f8d7afcb7e03d4a1cf9e942c013818386e29ac6` |

### Schema

| Column | Unit | Meaning |
| --- | --- | --- |
| `timestamp` | ISO-8601 UTC | Observation instant, hourly, no gaps. |
| `water_level` | m (**demo assumption — NOT datum verified**) | Simulated stage. The datum is fictional. |
| `inflow` | m³/s (**demo assumption**) | Simulated lateral inflow. |
| `rainfall_mm` | mm/h | Simulated rainfall intensity, non-negative. |

The generator's `base_level` and `annual_amplitude` parameters produce a
seasonal signal, and `noise_scale` adds a reproducible perturbation. It is a
*plausible-looking signal*, not a physical water-balance model: there is no
routing, no storage, no catchment, and no unit conversion between the columns.

---

## Using it

```bash
cd ai-service

python -m app.engines.hydro.training \
  --dataset ./app/engines/hydro/data/synthetic_hydrology_sample.csv \
  --dataset-type synthetic
```

`--dataset-type synthetic` is not cosmetic. It drives three separate behaviours:

1. `synthetic_dataset_spec()` forces the dataset reference onto the
   `synthetic://` scheme, so a demo run can never carry a reference that looks
   like a real observation source.
2. Every metric computed from it is labelled
   *"synthetic/demo evaluation only — not a production or research result"*.
3. `ArtifactRecord.production_ready` is forced to `False`.

Omitting the flag makes the run read as `unknown` provenance, which is also safe
but less informative. It never makes a synthetic run look real.

### Regenerating

The file is committed so a reviewer can reproduce the exact numbers without
running anything. To regenerate it byte-for-byte:

```bash
python -m app.engines.hydro.training \
  --write-synthetic ./app/engines/hydro/data/synthetic_hydrology_sample.csv \
  --n-rows 2160 --random-state 20240101
```

Generation is deterministic: the same `random_state` produces an identical
checksum. There is no hidden entropy.

---

## Adding a real dataset

Do **not** put one here without human sign-off. If a real dataset becomes
available, the following must be supplied by a human and recorded in
`HYDRO_DATASET_*` before any output may be described as a result:

- [ ] Source organisation and the exact export or endpoint used
- [ ] Licence, and confirmation that redistribution is permitted
- [ ] Station / gauge identifier and its authoritative reference
- [ ] Sampling interval, timezone, and the datum for the level measurements
- [ ] Missing-data semantics: is a gap a sensor failure, or a real zero?
- [ ] Quality-control rules and who approved them
- [ ] Whether the record is revised after the fact, and how

Until then, `provenance.ProvenanceRecord` leaves every one of those fields
`None` and reports them under `missing_fields()`. That is deliberate: an
unfilled field is a visible question, whereas a plausible default is a silent
lie.

---

## Why synthetic data is here at all

The pipeline needs to be runnable, reviewable and testable by people who do not
have access to a licensed hydrological archive. A committed synthetic sample
means:

- `pytest` exercises the real code path end to end, not a mock;
- a reviewer can reproduce every number in `Evaluation_Report.md`;
- the labelling can be audited, which is the whole point.

The cost is that **no score in this repository says anything about real flood
forecasting.** The synthetic evaluation measures whether the code computes what
it claims to compute. It is not evidence of hydrological skill, and it is
labelled as such in every artifact, report and log line that references it.
