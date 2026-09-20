
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
  getDatasets,
  getDataset,
  deleteDataset,
} from "../../services/api";

function DatasetTable({ refreshKey }) {
  const [datasets, setDatasets] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [selectedDataset, setSelectedDataset] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  useEffect(() => {
    loadDatasets();
  }, [refreshKey]);

  const loadDatasets = async () => {
    setLoading(true);
    setApiError("");

    try {
      const data = await getDatasets();

      const datasetList = Array.isArray(data)
        ? data
        : data.datasets || [];

      setDatasets(datasetList);
    } catch (error) {
      console.error("Dataset fetch error:", error);

      setDatasets([]);
      setApiError(error.message);
    } finally {
      setLoading(false);
    }
  };

  const handleView = async (dataset) => {
    const datasetId = dataset.id || dataset._id;

    if (!datasetId) {
      setSelectedDataset(dataset);
      setActionMessage(
        "Dataset ID is not available. Showing available dataset information."
      );
      return;
    }

    try {
      setDetailsLoading(true);
      setActionMessage("");

      const result = await getDataset(datasetId);

      setSelectedDataset(result.dataset || result);
    } catch (error) {
      console.error("View dataset error:", error);

      setSelectedDataset(dataset);

      setActionMessage(
        error.message ||
          "Unable to load complete dataset details. Showing available information."
      );
    } finally {
      setDetailsLoading(false);
    }
  };

  const handleDelete = async (dataset) => {
    const datasetId = dataset.id || dataset._id;

    if (!datasetId) {
      setActionMessage("Dataset ID is not available.");
      return;
    }

    const datasetName =
      dataset.name || "this dataset";

    const confirmed = window.confirm(
      `Are you sure you want to delete "${datasetName}"?`
    );

    if (!confirmed) {
      return;
    }

    try {
      setActionMessage("Deleting dataset...");

      await deleteDataset(datasetId);

      setActionMessage("Dataset deleted successfully.");

      if (
        selectedDataset &&
        (selectedDataset.id === datasetId ||
          selectedDataset._id === datasetId)
      ) {
        setSelectedDataset(null);
      }

      await loadDatasets();
    } catch (error) {
      console.error("Delete dataset error:", error);

      setActionMessage(
        error.message || "Unable to delete dataset."
      );
    }
  };

  const closeDetails = () => {
    setSelectedDataset(null);
    setActionMessage("");
  };

  const filteredDatasets = datasets.filter((dataset) => {
    const searchText = searchTerm.toLowerCase();

    const name = dataset.name || "";
    const source = dataset.source || "";
    const status = dataset.status || "Available";

    const matchesSearch =
      name.toLowerCase().includes(searchText) ||
      source.toLowerCase().includes(searchText) ||
      status.toLowerCase().includes(searchText);

    const matchesStatus =
      statusFilter === "All" ||
      status.toLowerCase() ===
        statusFilter.toLowerCase();

    return matchesSearch && matchesStatus;
  });

  return (
    <div className="dataset-table-card">
      <div className="table-header">
        <div>
          <h2>Datasets</h2>

          <p>
            View and manage available flood datasets.
          </p>

          <span className="dataset-count">
            Total: {datasets.length}{" "}
            {datasets.length === 1
              ? "dataset"
              : "datasets"}
          </span>
        </div>

        <div className="table-actions">
          <div className="search-box">
            <Search size={17} />

            <input
              type="text"
              placeholder="Search datasets..."
              value={searchTerm}
              onChange={(event) =>
                setSearchTerm(event.target.value)
              }
            />
          </div>

          <button
            type="button"
            className="filter-button"
            onClick={loadDatasets}
            disabled={loading}
            title="Refresh datasets"
          >
            <RefreshCw
              size={17}
              className={
                loading ? "refresh-spinning" : ""
              }
            />

            Refresh
          </button>

          <button
            type="button"
            className="filter-button"
            onClick={() =>
              setShowFilters(!showFilters)
            }
          >
            <Filter size={17} />

            Filter
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="dataset-filter-panel">
          <label htmlFor="status-filter">
            Status
          </label>

          <select
            id="status-filter"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value)
            }
          >
            <option value="All">All</option>
            <option value="Available">Available</option>
            <option value="Processing">Processing</option>
            <option value="Failed">Failed</option>
          </select>
        </div>
      )}

      {actionMessage && (
        <div className="dataset-action-message">
          {actionMessage}
        </div>
      )}

      {selectedDataset && (
        <div className="dataset-details-panel">
          <div className="dataset-details-header">
            <div>
              <h3>Dataset Details</h3>
              <p>
                Information about the selected dataset.
              </p>
            </div>

            <button
              type="button"
              className="details-close-button"
              onClick={closeDetails}
              title="Close details"
            >
              <X size={18} />
            </button>
          </div>

          {detailsLoading ? (
            <div className="dataset-details-loading">
              Loading dataset details...
            </div>
          ) : (
            <div className="dataset-details-grid">
              <div className="dataset-detail-item">
                <span>Name</span>
                <strong>
                  {selectedDataset.name ||
                    "Unnamed Dataset"}
                </strong>
              </div>

              <div className="dataset-detail-item">
                <span>Source</span>
                <strong>
                  {selectedDataset.source ||
                    "Uploaded"}
                </strong>
              </div>

              <div className="dataset-detail-item">
                <span>Records</span>
                <strong>
                  {selectedDataset.records ??
                    selectedDataset.record_count ??
                    "-"}
                </strong>
              </div>

              <div className="dataset-detail-item">
                <span>Quality</span>
                <strong>
                  {selectedDataset.quality
                    ? `${selectedDataset.quality}%`
                    : "-"}
                </strong>
              </div>

              <div className="dataset-detail-item">
                <span>Status</span>
                <strong>
                  {selectedDataset.status ||
                    "Available"}
                </strong>
              </div>

              <div className="dataset-detail-item">
                <span>Dataset ID</span>
                <strong>
                  {selectedDataset.id ||
                    selectedDataset._id ||
                    "-"}
                </strong>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Source</th>
              <th>Records</th>
              <th>Quality</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>

          <tbody>
            {loading ? (
              <tr>
                <td colSpan="6">
                  <div className="table-empty">
                    Loading datasets...
                  </div>
                </td>
              </tr>
            ) : apiError ? (
              <tr>
                <td colSpan="6">
                  <div className="table-empty">
                    {apiError}
                  </div>
                </td>
              </tr>
            ) : filteredDatasets.length === 0 ? (
              <tr>
                <td colSpan="6">
                  <div className="table-empty">
                    No datasets match the selected
                    filters.
                  </div>
                </td>
              </tr>
            ) : (
              filteredDatasets.map(
                (dataset, index) => (
                  <tr
                    key={
                      dataset.id ||
                      dataset._id ||
                      index
                    }
                  >
                    <td>
                      <strong>
                        {dataset.name ||
                          "Unnamed Dataset"}
                      </strong>
                    </td>

                    <td>
                      {dataset.source ||
                        "Uploaded"}
                    </td>

                    <td>
                      {dataset.records ??
                        dataset.record_count ??
                        "-"}
                    </td>

                    <td>
                      {dataset.quality
                        ? `${dataset.quality}%`
                        : "-"}
                    </td>

                    <td>
                      <span className="dataset-status">
                        {dataset.status ||
                          "Available"}
                      </span>
                    </td>

                    <td>
                      <div className="dataset-actions">
                        <button
                          type="button"
                          title="View dataset"
                          onClick={() =>
                            handleView(dataset)
                          }
                        >
                          <Eye size={17} />
                        </button>

                        <button
                          type="button"
                          title="Delete dataset"
                          onClick={() =>
                            handleDelete(dataset)
                          }
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              )
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default DatasetTable;

