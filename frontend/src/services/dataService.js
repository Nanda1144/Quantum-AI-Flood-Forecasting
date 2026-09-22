const API_BASE_URL = "http://127.0.0.1:8000/api/data";

// ============================================================
// UPLOAD DATASET
// ============================================================

export async function uploadDataset(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Dataset upload failed");
  }

  return response.json();
}


// ============================================================
// GET ALL DATASETS
// ============================================================

export async function getDatasets() {
  const response = await fetch(`${API_BASE_URL}/`);

  if (!response.ok) {
    throw new Error("Failed to fetch datasets");
  }

  return response.json();
}


// ============================================================
// GET DATASET BY ID
// ============================================================

export async function getDataset(datasetId) {
  const response = await fetch(`${API_BASE_URL}/${datasetId}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
      error.detail || "Failed to fetch dataset"
    );
  }

  return response.json();
}


// ============================================================
// DATASET PREVIEW
// ============================================================

export async function previewDataset(datasetId) {
  const response = await fetch(
    `${API_BASE_URL}/${datasetId}/preview`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
      error.detail || "Failed to load dataset preview"
    );
  }

  return response.json();
}


// ============================================================
// DELETE DATASET
// ============================================================

export async function deleteDataset(datasetId) {
  const response = await fetch(
    `${API_BASE_URL}/${datasetId}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
      error.detail || "Failed to delete dataset"
    );
  }

  return response.json();
}


// ============================================================
// VALIDATE DATASET
// ============================================================

export async function validateDataset(datasetId) {
  const response = await fetch(
    `${API_BASE_URL}/validate/${datasetId}`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
      error.detail || "Dataset validation failed"
    );
  }

  return response.json();
}


// ============================================================
// GET DATA QUALITY
// ============================================================

export async function getDatasetQuality(datasetId) {
  const response = await fetch(
    `${API_BASE_URL}/quality/${datasetId}`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
      error.detail || "Failed to fetch data quality"
    );
  }

  return response.json();
}


// ============================================================
// IMPORT HISTORY
// ============================================================

export async function getImportHistory() {
  const response = await fetch(
    `${API_BASE_URL}/import-history`
  );

  if (!response.ok) {
    throw new Error("Failed to fetch import history");
  }

  return response.json();
}


// ============================================================
// PREPROCESS DATASET
// ============================================================

export async function preprocessDataset(datasetId) {
  const response = await fetch(
    `${API_BASE_URL}/preprocess/${datasetId}`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
      error.detail || "Dataset preprocessing failed"
    );
  }

  return response.json();
}