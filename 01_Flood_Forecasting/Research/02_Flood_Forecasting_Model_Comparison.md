# Flood Forecasting Model Comparison

## Project

Quantum-AI Flood Intelligence & Sensor Placement Platform

## Use Case

UC-067 — Flood forecasting and disaster-response sensor placement

## Prepared By

K. Navya Sree

## Responsibility

Flood/Inflow Forecasting & Overall Architecture

---

# 1. Objective

The objective of the flood forecasting component is to predict future river water levels and/or inflow using historical hydrological and meteorological data.

The forecasting output will later be used by the flood-risk and sensor-placement components of the UC-067 platform.

The final forecasting model will be selected only after understanding the available dataset, target variable, prediction horizon, data quality and evaluation requirements.

---

# 2. Candidate Models

The main candidate models considered for flood/inflow forecasting are:

1. Linear Regression
2. Random Forest
3. XGBoost
4. LSTM
5. GRU
6. Quantum Machine Learning (QML)

---

# 3. Linear Regression

## What it is

Linear Regression is a classical supervised learning algorithm that models the relationship between input features and a continuous target variable.

## Possible use

It can be used as a baseline model for predicting:

- Future water level
- River inflow
- Other continuous hydrological variables

## Advantages

- Simple to implement
- Fast training
- Fast inference
- Easy to interpret
- Useful as a baseline

## Limitations

- Assumes a relatively simple relationship between features and target
- May not capture complex nonlinear hydrological patterns
- May not adequately represent long-term temporal dependencies

## Role in UC-067

Linear Regression should primarily be considered as a baseline against which more advanced models can be compared.

---

# 4. Random Forest

## What it is

Random Forest is an ensemble learning method that combines multiple decision trees to produce predictions.

## Possible use

It can use features such as:

- Rainfall
- Previous water levels
- Previous inflow
- Temperature
- Other available environmental variables

to predict future water level or inflow.

## Advantages

- Handles nonlinear relationships
- Works well with tabular data
- Less sensitive to feature scaling
- Provides feature-importance information
- Suitable for an initial classical ML implementation

## Limitations

- Does not naturally model sequential dependencies like recurrent neural networks
- Model size can increase with many trees
- Temporal features may need to be explicitly engineered

## Role in UC-067

Random Forest can serve as a classical nonlinear baseline for comparison with other forecasting models.

---

# 5. XGBoost

## What it is

XGBoost is a gradient-boosting machine learning algorithm based on decision trees.

## Possible use

XGBoost can be used for flood/inflow prediction using engineered time-series and environmental features.

Example features may include:

- Recent rainfall
- Lagged rainfall
- Previous water level
- Previous inflow
- Rolling rainfall statistics
- Seasonal information

The actual features will depend on the available dataset.

## Advantages

- Strong performance on structured/tabular data
- Handles nonlinear relationships
- Supports feature importance analysis
- Efficient training
- Suitable for engineered time-series features

## Limitations

- Requires appropriate feature engineering for temporal relationships
- Hyperparameter tuning may be required
- Does not inherently model sequences like LSTM/GRU

## Role in UC-067

XGBoost is an important classical ML candidate and can be compared against simpler models and deep-learning approaches.

---

# 6. LSTM

## What it is

Long Short-Term Memory (LSTM) is a type of recurrent neural network designed to learn patterns from sequential data.

## Possible use

Flood forecasting is naturally a time-series problem.

An LSTM can learn relationships between previous observations and future values.

Example:

Historical observations

→ Rainfall at previous time steps

→ Previous water levels

→ Previous inflows

→ LSTM

→ Future water level/inflow prediction

## Advantages

- Designed for sequential data
- Can learn temporal dependencies
- Suitable for time-series forecasting
- Can model complex nonlinear relationships

## Limitations

- Requires more data than simple models in many cases
- Training can be computationally expensive
- More difficult to interpret
- Requires careful preprocessing and sequence construction

## Role in UC-067

LSTM is a strong candidate when the available dataset contains sufficient historical time-series observations.

---

# 7. GRU

## What it is

Gated Recurrent Unit (GRU) is a recurrent neural network architecture designed for sequence learning.

It is related to LSTM but uses a simpler gating structure.

## Possible use

GRU can be used to forecast future water levels or inflow from sequences of historical observations.

## Advantages

- Suitable for sequential data
- Can capture temporal dependencies
- Generally has a simpler architecture than LSTM
- Can require fewer parameters than comparable LSTM architectures

## Limitations

- Still requires sequence-based preprocessing
- Requires sufficient training data
- Less interpretable than simple classical models
- Performance depends on data quality and hyperparameter configuration

## Role in UC-067

