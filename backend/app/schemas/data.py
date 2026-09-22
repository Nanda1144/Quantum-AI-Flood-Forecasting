from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DatasetResponse(BaseModel):
    id: int
    name: str
    file_name: str
    file_type: str
    file_path: str
    row_count: int
    column_count: int
    status: str
    quality: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)