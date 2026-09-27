# AI Flow

**Owner:** Navya
**Diagram source:** `ai-flow.mmd`
**Status legend:** see [`README.md`](README.md)

---

## 1. The path

```
input -> preprocessing -> candidate models -> model comparison
      -> selected forecast -> uncertainty -> flood risk -> optimization handoff
```

---

## 2. Candidate models

Taken from the research in `01_Flood_Forecasting/Research/02_Flood_Forecasting_Model_Comparison.md`.
The research describes seven candidate families; **the executed registry contains only two**,
because it contains only models that can actually run.

| Model | Research role | Implementation status |
|---|---|---|
| Linear / Ridge regression | Interpretable baseline | `[MY IMPLEMENTATION]` — executable, and the model selected in the realized run |
| Random Forest | Non-linear ensemble baseline | `[NOT CURRENTLY AVAILABLE]` — research candidate, not in the executed registry |
| XGBoost | Strong tabular baseline | `[MY IMPLEMENTATION]` — optional dependency; **skipped** when absent, and the skip is reported |
| LSTM | Sequence learning | `[NOT CURRENTLY AVAILABLE]` — **not implemented, future work** |
| GRU | Sequence learning | `[NOT CURRENTLY AVAILABLE]` — **not implemented, future work** |
| Quantum ML | Experimental component | `[NOT CURRENTLY AVAILABLE]` — **research only, not implemented** |

> No LSTM, GRU, Random Forest, or QML model has been trained by this work. No performance of
> any kind is claimed for them. They appear in `models.py` only as labelled future entries.

---

## 3. Model comparison and selection — the discipline

This is the part of the ML flow most easily done dishonestly, so it is stated precisely and
enforced by tests.

| Rule | Enforcement |
|---|---|
| Split chronologically, never shuffle | `evaluation.py`; no random seed exists in the split path |
| Rank using the **validation split only** | selection reads validation metrics only |
| Score the **test split exactly once**, with the already-selected model | test metrics are computed after selection is fixed |
| Test results must never influence ranking | ranking function has no access to test metrics |
| Metrics computed from real predictions | no hard-coded metric values exist |
| Report the split with every metric | `EvaluationReport.metric_label` is split-aware |
| Refuse to present a non-held-out metric as a result | `areMetricsPresentableAsResult`, `assertMetricsMayBeReported` |

A validation-split score is **optimistic by construction** — it is the split the model was
chosen on. The implementation labels it as a selection statistic and refuses to render it as
an outcome.

---

## 4. Measured results

### 4.1 What was actually run

A single end-to-end run of the Navya engine over the **synthetic** 8,760-row dataset:

- Chronological 70 / 15 / 15 split
- 23 causal features
- Ridge selected on the validation split
- XGBoost skipped — optional dependency not installed
- Artifact checksum `585fced336c9428d323316d5f741c4f6113d1e2426d9575d838945d66d57c78f`
- `is_complete: True`, `production_ready: False`

### 4.2 The numbers

> ### SYNTHETIC / DEMO EVALUATION ONLY
> ### NOT A PRODUCTION OR RESEARCH RESULT

**Validation split** — used for model selection, therefore optimistic by construction:

| MAE | RMSE | R² |
|---|---|---|
| 0.1191 | 0.1613 | 0.7884 |

**Held-out test split** — scored exactly once, never used for ranking:

| MAE | RMSE | R² | Peak abs. error | Bias | Samples |
|---|---|---|---|---|---|
| 0.2779 | 0.3645 | 0.6359 | 1.564719 | −0.062558 | 1,315 |

### 4.3 What these numbers mean, and do not mean

They mean: the pipeline runs end to end, the split discipline holds, the metrics are computed
rather than asserted, and the artifact is checksummed.

They do **not** mean the model forecasts floods. They were produced on procedurally generated
data whose statistical structure is whatever the generator was configured to emit. The gap
between validation MAE 0.1191 and test MAE 0.2779 is itself evidence that these figures
describe the synthetic generator and not a general capability.

**No metric anywhere in this repository is a real-world hydrological result.**

---

## 5. Uncertainty

Residual sigma is carried on the forecast record as an uncertainty signal.

It is deliberately **not** converted into a confidence interval, a prediction band, or a
calibrated probability. Doing so would require a distributional assumption and a calibration
step that have not been performed on real data. The field reports dispersion and nothing more.

---

## 6. Flood risk

- Bands LOW / MEDIUM / HIGH / CRITICAL, **configurable**, never hard-coded
- The team's `ReferenceEngine` placeholder of `8.0` is deliberately not reused
- **Official flood stage values are `[NOT CURRENTLY AVAILABLE]`** — no official source has been
  supplied, so every threshold is marked `pending`
- A pending threshold is never rendered as a bare number. The UI renders the value together
  with its pending status and its source, because a threshold without provenance is a guess
  wearing a decimal point

---

## 7. Downstream handoff

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

Navya provides the forecast record, provenance, metric split, threshold policy, and residual
sigma. The team's optimization consumes `forecast_id`. Carrying the remaining fields is a
team-owned schema change, documented rather than performed.

See [`../API_Integration/`](../API_Integration/) and
[`../INTEGRATION_MATRIX.md`](../INTEGRATION_MATRIX.md).
