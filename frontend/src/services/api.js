
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function uploadDataset(file) {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/datasets/upload`,
      {
        method: "POST",
        body: formData,
      }
    );

    if (!response.ok) {
      throw new Error(
        `Dataset upload failed (${response.status}).`
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Backend API is not available. Please start the API server."
      );
    }

    throw error;
  }
}

export async function getDatasets() {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/datasets`
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch datasets (${response.status}).`
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Backend API is not available. Please start the API server."
      );
    }

    throw error;
  }
}

export async function getDataset(datasetId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/datasets/${datasetId}`
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch dataset (${response.status}).`
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Backend API is not available. Please start the API server."
      );
    }

    throw error;
  }
}

export async function deleteDataset(datasetId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/datasets/${datasetId}`,
      {
        method: "DELETE",
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to delete dataset (${response.status}).`
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Backend API is not available. Please start the API server."
      );
    }

    throw error;
  }
}

