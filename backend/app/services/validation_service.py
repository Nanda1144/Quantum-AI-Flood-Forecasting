
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.data import Dataset, DataQualityResult, DataValidationLog


# ---------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------

def load_dataset(dataset: Dataset) -> pd.DataFrame:
    """
    Load a dataset from CSV or JSON.
    """

    file_path = Path(dataset.file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {file_path}"
        )

    if dataset.file_type.lower() == "csv":
        return pd.read_csv(file_path)

    if dataset.file_type.lower() == "json":
        return pd.read_json(file_path)

    raise ValueError(
        f"Unsupported file type: {dataset.file_type}"
    )


# ---------------------------------------------------------
# VALIDATION LOGGING
# ---------------------------------------------------------

def save_validation_log(
    db: Session,
    dataset_id: int,
    validation_type: str,
    status: str,
    message: str,
):
    log = DataValidationLog(
        dataset_id=dataset_id,
        validation_type=validation_type,
        status=status,
        message=message,
    )

    db.add(log)


# ---------------------------------------------------------
# SCHEMA VALIDATION
# ---------------------------------------------------------

def validate_schema(dataframe: pd.DataFrame):
    """
    Validate basic dataset schema.
    """

    errors = []

    if dataframe.empty:
        errors.append(
            "Dataset contains no rows."
        )

    if len(dataframe.columns) == 0:
        errors.append(
            "Dataset contains no columns."
        )

    if dataframe.columns.duplicated().any():
        duplicated_columns = dataframe.columns[
            dataframe.columns.duplicated()
        ].tolist()

        errors.append(
            f"Duplicate column names found: {duplicated_columns}"
        )

    empty_columns = dataframe.columns[
        dataframe.isnull().all()
    ].tolist()

    if empty_columns:
        errors.append(
            f"Completely empty columns found: {empty_columns}"
        )

    return errors


# ---------------------------------------------------------
# TIMESTAMP NORMALIZATION
# ---------------------------------------------------------

def normalize_timestamps(dataframe: pd.DataFrame):
    """
    Detect timestamp/date/time columns and normalize
    valid values to pandas datetime values.

    Invalid non-empty values become NaT and are reported.
    """

    timestamp_columns = []

    for column in dataframe.columns:

        column_name = str(column).lower().strip()

        if any(
            keyword in column_name
            for keyword in [
                "timestamp",
                "datetime",
                "date",
                "time",
            ]
        ):
            timestamp_columns.append(column)

    results = []

    for column in timestamp_columns:

        original = dataframe[column]

        converted = pd.to_datetime(
            original,
            errors="coerce",
        )

        invalid_count = int(
            original.notna().sum()
            - converted.notna().sum()
        )

        dataframe[column] = converted

        results.append(
            {
                "column": column,
                "invalid_values": invalid_count,
                "normalized": True,
            }
        )

    return results


def validate_timestamps(dataframe: pd.DataFrame):
    """
    Validate timestamp/date/time columns.
    """

    timestamp_results = normalize_timestamps(
        dataframe
    )

    errors = []

    for result in timestamp_results:

        if result["invalid_values"] > 0:

            errors.append(
                f"Column '{result['column']}' contains "
                f"{result['invalid_values']} invalid "
                f"date/time values."
            )

    return errors


# ---------------------------------------------------------
# UNIT / MEASUREMENT DETECTION
# ---------------------------------------------------------

MEASUREMENT_KEYWORDS = [
    "rainfall",
    "rain",
    "water_level",
    "waterlevel",
    "river_level",
    "riverlevel",
    "temperature",
    "humidity",
    "pressure",
    "elevation",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "speed",
    "flow",
    "depth",
]


def detect_measurement_columns(dataframe: pd.DataFrame):
    """
    Detect common flood/environmental measurement columns.
    """

    columns = []

    for column in dataframe.columns:

        column_name = str(column).lower().strip()

        if any(
            keyword in column_name
            for keyword in MEASUREMENT_KEYWORDS
        ):
            columns.append(column)

    return columns


# ---------------------------------------------------------
# NUMERIC NORMALIZATION
# ---------------------------------------------------------

def normalize_units(dataframe: pd.DataFrame):
    """
    Normalize recognized measurement columns to numeric values.

    This does not silently convert physical units such as
    inches to millimeters or feet to meters.

    It only ensures that recognized measurement values are
    represented numerically.
    """

    measurement_columns = detect_measurement_columns(
        dataframe
    )

    results = []

    for column in measurement_columns:

        original = dataframe[column]

        numeric = pd.to_numeric(
            original,
            errors="coerce",
        )

        invalid_count = int(
            original.notna().sum()
            - numeric.notna().sum()
        )

        dataframe[column] = numeric

        results.append(
            {
                "column": column,
                "invalid_values": invalid_count,
                "normalized": True,
            }
        )

    return results


def validate_numeric_columns(dataframe: pd.DataFrame):
    """
    Validate environmental/flood measurement columns.
    """

    unit_results = normalize_units(
        dataframe
    )

    errors = []

    for result in unit_results:

        if result["invalid_values"] > 0:

            errors.append(
                f"Column '{result['column']}' contains "
                f"{result['invalid_values']} invalid "
                f"numeric values."
            )

    return errors


# ---------------------------------------------------------
# INVALID ROW DETECTION
# ---------------------------------------------------------

def count_invalid_rows(dataframe: pd.DataFrame):
    """
    Count rows that are completely empty or contain
    invalid recognized measurement values.
    """

    invalid_mask = dataframe.isnull().all(
        axis=1
    )

    measurement_columns = detect_measurement_columns(
        dataframe
    )

    for column in measurement_columns:

        numeric = pd.to_numeric(
            dataframe[column],
            errors="coerce",
        )

        invalid_mask = invalid_mask | (
            dataframe[column].notna()
            & numeric.isna()
        )

    return int(
        invalid_mask.sum()
    )


