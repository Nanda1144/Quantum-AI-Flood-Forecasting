
import { useEffect, useState } from "react";
import {
  Search,
  Filter,
  Eye,
  Trash2,
  RefreshCw,
  X,
} from "lucide-react";

import {
  getDataset,
  deleteDataset,
  previewDataset,
  getDatasetQuality,
} from "../../services/dataService";

function DatasetTable({
  datasets = [],
  loading = false,
  onDatasetSelect,
  selectedDatasetId,
  onRefresh,
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [showFilters, setShowFilters] = useState(false);

  const [actionMessage, setActionMessage] = useState("");

  const [selectedDataset, setSelectedDataset] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const [deleteLoading, setDeleteLoading] = useState(null);

  // Real dataset preview data
  const [previewData, setPreviewData] = useState([]);

  // ============================================================
  // FILTER DATASETS
  // ============================================================

  const filteredDatasets = datasets.filter((dataset) => {
    const searchValue = searchTerm.toLowerCase().trim();

    const matchesSearch =
      !searchValue ||
      String(dataset.name || "")
        .toLowerCase()
        .includes(searchValue) ||
      String(dataset.file_name || "")
        .toLowerCase()
        .includes(searchValue) ||
      String(dataset.file_type || "")
        .toLowerCase()
        .includes(searchValue);

    const matchesStatus =
      statusFilter === "all" ||
      String(dataset.status || "").toLowerCase() ===
        statusFilter.toLowerCase();

    return matchesSearch && matchesStatus;
  });

  // ============================================================
  // GET QUALITY LABEL
  // ============================================================

  const getQualityLabel = (dataset) => {
    if (!dataset) {
      return "Not validated";
    }

    const quality =
      dataset.quality ||
      dataset.quality_status ||
      dataset.quality_label;

    if (!quality) {
      return "Not validated";
    }

    // Backend may return quality as an object
    if (typeof quality === "object") {
      const objectQuality =
        quality.quality_status ||
        quality.status ||
        quality.quality;

      if (!objectQuality) {
        return "Not validated";
      }

      const value = String(objectQuality).toLowerCase();

      if (value === "good") {
        return "Good";
      }

      if (value === "warning") {
        return "Warning";
      }

      if (value === "bad") {
        return "Bad";
      }

      return String(objectQuality);
    }

    const value = String(quality).toLowerCase();

    if (value === "good") {
      return "Good";
    }

    if (value === "warning") {
      return "Warning";
    }

    if (value === "bad") {
      return "Bad";
    }

    return String(quality);
  };

  // ============================================================
  // GET RECORD COUNT
  // ============================================================

  const getRecordCount = (dataset) => {
    return (
      dataset.row_count ??
      dataset.total_rows ??
      dataset.records ??
      dataset.record_count ??
      0
    );
  };

  // ============================================================
  // GET COLUMN COUNT
  // ============================================================

  const getColumnCount = (dataset) => {
    return (
      dataset.column_count ??
      dataset.total_columns ??
      dataset.columns_count ??
      0
    );
  };

  // ============================================================
  // VIEW DATASET
  // ============================================================

  const handleView = async (dataset) => {
    try {
      setDetailsLoading(true);
      setActionMessage("");

      // Clear previous preview
      setPreviewData([]);

      // Get dataset details and preview
      const requests = [
        getDataset(dataset.id),
        previewDataset(dataset.id),
      ];

      // Get quality information for validated datasets
      if (
        String(dataset.status || "").toLowerCase() === "good" ||
        String(dataset.status || "").toLowerCase() === "warning" ||
        String(dataset.status || "").toLowerCase() === "bad"
      ) {
        requests.push(getDatasetQuality(dataset.id));
      }

      const responses = await Promise.all(requests);

      const datasetResponse = responses[0];
      const previewResponse = responses[1];
      const qualityResponse = responses[2];

      // ========================================================
      // MERGE QUALITY RESULT INTO DATASET DETAILS
      // ========================================================

      const mergedDataset = {
        ...datasetResponse,
      };

      if (qualityResponse) {
        const qualityValue =
          qualityResponse.quality_status ||
          qualityResponse.status ||
          qualityResponse.quality;

        if (qualityValue) {
          mergedDataset.quality = qualityValue;
        } else {
          mergedDataset.quality = qualityResponse;
        }
      }

      // Store selected dataset
      setSelectedDataset(mergedDataset);

      // ========================================================
      // PROCESS REAL BACKEND PREVIEW RESPONSE
      // ========================================================

      let previewRows = [];

      // Case 1: API directly returns an array
      if (Array.isArray(previewResponse)) {
        previewRows = previewResponse;
      }

      // Case 2: Current Q-FLARE backend response
      else if (Array.isArray(previewResponse.preview_rows)) {
        previewRows = previewResponse.preview_rows;
      }

      // Case 3: Other possible response format
      else if (Array.isArray(previewResponse.data)) {
        previewRows = previewResponse.data;
      }

      // Case 4: Other possible response format
      else if (Array.isArray(previewResponse.rows)) {
        previewRows = previewResponse.rows;
      }

      setPreviewData(previewRows);

      // Send selected dataset to parent
      if (onDatasetSelect) {
        onDatasetSelect(mergedDataset);
      }
    } catch (error) {
      console.error(
        "Failed to load dataset details:",
        error
      );

      setActionMessage(
        error.message ||
          "Failed to load dataset details"
      );

      setSelectedDataset(null);
      setPreviewData([]);
    } finally {
      setDetailsLoading(false);
    }
  };

  // ============================================================
  // DELETE DATASET
  // ============================================================

  const handleDelete = async (dataset) => {
    const confirmed = window.confirm(
      `Are you sure you want to delete "${
        dataset.file_name || dataset.name
      }"?`
    );

    if (!confirmed) {
      return;
    }

    try {
      setDeleteLoading(dataset.id);
      setActionMessage("");

      await deleteDataset(dataset.id);

      // If deleted dataset is currently selected
      if (
        selectedDataset &&
        String(selectedDataset.id) ===
          String(dataset.id)
      ) {
        setSelectedDataset(null);
        setPreviewData([]);

        if (onDatasetSelect) {
          onDatasetSelect(null);
        }
      }

      setActionMessage(
        "Dataset deleted successfully."
      );

      // Refresh dataset list
      if (onRefresh) {
        await onRefresh();
      }
    } catch (error) {
      console.error(
        "Failed to delete dataset:",
        error
      );

      setActionMessage(
        error.message ||
          "Failed to delete dataset"
      );
    } finally {
      setDeleteLoading(null);
    }
  };

  // ============================================================
  // CLOSE DATASET DETAILS
  // ============================================================

  const handleCloseDetails = () => {
    setSelectedDataset(null);
    setPreviewData([]);
    setActionMessage("");

    if (onDatasetSelect) {
      onDatasetSelect(null);
    }
  };

  // ============================================================
  // REFRESH
  // ============================================================

  const handleRefresh = async () => {
    try {
      setActionMessage("");

      if (onRefresh) {
        await onRefresh();
      }

      setActionMessage(
        "Datasets refreshed successfully."
      );
    } catch (error) {
      console.error(
        "Failed to refresh datasets:",
        error
      );

      setActionMessage(
        error.message ||
          "Failed to refresh datasets"
      );
    }
  };

  // ============================================================
  // PREVIEW COLUMNS
  // ============================================================

  const previewColumns =
    previewData.length > 0
      ? Object.keys(previewData[0])
      : [];

  // ============================================================
  // KEEP SELECTED DATASET IN SYNC
  // ============================================================

  useEffect(() => {
    if (
      selectedDatasetId !== undefined &&
      selectedDatasetId !== null
    ) {
      const existingDataset = datasets.find(
        (dataset) =>
          String(dataset.id) ===
          String(selectedDatasetId)
      );

      if (existingDataset && !selectedDataset) {
        handleView(existingDataset);
      }
    }
  }, [selectedDatasetId]);

  return (
    <div className="dataset-management">

      {/* ========================================================
          HEADER
      ======================================================== */}

      <div className="dataset-table-header">
        <div>
          <h2>Datasets</h2>

          <p>
            Total:{" "}
            <strong>{datasets.length}</strong>{" "}
            datasets
          </p>
        </div>

        <div className="dataset-actions">

          {/* Search */}

          <div className="dataset-search">
            <Search size={18} />

            <input
              type="text"
              placeholder="Search datasets..."
              value={searchTerm}
              onChange={(event) =>
                setSearchTerm(event.target.value)
              }
            />
          </div>

          {/* Filter */}

          <button
            type="button"
            className={`icon-button ${
              showFilters ? "active" : ""
            }`}
            onClick={() =>
              setShowFilters(
                (previous) => !previous
              )
            }
            title="Filter datasets"
          >
            <Filter size={18} />
          </button>

          {/* Refresh */}

          <button
            type="button"
            className="icon-button"
            onClick={handleRefresh}
            disabled={loading}
            title="Refresh datasets"
          >
            <RefreshCw
              size={18}
              className={
                loading ? "spin" : ""
              }
            />
          </button>
        </div>
      </div>

      {/* ========================================================
          FILTERS
      ======================================================== */}

      {showFilters && (
        <div className="dataset-filter-panel">

          <div className="filter-group">
            <label htmlFor="status-filter">
              Status
            </label>

            <select
              id="status-filter"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(
                  event.target.value
                )
              }
            >
              <option value="all">
                All
              </option>

              <option value="uploaded">
                Uploaded
              </option>

              <option value="good">
                Good
              </option>

              <option value="warning">
                Warning
              </option>

              <option value="error">
                Error
              </option>
            </select>
          </div>

          <button
            type="button"
            className="clear-filter-button"
            onClick={() => {
              setSearchTerm("");
              setStatusFilter("all");
            }}
          >
            Clear Filters
          </button>
        </div>
      )}

      {/* ========================================================
          ACTION MESSAGE
      ======================================================== */}

      {actionMessage && (
        <div className="dataset-action-message">
          {actionMessage}
        </div>
      )}

      {/* ========================================================
          LOADING / EMPTY / TABLE
      ======================================================== */}

      {loading ? (
        <div className="dataset-loading">
          <RefreshCw
            size={22}
            className="spin"
          />

          <span>
            Loading datasets...
          </span>
        </div>
      ) : filteredDatasets.length === 0 ? (

        <div className="dataset-empty">

          <div className="dataset-empty-icon">
            <Search size={28} />
          </div>

          <h3>
            No datasets found
          </h3>

          <p>
            {searchTerm ||
            statusFilter !== "all"
              ? "Try changing your search or filter."
              : "Upload a dataset to get started."}
          </p>
        </div>

      ) : (

        <div className="dataset-table-wrapper">

          <table className="dataset-table">

            <thead>
              <tr>
                <th>Dataset</th>
                <th>File Type</th>
                <th>Records</th>
                <th>Columns</th>
                <th>Status</th>
                <th>Quality</th>
                <th>Actions</th>
              </tr>
            </thead>

            <tbody>

              {filteredDatasets.map(
                (dataset) => {

                  const isSelected =
                    selectedDataset &&
                    String(
                      selectedDataset.id
                    ) ===
                      String(dataset.id);

                  return (
                    <tr
                      key={dataset.id}
                      className={
                        isSelected
                          ? "selected-row"
                          : ""
                      }
                    >

                      {/* Dataset */}

                      <td>
                        <div className="dataset-name-cell">

                          <strong>
                            {dataset.file_name ||
                              dataset.name ||
                              "Unnamed Dataset"}
                          </strong>

                          {dataset.name &&
                            dataset.file_name &&
                            dataset.name !==
                              dataset.file_name && (
                              <span>
                                {dataset.name}
                              </span>
                            )}

                        </div>
                      </td>

                      {/* File Type */}

                      <td>
                        <span className="file-type-badge">
                          {String(
                            dataset.file_type ||
                              "unknown"
                          ).toUpperCase()}
                        </span>
                      </td>

                      {/* Records */}

                      <td>
                        {getRecordCount(
                          dataset
                        )}
                      </td>

                      {/* Columns */}

                      <td>
                        {getColumnCount(
                          dataset
                        )}
                      </td>

                      {/* Status */}

                      <td>
                        <span
                          className={`status-badge status-${String(
                            dataset.status ||
                              "unknown"
                          )
                            .toLowerCase()
                            .replace(
                              /\s+/g,
                              "-"
                            )}`}
                        >
                          {dataset.status ||
                            "Unknown"}
                        </span>
                      </td>

                      {/* Quality */}

                      <td>
                        <span
                          className={`quality-badge quality-${String(
                            getQualityLabel(
                              dataset
                            )
                          )
                            .toLowerCase()
                            .replace(
                              /\s+/g,
                              "-"
                            )}`}
                        >
                          {getQualityLabel(
                            dataset
                          )}
                        </span>
                      </td>

                      {/* Actions */}

                      <td>
                        <div className="dataset-row-actions">

                          {/* View */}

                          <button
                            type="button"
                            className="table-action-button view-button"
                            onClick={() =>
                              handleView(
                                dataset
                              )
                            }
                            disabled={
                              detailsLoading &&
                              String(
                                selectedDataset?.id
                              ) ===
                                String(
                                  dataset.id
                                )
                            }
                            title="View dataset"
                          >
                            <Eye size={17} />

                            <span>
                              View
                            </span>
                          </button>

                          {/* Delete */}

                          <button
                            type="button"
                            className="table-action-button delete-button"
                            onClick={() =>
                              handleDelete(
                                dataset
                              )
                            }
                            disabled={
                              deleteLoading ===
                              dataset.id
                            }
                            title="Delete dataset"
                          >
                            {deleteLoading ===
                            dataset.id ? (
                              <RefreshCw
                                size={17}
                                className="spin"
                              />
                            ) : (
                              <Trash2
                                size={17}
                              />
                            )}

                            <span>
                              Delete
                            </span>
                          </button>

                        </div>
                      </td>

                    </tr>
                  );
                }
              )}

            </tbody>

          </table>

        </div>
      )}

      {/* ========================================================
          DATASET DETAILS
      ======================================================== */}

      {selectedDataset && (
        <div className="dataset-details-panel">

          <div className="dataset-details-header">

            <div>
              <h3>
                Dataset Details
              </h3>

              <p>
                Detailed information and preview
              </p>
            </div>

            <button
              type="button"
              className="close-details-button"
              onClick={
                handleCloseDetails
              }
              title="Close"
            >
              <X size={20} />
            </button>

          </div>

          {/* ====================================================
              DETAILS GRID
          ==================================================== */}

          <div className="dataset-details-grid">

            <div className="detail-item">
              <span>Name</span>

              <strong>
                {selectedDataset.name ||
                  selectedDataset.file_name ||
                  "-"}
              </strong>
            </div>

            <div className="detail-item">
              <span>File Name</span>

              <strong>
                {selectedDataset.file_name ||
                  "-"}
              </strong>
            </div>

            <div className="detail-item">
              <span>File Type</span>

              <strong>
                {String(
                  selectedDataset.file_type ||
                    "-"
                ).toUpperCase()}
              </strong>
            </div>

            <div className="detail-item">
              <span>Records</span>

              <strong>
                {getRecordCount(
                  selectedDataset
                )}
              </strong>
            </div>

            <div className="detail-item">
              <span>Columns</span>

              <strong>
                {getColumnCount(
                  selectedDataset
                )}
              </strong>
            </div>

            <div className="detail-item">
              <span>Status</span>

              <strong>
                {selectedDataset.status ||
                  "-"}
              </strong>
            </div>

            <div className="detail-item">
              <span>Quality</span>

              <strong>
                {getQualityLabel(
                  selectedDataset
                )}
              </strong>
            </div>

            <div className="detail-item">
              <span>Dataset ID</span>

              <strong>
                {selectedDataset.id ||
                  "-"}
              </strong>
            </div>

          </div>

          {/* ====================================================
              REAL DATASET PREVIEW
          ==================================================== */}

          <div className="dataset-preview-section">

            <div className="dataset-preview-header">

              <div>
                <h3>
                  Dataset Preview
                </h3>

                <p>
                  Showing preview rows from the
                  uploaded dataset.
                </p>
              </div>

              {previewData.length > 0 && (
                <span className="preview-count">
                  {previewData.length} preview rows
                </span>
              )}

            </div>

            {detailsLoading ? (

              <div className="preview-loading">

                <RefreshCw
                  size={20}
                  className="spin"
                />

                <span>
                  Loading preview...
                </span>

              </div>

            ) : previewData.length > 0 ? (

              <div className="preview-table-wrapper">

                <table className="preview-table">

                  <thead>
                    <tr>
                      {previewColumns.map(
                        (column) => (
                          <th key={column}>
                            {column}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>

                  <tbody>

                    {previewData.map(
                      (row, rowIndex) => (
                        <tr key={rowIndex}>

                          {previewColumns.map(
                            (column) => (
                              <td key={column}>
                                {row[column] !==
                                  null &&
                                row[column] !==
                                  undefined
                                  ? String(
                                      row[column]
                                    )
                                  : "-"}
                              </td>
                            )
                          )}

                        </tr>
                      )
                    )}

                  </tbody>

                </table>

              </div>

            ) : (

              <div className="preview-empty">
                <p>
                  No preview data available.
                </p>
              </div>

            )}

          </div>

        </div>
      )}

    </div>
  );
}

export default DatasetTable;

