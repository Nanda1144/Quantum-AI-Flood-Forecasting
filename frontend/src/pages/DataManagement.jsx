
import { useEffect, useState } from "react";

import DatasetUpload from "../components/data/DatasetUpload";
import DatasetTable from "../components/data/DatasetTable";
import DataQualityCard from "../components/data/DataQualityCard";
import ValidationResults from "../components/data/ValidationResults";
import DatasetPreview from "../components/data/DatasetPreview";

import {
  getDatasets,
  previewDataset,
  validateDataset,
  getDatasetQuality,
  preprocessDataset,
} from "../services/dataService";

function DataManagement() {
  const [datasets, setDatasets] = useState([]);
  const [selectedDataset, setSelectedDataset] = useState(null);

  const [preview, setPreview] = useState(null);
  const [quality, setQuality] = useState(null);
  const [validation, setValidation] = useState(null);
  const [preprocessing, setPreprocessing] = useState(null);

  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");

  // ============================================================
  // LOAD DATASETS
  // ============================================================

  const loadDatasets = async () => {
    try {
      setLoading(true);
      setError("");

      const response = await getDatasets();

      let datasetList = [];

      if (Array.isArray(response)) {
        datasetList = response;
      } else if (Array.isArray(response?.value)) {
        datasetList = response.value;
      } else if (Array.isArray(response?.data)) {
        datasetList = response.data;
      } else if (Array.isArray(response?.datasets)) {
        datasetList = response.datasets;
      }

      setDatasets(datasetList);

      return datasetList;
    } catch (err) {
      console.error("FAILED TO LOAD DATASETS:", err);

      setError(
        err.message || "Failed to load datasets."
      );

      return [];
    } finally {
      setLoading(false);
    }
  };

  // ============================================================
  // INITIAL LOAD
  // ============================================================

  useEffect(() => {
    loadDatasets();
  }, []);

  // ============================================================
  // UPLOAD SUCCESS
  // ============================================================

  const handleUploadSuccess = async (uploadedDataset) => {
    try {
      setError("");

      const updatedDatasets = await loadDatasets();

      if (uploadedDataset?.id) {
        const uploadedId = uploadedDataset.id;

        const datasetFromList = updatedDatasets.find(
          (dataset) =>
            String(dataset.id) === String(uploadedId)
        );

        await handleDatasetSelect(
          datasetFromList || uploadedDataset
        );
      }
    } catch (err) {
      console.error("UPLOAD SUCCESS ERROR:", err);

      setError(
        err.message || "Failed to load uploaded dataset."
      );
    }
  };

  // ============================================================
  // SELECT DATASET
  // ============================================================

  const handleDatasetSelect = async (dataset) => {
    if (!dataset) {
      setSelectedDataset(null);
      setPreview(null);
      setQuality(null);
      setValidation(null);
      setPreprocessing(null);
      return;
    }

    try {
      setActionLoading(true);
      setError("");

      // Keep the dataset object received from DatasetTable.
      // DatasetTable may already contain quality information.
      setSelectedDataset(dataset);

      // Reset old results
      setValidation(null);
      setPreprocessing(null);
      setQuality(null);
      setPreview(null);

      // ----------------------------------------------------------
      // LOAD PREVIEW
      // ----------------------------------------------------------

      const previewData = await previewDataset(dataset.id);

      setPreview(previewData);

      // ----------------------------------------------------------
      // LOAD QUALITY
      // ----------------------------------------------------------

      try {
        const qualityData = await getDatasetQuality(
          dataset.id
        );

        console.log(
          "DATA QUALITY ON SELECT:",
          qualityData
        );

        setQuality(qualityData);

        // Extract quality status from possible backend formats.
        const qualityStatus =
          qualityData?.quality_status ||
          qualityData?.status ||
          qualityData?.quality;

        // Keep Dataset Details synchronized.
        if (qualityStatus) {
          setSelectedDataset((current) => ({
            ...current,

            status:
              String(qualityStatus).toLowerCase() ===
              "good"
                ? "good"
                : qualityStatus,

            quality: qualityStatus,
          }));
        }
      } catch (qualityError) {
        console.log(
          "No quality result available yet:",
          qualityError.message
        );

        // Preserve quality already supplied by DatasetTable.
        if (dataset?.quality) {
          setQuality(dataset.quality);
        } else {
          setQuality(null);
        }
      }
    } catch (err) {
      console.error(
        "DATASET SELECT ERROR:",
        err
      );

      setError(
        err.message || "Failed to load dataset."
      );
    } finally {
      setActionLoading(false);
    }
  };

  // ============================================================
  // VALIDATE DATASET
  // ============================================================

  const handleValidate = async () => {
    if (!selectedDataset) {
      setError("Please select a dataset first.");
      return;
    }

    try {
      setActionLoading(true);
      setError("");

      const datasetId = selectedDataset.id;

      // ----------------------------------------------------------
      // VALIDATE
      // ----------------------------------------------------------

      const validationData =
        await validateDataset(datasetId);

      console.log(
        "VALIDATION RESPONSE:",
        validationData
      );

      setValidation(validationData);

      // ----------------------------------------------------------
      // GET UPDATED QUALITY
      // ----------------------------------------------------------

      const qualityData =
        await getDatasetQuality(datasetId);

      console.log(
        "UPDATED QUALITY RESPONSE:",
        qualityData
      );

      setQuality(qualityData);

      const qualityStatus =
        qualityData?.quality_status ||
        qualityData?.status ||
        qualityData?.quality;

      // ----------------------------------------------------------
      // REFRESH DATASET LIST
      // ----------------------------------------------------------

      const updatedDatasets =
        await loadDatasets();

      const updatedDataset =
        updatedDatasets.find(
          (dataset) =>
            String(dataset.id) ===
            String(datasetId)
        );

      // ----------------------------------------------------------
      // KEEP DETAILS SYNCHRONIZED
      // ----------------------------------------------------------

      if (updatedDataset) {
        setSelectedDataset({
          ...updatedDataset,

          status:
            qualityStatus ||
            updatedDataset.status,

          quality:
            qualityStatus ||
            updatedDataset.quality ||
            "Not validated",
        });
      } else {
        setSelectedDataset((current) => ({
          ...current,

          status:
            qualityStatus ||
            current?.status,

          quality:
            qualityStatus ||
            current?.quality ||
            "Not validated",
        }));
      }
    } catch (err) {
      console.error(
        "VALIDATION ERROR:",
        err
      );

      setError(
        err.message ||
          "Dataset validation failed."
      );
    } finally {
      setActionLoading(false);
    }
  };

  // ============================================================
  // PREPROCESS DATASET
  // ============================================================

  const handlePreprocess = async () => {
    if (!selectedDataset) {
      setError("Please select a dataset first.");
      return;
    }

    try {
      setActionLoading(true);
      setError("");

      const datasetId = selectedDataset.id;

      // ----------------------------------------------------------
      // PREPROCESS
      // ----------------------------------------------------------

      const result =
        await preprocessDataset(datasetId);

      console.log(
        "PREPROCESSING RESPONSE:",
        result
      );

      setPreprocessing(result);

      // ----------------------------------------------------------
      // REFRESH PREVIEW
      // ----------------------------------------------------------

      const previewData =
        await previewDataset(datasetId);

      setPreview(previewData);

      // ----------------------------------------------------------
      // REFRESH DATASET LIST
      // ----------------------------------------------------------

      const updatedDatasets =
        await loadDatasets();

      const updatedDataset =
        updatedDatasets.find(
          (dataset) =>
            String(dataset.id) ===
            String(datasetId)
        );

      // ----------------------------------------------------------
      // REFRESH QUALITY
      // ----------------------------------------------------------

      let qualityData = null;

      try {
        qualityData =
          await getDatasetQuality(datasetId);

        console.log(
          "QUALITY AFTER PREPROCESSING:",
          qualityData
        );

        setQuality(qualityData);
      } catch (qualityError) {
        console.log(
          "Quality unavailable after preprocessing:",
          qualityError.message
        );
      }

      const qualityStatus =
        qualityData?.quality_status ||
        qualityData?.status ||
        qualityData?.quality;

      // ----------------------------------------------------------
      // KEEP DETAILS SYNCHRONIZED
      // ----------------------------------------------------------

      if (updatedDataset) {
        setSelectedDataset({
          ...updatedDataset,

          status:
            qualityStatus ||
            updatedDataset.status,

          quality:
            qualityStatus ||
            updatedDataset.quality ||
            selectedDataset.quality ||
            "Not validated",
        });
      } else {
        setSelectedDataset((current) => ({
          ...current,

          status:
            qualityStatus ||
            current?.status,

          quality:
            qualityStatus ||
            current?.quality ||
            "Not validated",
        }));
      }
    } catch (err) {
      console.error(
        "PREPROCESSING ERROR:",
        err
      );

      setError(
        err.message ||
          "Dataset preprocessing failed."
      );
    } finally {
      setActionLoading(false);
    }
  };

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div className="data-management-page">

      {/* ======================================================
          PAGE HEADING
      ====================================================== */}

      <div className="page-heading">
        <div>
          <h1>Data Management</h1>

          <p>
            Upload, inspect, validate, and manage
            flood-related datasets.
          </p>
        </div>
      </div>

      {/* ======================================================
          ERROR MESSAGE
      ====================================================== */}

      {error && (
        <div className="data-management-error">
          {error}
        </div>
      )}

      {/* ======================================================
          DATASET UPLOAD
      ====================================================== */}

      <DatasetUpload
        onUploadSuccess={
          handleUploadSuccess
        }
      />

      {/* ======================================================
          SELECTED DATASET ACTIONS
      ====================================================== */}

      {selectedDataset && (
        <div className="dataset-actions">

          <div className="selected-dataset-info">
            <strong>
              Selected Dataset:
            </strong>{" "}
            {selectedDataset.file_name}
          </div>

          <div className="dataset-action-buttons">

            <button
              type="button"
              onClick={handleValidate}
              disabled={actionLoading}
            >
              {actionLoading
                ? "Processing..."
                : "Validate Dataset"}
            </button>

            <button
              type="button"
              onClick={handlePreprocess}
              disabled={actionLoading}
            >
              {actionLoading
                ? "Processing..."
                : "Preprocess Dataset"}
            </button>

          </div>
        </div>
      )}

      {/* ======================================================
          DATA QUALITY
      ====================================================== */}

      <DataQualityCard
        datasetId={
          selectedDataset?.id
        }
        quality={quality}
      />

      {/* ======================================================
          VALIDATION RESULTS
      ====================================================== */}

      <ValidationResults
        validation={validation}
      />

      {/* ======================================================
          PREPROCESSING RESULT
      ====================================================== */}

      {preprocessing && (
        <div className="preprocessing-result">

          <h2>
            Preprocessing Result
          </h2>

          <div className="preprocessing-grid">

            <div>
              <span>
                Original Rows
              </span>

              <strong>
                {preprocessing.result
                  ?.original_rows ?? "-"}
              </strong>
            </div>

            <div>
              <span>
                Cleaned Rows
              </span>

              <strong>
                {preprocessing.result
                  ?.cleaned_rows ?? "-"}
              </strong>
            </div>

            <div>
              <span>
                Duplicates Removed
              </span>

              <strong>
                {preprocessing.result
                  ?.duplicates_removed ?? 0}
              </strong>
            </div>

            <div>
              <span>
                Invalid Rows Removed
              </span>

              <strong>
                {preprocessing.result
                  ?.invalid_rows_removed ?? 0}
              </strong>
            </div>

          </div>

          <p>
            Cleaned file:{" "}
            <strong>
              {preprocessing.result
                ?.cleaned_file ?? "-"}
            </strong>
          </p>

        </div>
      )}

      {/* ======================================================
          DATASET PREVIEW
      ====================================================== */}

      <DatasetPreview
        preview={preview}
        dataset={selectedDataset}
      />

      {/* ======================================================
          DATASET TABLE
      ====================================================== */}

      <DatasetTable
        datasets={datasets}
        loading={loading}
        onDatasetSelect={
          handleDatasetSelect
        }
        selectedDatasetId={
          selectedDataset?.id
        }
        onRefresh={loadDatasets}
      />

    </div>
  );
}

export default DataManagement;

