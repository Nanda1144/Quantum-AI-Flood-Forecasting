import { useEffect, useState } from "react";
import { RefreshCw, History, FileText } from "lucide-react";
import {
  getImportHistory,
  getDataset,
} from "../../services/dataService";

function ImportHistory() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadHistory = async () => {
    try {
      setLoading(true);
      setError("");

      const response = await getImportHistory();

      const historyData = Array.isArray(response)
        ? response
        : Array.isArray(response.value)
        ? response.value
        : Array.isArray(response.history)
        ? response.history
        : Array.isArray(response.data)
        ? response.data
        : [];

      // Fetch dataset details to get column count
      const enrichedHistory = await Promise.all(
        historyData.map(async (item) => {
          try {
            if (item.dataset_id) {
              const dataset = await getDataset(item.dataset_id);

              return {
                ...item,
                column_count:
                  dataset.column_count ??
                  dataset.total_columns ??
                  dataset.columns ??
                  0,
              };
            }

            return {
              ...item,
              column_count: 0,
            };
          } catch (err) {
            console.error(
              `Failed to load dataset ${item.dataset_id}:`,
              err
            );

            return {
              ...item,
              column_count: 0,
            };
          }
        })
      );

      setHistory(enrichedHistory);
    } catch (err) {
      console.error("Failed to load import history:", err);
      setError(err.message || "Failed to load import history");
      setHistory([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  const formatDate = (value) => {
    if (!value) return "-";

    try {
      return new Date(value).toLocaleString();
    } catch {
      return String(value);
    }
  };

  const getStatusClass = (status) => {
    return `history-status status-${String(status || "unknown")
      .toLowerCase()
      .replace(/\s+/g, "-")}`;
  };

  return (
    <section className="import-history-section">
      <div className="import-history-header">
        <div className="import-history-title">
          <div className="import-history-icon">
            <History size={22} />
          </div>

          <div>
            <h2>Import History</h2>
            <p>View previously imported flood datasets.</p>
          </div>
        </div>

        <button
          type="button"
          className="import-history-refresh"
          onClick={loadHistory}
          disabled={loading}
        >
          <RefreshCw
            size={17}
            className={loading ? "spin" : ""}
          />
          Refresh
        </button>
      </div>

      {error && (
        <div className="import-history-error">
          {error}
        </div>
      )}

      {loading ? (
        <div className="import-history-loading">
          <RefreshCw size={22} className="spin" />
          <span>Loading import history...</span>
        </div>
      ) : history.length === 0 ? (
        <div className="import-history-empty">
          <FileText size={30} />

          <h3>No import history</h3>

          <p>
            Imported datasets will appear here.
          </p>
        </div>
      ) : (
        <div className="import-history-table-wrapper">
          <table className="import-history-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Dataset</th>
                <th>File Type</th>
                <th>Records</th>
                <th>Columns</th>
                <th>Status</th>
                <th>Imported</th>
              </tr>
            </thead>

            <tbody>
              {history.map((item, index) => (
                <tr key={item.id ?? index}>
                  <td>{index + 1}</td>

                  <td>
                    <div className="history-dataset-name">
                      <strong>
                        {item.file_name ||
                          item.name ||
                          "Unnamed Dataset"}
                      </strong>
                    </div>
                  </td>

                  <td>
                    {String(
                      item.file_type || "-"
                    ).toUpperCase()}
                  </td>

                  <td>
                    {item.rows_imported ?? 0}
                  </td>

                  <td>
                    {item.column_count ?? 0}
                  </td>

                  <td>
                    <span
                      className={getStatusClass(
                        item.status
                      )}
                    >
                      {item.status || "Unknown"}
                    </span>
                  </td>

                  <td>
                    {formatDate(
                      item.completed_at ||
                        item.started_at
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default ImportHistory;