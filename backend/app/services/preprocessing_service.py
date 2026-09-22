from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.data import Dataset
from app.services.validation_service import (
    detect_measurement_columns,
)


# ---------------------------------------------------------
# CLEANED DATASET DIRECTORY
# ---------------------------------------------------------

CLEANED_DIR = Path("data/cleaned")
CLEANED_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# LOAD ORIGINAL DATASET
# ---------------------------------------------------------

def load_original_dataset(dataset: Dataset) -> pd.DataFrame:
    """
    Load the original CSV or JSON dataset.
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
# TIMESTAMP NORMALIZATION
# ---------------------------------------------------------

def preprocess_timestamps(dataframe: pd.DataFrame):
    """
    Normalize detected date/time columns.

    Invalid values become missing values.
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

    normalized_columns = []

    for column in timestamp_columns:

        dataframe[column] = pd.to_datetime(
            dataframe[column],
            errors="coerce",
        )

        normalized_columns.append(
            str(column)
        )

    return normalized_columns


# ---------------------------------------------------------
# NUMERIC NORMALIZATION
# ---------------------------------------------------------

def preprocess_measurements(dataframe: pd.DataFrame):
    """
    Convert recognized environmental/flood measurement
    columns into numeric values.

    Invalid values become missing values.
    """

    measurement_columns = detect_measurement_columns(
        dataframe
    )

    normalized_columns = []

    for column in measurement_columns:

        dataframe[column] = pd.to_numeric(
            dataframe[column],
            errors="coerce",
        )

        normalized_columns.append(
            str(column)
        )

    return normalized_columns


# ---------------------------------------------------------
# MISSING VALUE HANDLING
# ---------------------------------------------------------

def handle_missing_values(dataframe: pd.DataFrame):
    """
    Handle missing values.

    Numeric columns use median values.
    Text columns use the most frequent value.

    Completely empty columns are removed.
    """

    # Remove completely empty columns
    dataframe.dropna(
        axis=1,
        how="all",
        inplace=True,
    )

    numeric_columns = dataframe.select_dtypes(
        include=["number"]
    ).columns

    for column in numeric_columns:

        if dataframe[column].isna().any():

            median_value = dataframe[column].median()

            if pd.notna(median_value):

                dataframe[column] = (
                    dataframe[column].fillna(
                        median_value
                    )
                )

    text_columns = dataframe.select_dtypes(
        include=["object"]
    ).columns

    for column in text_columns:

        if dataframe[column].isna().any():

            mode_values = dataframe[column].mode()

            if not mode_values.empty:

                dataframe[column] = (
                    dataframe[column].fillna(
                        mode_values.iloc[0]
                    )
                )

    return dataframe


# ---------------------------------------------------------
# DUPLICATE HANDLING
# ---------------------------------------------------------

def remove_duplicate_rows(dataframe: pd.DataFrame):
    """
    Remove completely duplicated rows.
    """

    before_count = len(dataframe)

    dataframe.drop_duplicates(
        inplace=True
    )

    after_count = len(dataframe)

    return before_count - after_count


# ---------------------------------------------------------
# INVALID ROW HANDLING
# ---------------------------------------------------------

def remove_invalid_measurement_rows(
    dataframe: pd.DataFrame,
):
    """
    Remove rows containing invalid values in recognized
    measurement columns.

    Values that could not be converted to numeric become
    NaN and are removed here.
    """

    measurement_columns = detect_measurement_columns(
        dataframe
    )

    if not measurement_columns:
        return 0

    before_count = len(dataframe)

    dataframe.dropna(
        subset=measurement_columns,
        how="any",
        inplace=True,
    )

    after_count = len(dataframe)

    return before_count - after_count


# ---------------------------------------------------------
# SAVE CLEANED DATASET
# ---------------------------------------------------------

def save_cleaned_dataset(
    dataframe: pd.DataFrame,
    dataset: Dataset,
):
    """
    Save the cleaned dataset without modifying the
    original uploaded file.
    """

    original_name = Path(
        dataset.file_name
    ).stem

    if dataset.file_type.lower() == "csv":

        cleaned_path = (
            CLEANED_DIR
            / f"{original_name}_cleaned.csv"
        )

        dataframe.to_csv(
            cleaned_path,
            index=False,
        )

    elif dataset.file_type.lower() == "json":

        cleaned_path = (
            CLEANED_DIR
            / f"{original_name}_cleaned.json"
        )

        dataframe.to_json(
            cleaned_path,
            orient="records",
            date_format="iso",
        )

    else:

        raise ValueError(
            f"Unsupported file type: {dataset.file_type}"
        )

    return cleaned_path


# ---------------------------------------------------------
# COMPLETE PREPROCESSING
# ---------------------------------------------------------

def preprocess_dataset(
    db: Session,
    dataset_id: int,
):
    """
    Create a cleaned and normalized copy of a dataset.

    The original uploaded dataset is never modified.
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

    dataframe = load_original_dataset(
        dataset
    )

    original_rows = len(dataframe)

    # 1. Normalize timestamps
    normalized_timestamp_columns = (
        preprocess_timestamps(
            dataframe
        )
    )

    # 2. Normalize measurement columns
    normalized_measurement_columns = (
        preprocess_measurements(
            dataframe
        )
    )

    # 3. Remove duplicate rows
    duplicates_removed = (
        remove_duplicate_rows(
            dataframe
        )
    )

    # 4. Remove invalid measurement rows
    invalid_rows_removed = (
        remove_invalid_measurement_rows(
            dataframe
        )
    )

    # 5. Fill remaining missing values
    handle_missing_values(
        dataframe
    )

    # 6. Save cleaned copy
    cleaned_path = save_cleaned_dataset(
        dataframe,
        dataset,
    )

    cleaned_rows = len(dataframe)

    return {
        "dataset_id": dataset_id,
        "original_file": dataset.file_name,
        "cleaned_file": cleaned_path.name,
        "cleaned_file_path": str(cleaned_path),
        "original_rows": original_rows,
        "cleaned_rows": cleaned_rows,
        "duplicates_removed": duplicates_removed,
        "invalid_rows_removed": invalid_rows_removed,
        "normalized_timestamp_columns": (
            normalized_timestamp_columns
        ),
        "normalized_measurement_columns": (
            normalized_measurement_columns
        ),
        "status": "completed",
    }