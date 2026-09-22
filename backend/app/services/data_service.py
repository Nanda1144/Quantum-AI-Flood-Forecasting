from pathlib import Path
from datetime import datetime

import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.data import Dataset, DataImportJob


UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_all_datasets(db: Session):
    return db.query(Dataset).order_by(Dataset.created_at.desc()).all()


def get_dataset_by_id(db: Session, dataset_id: int):
    return db.query(Dataset).filter(Dataset.id == dataset_id).first()


def delete_dataset(db: Session, dataset_id: int):
    dataset = get_dataset_by_id(db, dataset_id)

    if not dataset:
        return None

    db.delete(dataset)
    db.commit()

    file_path = Path(dataset.file_path)

    if file_path.exists():
        file_path.unlink()

    return dataset


def save_uploaded_dataset(db: Session, file: UploadFile):
    file_name = file.filename or ""

    if not file_name.lower().endswith((".csv", ".json")):
        raise ValueError("Only CSV and JSON files are supported.")

    file_path = UPLOAD_DIR / file_name

    # ---------------------------------------------------------
    # CREATE IMPORT HISTORY RECORD
    # ---------------------------------------------------------

    file_type = Path(file_name).suffix.lower().replace(".", "")

    import_job = DataImportJob(
        file_name=file_name,
        file_type=file_type,
        status="started",
        rows_imported=0,
    )

    db.add(import_job)
    db.commit()
    db.refresh(import_job)

    try:
        # -----------------------------------------------------
        # SAVE FILE
        # -----------------------------------------------------

        with open(file_path, "wb") as output_file:
            output_file.write(file.file.read())

        # -----------------------------------------------------
        # READ DATASET
        # -----------------------------------------------------

        if file_name.lower().endswith(".csv"):
            dataframe = pd.read_csv(file_path)
            file_type = "csv"

        else:
            dataframe = pd.read_json(file_path)
            file_type = "json"

        # -----------------------------------------------------
        # CREATE DATASET
        # -----------------------------------------------------

        dataset = Dataset(
            name=Path(file_name).stem,
            file_name=file_name,
            file_type=file_type,
            file_path=str(file_path),
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            status="uploaded",
        )

        db.add(dataset)
        db.commit()
        db.refresh(dataset)

        # -----------------------------------------------------
        # UPDATE IMPORT HISTORY
        # -----------------------------------------------------

        import_job.dataset_id = dataset.id
        import_job.file_type = file_type
        import_job.status = "completed"
        import_job.rows_imported = len(dataframe)
        import_job.completed_at = datetime.utcnow()
        import_job.error_message = None

        db.commit()
        db.refresh(import_job)

        return dataset

    except Exception as error:

        # -----------------------------------------------------
        # UPDATE FAILED IMPORT
        # -----------------------------------------------------

        import_job.status = "failed"
        import_job.completed_at = datetime.utcnow()
        import_job.error_message = str(error)

        db.commit()

        if file_path.exists():
            file_path.unlink()

        raise ValueError(f"Unable to import dataset: {error}") from error