GRU can be evaluated as an alternative recurrent neural-network approach alongside LSTM.

---

# 8. Quantum Machine Learning

## What it is

Quantum Machine Learning (QML) combines machine-learning methods with quantum computing techniques.

For UC-067, QML is part of the proposed approach for improving flood/inflow forecasting.

## Possible role

QML can be investigated as an experimental forecasting approach after establishing reliable classical ML baselines.

A possible research flow is:

Classical preprocessing

→ Feature selection

→ Classical baseline

→ QML model

→ Performance comparison

## Advantages

- Aligns with the quantum-AI objective of UC-067
- Provides an opportunity to investigate quantum-enhanced learning methods
- Can be evaluated experimentally against classical models

## Limitations

- Requires appropriate quantum-compatible model design
- Current quantum hardware has practical limitations
- Dataset size and feature dimensions may need to be reduced
- Quantum model performance must be experimentally validated
- Classical baselines are necessary for meaningful comparison

## Role in UC-067

QML should be treated as an experimental component rather than assuming in advance that it will outperform classical models.

---

# 9. Preliminary Comparison

| Model | Data Type | Nonlinear Patterns | Temporal Dependency | Training Complexity | Interpretability | Initial Role |
|------|-----------|--------------------|----------------------|--------------------|------------------|--------------|
| Linear Regression | Tabular | Limited | Requires engineered features | Low | High | Baseline |
| Random Forest | Tabular | Yes | Requires engineered features | Medium | Medium | Classical baseline |
| XGBoost | Tabular | Yes | Requires engineered features | Medium | Medium | Strong classical candidate |
| LSTM | Sequential | Yes | Yes | High | Low | Deep-learning candidate |
| GRU | Sequential | Yes | Yes | Medium-High | Low | Deep-learning candidate |
| QML | Depends on model | Potentially | Depends on architecture | Experimental | Depends on model | Quantum-AI experiment |

---

# 10. Model Selection Criteria

The final forecasting model should be selected using measurable criteria.

Important criteria include:

## 10.1 Prediction Accuracy

The model should produce accurate forecasts for the selected target.

Possible regression metrics include:

- MAE
- RMSE
- R²

The exact metrics will be finalized according to the prediction task.

## 10.2 Training Time

The time required to train the model should be recorded.

## 10.3 Inference Time

The time required to generate a forecast should be measured because disaster-response applications may require timely predictions.

## 10.4 Data Requirements

The model should be evaluated based on the amount and quality of historical data required.

## 10.5 Explainability

The ability to understand important features and model behaviour is relevant for operational decision-support systems.

## 10.6 Deployment Complexity

The model should be practical to integrate into the project's backend and forecasting pipeline.

## 10.7 Hardware Requirements

The computational requirements should be documented for training and deployment.

---

# 11. Proposed Evaluation Workflow

The model comparison should follow a common evaluation procedure.

```text
Historical Dataset
        ↓
Data Cleaning
        ↓
Feature Engineering
        ↓
Train / Validation / Test Split
        ↓
Linear Regression Baseline
        ↓
Random Forest
        ↓
XGBoost
        ↓
LSTM / GRU
        ↓
QML Experiment
        ↓
Metric Comparison
        ↓
Final Model Selection

12. Important Dependency

Model selection cannot be finalized before inspecting the actual historical dataset.

The following information must be confirmed:

Available columns
Timestamp format
River/location information
Water-level measurements
Inflow/discharge measurements
Rainfall measurements
Missing values
Sampling frequency
Number of observations
Available prediction horizon

Therefore, the current model list is a research-stage candidate list.

13. Connection to Sensor Placement

The forecasting component provides information that can support the sensor-placement component.

Conceptually:

Historical Data
      ↓
Flood / Inflow Forecast
      ↓
Flood Risk Estimation
      ↓
High-Risk Geographic Areas
      ↓
Sensor Placement Optimization
      ↓
Classical Optimization vs Quantum Optimization

14. Current Research Status
Completed
Flood forecasting basics research
Candidate forecasting model identification
Preliminary model comparison framework
Pending
Actual dataset inspection
Target-variable selection
Feature selection
Prediction horizon definition
Baseline implementation
Model training
Evaluation
Final forecasting model selection

15. Conclusion

UC-067 requires a forecasting component capable of producing useful information about future flood or inflow conditions.

Classical models such as Linear Regression, Random Forest and XGBoost provide important baselines, while LSTM and GRU provide sequence-learning approaches.

Quantum Machine Learning can be investigated as an experimental component of the quantum-AI approach.

The final choice should be based on actual dataset characteristics and measured experimental performance rather than selecting a model in advance.
