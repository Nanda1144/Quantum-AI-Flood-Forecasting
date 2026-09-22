from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.data import DataImportJob
from app.schemas.data import DatasetResponse

from app.services.data_service import (
    get_all_datasets,
    get_dataset_by_id,
    delete_dataset,
    save_uploaded_dataset,
)

from app.services.validation_service import (
    validate_dataset,
    get_data_quality,
)

from app.services.preprocessing_service import (
    preprocess_dataset,
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/data",
    tags=["Data Management"],
)


# ============================================================
# UPLOAD DATASET
# ============================================================

@router.post("/upload", response_model=DatasetResponse)
def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        dataset = save_uploaded_dataset(db, file)
        return dataset

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset upload failed: {error}",
        ) from error


# ============================================================
# VALIDATE DATASET
# ============================================================

@router.post("/validate/{dataset_id}")
def validate_dataset_api(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    try:
        result = validate_dataset(
            db,
            dataset_id,
        )

        return {
            "message": "Dataset validation completed successfully.",
            "dataset_id": dataset_id,
            "quality_result": {
                "id": result.id,
                "total_rows": result.total_rows,
                "total_columns": result.total_columns,
                "missing_values": result.missing_values,
                "duplicate_rows": result.duplicate_rows,
                "invalid_rows": result.invalid_rows,
                "quality_status": result.quality_status,
                "created_at": result.created_at,
            },
        }

    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset validation failed: {error}",
        ) from error


# ============================================================
# GET DATA QUALITY
# ============================================================

@router.get("/quality/{dataset_id}")
def get_dataset_quality_api(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    result = get_data_quality(
        db,
        dataset_id,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail=(
                "Data quality result not found. "
                "Validate the dataset first."
            ),
        )

    return {
        "dataset_id": dataset_id,
        "quality_result": {
            "id": result.id,
            "total_rows": result.total_rows,
            "total_columns": result.total_columns,
            "missing_values": result.missing_values,
            "duplicate_rows": result.duplicate_rows,
            "invalid_rows": result.invalid_rows,
            "quality_status": result.quality_status,
            "created_at": result.created_at,
        },
    }


# ============================================================
# PREPROCESS DATASET
# ============================================================

@router.post("/preprocess/{dataset_id}")
def preprocess_dataset_api(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    try:
        result = preprocess_dataset(
            db,
            dataset_id,
        )

        return {
            "message": "Dataset preprocessing completed successfully.",
            "result": result,
        }

    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset preprocessing failed: {error}",
        ) from error


# ============================================================
# DATASET PREVIEW
# ============================================================

@router.get("/{dataset_id}/preview")
def preview_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    try:
        dataset = get_dataset_by_id(
            db,
            dataset_id,
        )

        if not dataset:
            raise HTTPException(
                status_code=404,
                detail="Dataset not found",
            )

        from pathlib import Path
        import pandas as pd

        file_path = Path(dataset.file_path)

        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail="Dataset file not found",
            )

        if dataset.file_type.lower() == "csv":
            dataframe = pd.read_csv(file_path)

        elif dataset.file_type.lower() == "json":
            dataframe = pd.read_json(file_path)

        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported dataset file type",
            )

        preview_dataframe = dataframe.head(10)

        preview_dataframe = preview_dataframe.where(
            pd.notna(preview_dataframe),
            None,
        )

        preview_rows = preview_dataframe.to_dict(
            orient="records"
        )

        return {
            "dataset_id": dataset.id,
            "file_name": dataset.file_name,
            "file_type": dataset.file_type,
            "total_rows": len(dataframe),
            "total_columns": len(dataframe.columns),
            "columns": [
                str(column)
                for column in dataframe.columns
            ],
            "preview_rows": preview_rows,
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset preview failed: {error}",
        ) from error


# ============================================================
# IMPORT HISTORY
# ============================================================

@router.get("/import-history")
def get_import_history(
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(DataImportJob)
        .order_by(DataImportJob.started_at.desc())
        .all()
    )

    return [
        {
            "id": job.id,
            "dataset_id": job.dataset_id,
            "file_name": job.file_name,
            "file_type": job.file_type,
            "status": job.status,
            "rows_imported": job.rows_imported,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message,
        }
        for job in jobs
    ]


# ============================================================
# LIST ALL DATASETS
# ============================================================

@router.get("/", response_model=list[DatasetResponse])
def list_datasets(
    db: Session = Depends(get_db),
):
    datasets = get_all_datasets(db)

    response = []

    for dataset in datasets:

        quality_result = get_data_quality(
            db,
            dataset.id,
        )

        dataset_data = {
            "id": dataset.id,
            "name": dataset.name,
            "file_name": dataset.file_name,
            "file_type": dataset.file_type,
            "file_path": dataset.file_path,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "status": dataset.status,

            # Quality from validation result
            "quality": (
                quality_result.quality_status
                if quality_result
                else None
            ),

            "created_at": dataset.created_at,
        }

        response.append(dataset_data)

    return response


# ============================================================
# GET DATASET BY ID
# ============================================================

@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    dataset = get_dataset_by_id(
        db,
        dataset_id,
    )

    if not dataset:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found",
        )

    return dataset


# ============================================================
# DELETE DATASET
# ============================================================

@router.delete("/{dataset_id}")
def remove_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    dataset = delete_dataset(
        db,
        dataset_id,
    )

    if not dataset:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found",
        )

    return {
        "message": "Dataset deleted successfully",
        "dataset_id": dataset_id,
    }