# ---------------------------------------------------------
# COMPLETE DATASET VALIDATION
# ---------------------------------------------------------

def validate_dataset(
    db: Session,
    dataset_id: int,
):
    """
    Run complete dataset validation.

    Validation includes:

    1. Schema
    2. Missing values
    3. Duplicate rows
    4. Timestamp normalization
    5. Numeric/unit validation
    6. Invalid rows
    7. Overall quality status
    """

    dataset = (
        db.query(Dataset)
        .filter(
            Dataset.id == dataset_id
        )
        .first()
    )

    if not dataset:

        raise ValueError(
            f"Dataset with id {dataset_id} not found."
        )

    dataframe = load_dataset(
        dataset
    )

    total_rows = len(
        dataframe
    )

    total_columns = len(
        dataframe.columns
    )

    # -----------------------------------------------------
    # MISSING VALUES
    # -----------------------------------------------------

    missing_values = int(
        dataframe.isnull()
        .sum()
        .sum()
    )

    # -----------------------------------------------------
    # DUPLICATE ROWS
    # -----------------------------------------------------

    duplicate_rows = int(
        dataframe.duplicated()
        .sum()
    )

    # -----------------------------------------------------
    # SCHEMA
    # -----------------------------------------------------

    schema_errors = validate_schema(
        dataframe
    )

    if schema_errors:

        for error in schema_errors:

            save_validation_log(
                db,
                dataset_id,
                "schema",
                "failed",
                error,
            )

    else:

        save_validation_log(
            db,
            dataset_id,
            "schema",
            "passed",
            "Schema validation passed.",
        )

    # -----------------------------------------------------
    # TIMESTAMP
    # -----------------------------------------------------

    timestamp_errors = validate_timestamps(
        dataframe
    )

    if timestamp_errors:

        for error in timestamp_errors:

            save_validation_log(
                db,
                dataset_id,
                "timestamp",
                "failed",
                error,
            )

    else:

        save_validation_log(
            db,
            dataset_id,
            "timestamp",
            "passed",
            "Timestamp validation passed.",
        )

    # -----------------------------------------------------
    # NUMERIC / UNIT
    # -----------------------------------------------------

    numeric_errors = validate_numeric_columns(
        dataframe
    )

    if numeric_errors:

        for error in numeric_errors:

            save_validation_log(
                db,
                dataset_id,
                "numeric",
                "failed",
                error,
            )

    else:

        save_validation_log(
            db,
            dataset_id,
            "numeric",
            "passed",
            "Numeric/unit validation passed.",
        )

    # -----------------------------------------------------
    # INVALID ROWS
    # -----------------------------------------------------

    invalid_rows = count_invalid_rows(
        dataframe
    )

    # -----------------------------------------------------
    # QUALITY STATUS
    # -----------------------------------------------------

    has_errors = (
        missing_values > 0
        or duplicate_rows > 0
        or invalid_rows > 0
        or bool(schema_errors)
        or bool(timestamp_errors)
        or bool(numeric_errors)
    )

    if not has_errors:

        quality_status = "good"

    elif (
        invalid_rows > 0
        or schema_errors
        or timestamp_errors
        or numeric_errors
    ):

        quality_status = "warning"

    else:

        quality_status = "warning"

    # -----------------------------------------------------
    # MISSING VALUE LOG
    # -----------------------------------------------------

    if missing_values > 0:

        save_validation_log(
            db,
            dataset_id,
            "missing_values",
            "warning",
            f"{missing_values} missing values found.",
        )

    else:

        save_validation_log(
            db,
            dataset_id,
            "missing_values",
            "passed",
            "No missing values found.",
        )

    # -----------------------------------------------------
    # DUPLICATE LOG
    # -----------------------------------------------------

    if duplicate_rows > 0:

        save_validation_log(
            db,
            dataset_id,
            "duplicates",
            "warning",
            f"{duplicate_rows} duplicate rows found.",
        )

    else:

        save_validation_log(
            db,
            dataset_id,
            "duplicates",
            "passed",
            "No duplicate rows found.",
        )

    # -----------------------------------------------------
    # INVALID ROW LOG
    # -----------------------------------------------------

    if invalid_rows > 0:

        save_validation_log(
            db,
            dataset_id,
            "invalid_rows",
            "warning",
            f"{invalid_rows} invalid rows found.",
        )

    else:

        save_validation_log(
            db,
            dataset_id,
            "invalid_rows",
            "passed",
            "No invalid rows found.",
        )

    # -----------------------------------------------------
    # SAVE QUALITY RESULT
    # -----------------------------------------------------

    quality_result = DataQualityResult(
        dataset_id=dataset_id,
        total_rows=total_rows,
        total_columns=total_columns,
        missing_values=missing_values,
        duplicate_rows=duplicate_rows,
        invalid_rows=invalid_rows,
        quality_status=quality_status,
    )

    db.add(
        quality_result
    )

    # -----------------------------------------------------
    # UPDATE DATASET STATUS
    # -----------------------------------------------------

    dataset.status = quality_status

    db.commit()

    db.refresh(
        quality_result
    )

    return quality_result


# ---------------------------------------------------------
# GET LATEST DATA QUALITY
# ---------------------------------------------------------

def get_data_quality(
    db: Session,
    dataset_id: int,
):
    """
    Get latest data-quality result.
    """

    result = (
        db.query(DataQualityResult)
        .filter(
            DataQualityResult.dataset_id
            == dataset_id
        )
        .order_by(
            DataQualityResult.created_at.desc()
        )
        .first()
    )

    return result

