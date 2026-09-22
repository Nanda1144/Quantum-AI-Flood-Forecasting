
function DataQualityCard({ datasetId, quality }) {
  // ============================================================
  // NO DATASET
  // ============================================================

  if (!datasetId) {
    return (
      <section className="data-quality-card">
        <div className="section-heading">
          <h2>Data Quality</h2>

          <p>
            Overview of the quality and completeness
            of uploaded datasets.
          </p>
        </div>

        <div className="quality-empty-state">
          <p>
            Select a dataset to view its quality information.
          </p>
        </div>
      </section>
    );
  }

  // ============================================================
  // NO QUALITY RESULT
  // ============================================================

  if (!quality) {
    return (
      <section className="data-quality-card">
        <div className="section-heading">
          <h2>Data Quality</h2>

          <p>
            Overview of the quality and completeness
            of the selected dataset.
          </p>
        </div>

        <div className="quality-empty-state">
          <p>
            Data quality result not found. Validate the dataset first.
          </p>
        </div>
      </section>
    );
  }

  // ============================================================
  // NORMALIZE QUALITY RESPONSE
  // ============================================================

  const qualityResult =
    quality?.quality_result ||
    quality?.result ||
    quality;

  const totalRows =
    Number(qualityResult?.total_rows) || 0;

  const totalColumns =
    Number(qualityResult?.total_columns) || 0;

  const missingValues =
    Number(qualityResult?.missing_values) || 0;

  const duplicateRows =
    Number(qualityResult?.duplicate_rows) || 0;

  const invalidRows =
    Number(qualityResult?.invalid_rows) || 0;

  const qualityStatus = String(
    qualityResult?.quality_status ||
      qualityResult?.status ||
      "unknown"
  ).toLowerCase();

  // ============================================================
  // CALCULATE PERCENTAGES
  // ============================================================

  const missingPercentage =
    totalRows > 0
      ? Math.round(
          (missingValues / totalRows) * 100
        )
      : 0;

  const invalidPercentage =
    totalRows > 0
      ? Math.round(
          (invalidRows / totalRows) * 100
        )
      : 0;

  const completenessPercentage =
    Math.max(
      0,
      100 - missingPercentage
    );

  const validPercentage =
    Math.max(
      0,
      100 - invalidPercentage
    );

  // ============================================================
  // QUALITY LABEL
  // ============================================================

  let qualityLabel = "Unknown";
  let qualityMessage = "Dataset requires further review.";

  if (qualityStatus === "good") {
    qualityLabel = "Good Quality";
    qualityMessage = "Dataset passed quality checks.";
  } else if (qualityStatus === "warning") {
    qualityLabel = "Warning";
    qualityMessage = "Dataset contains quality warnings.";
  } else if (
    qualityStatus === "bad" ||
    qualityStatus === "error"
  ) {
    qualityLabel = "Poor Quality";
    qualityMessage = "Dataset requires further review.";
  }

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <section className="data-quality-card">

      <div className="section-heading">
        <div>
          <h2>Data Quality</h2>

          <p>
            Overview of the quality and completeness
            of the selected dataset.
          </p>
        </div>
      </div>

      {/* QUALITY STATUS */}

      <div className="quality-overview">
        <div
          className={`quality-status quality-status-${qualityStatus}`}
        >
          <strong>
            {qualityLabel}
          </strong>

          <span>
            {qualityMessage}
          </span>
        </div>
      </div>

      {/* QUALITY METRICS */}

      <div className="quality-metrics">

        <div className="quality-metric">

          <div className="quality-metric-header">
            <span>
              Completeness
            </span>

            <strong>
              {completenessPercentage}%
            </strong>
          </div>

          <div className="quality-progress">
            <div
              className="quality-progress-fill"
              style={{
                width:
                  `${completenessPercentage}%`,
              }}
            />
          </div>

        </div>

        <div className="quality-metric">

          <div className="quality-metric-header">
            <span>
              Valid Records
            </span>

            <strong>
              {validPercentage}%
            </strong>
          </div>

          <div className="quality-progress">
            <div
              className="quality-progress-fill"
              style={{
                width:
                  `${validPercentage}%`,
              }}
            />
          </div>

        </div>

      </div>

      {/* QUALITY STATISTICS */}

      <div className="quality-stat-grid">

        <div className="quality-stat">
          <span>
            Missing Values
          </span>

          <strong>
            {missingValues}
          </strong>

          <small>
            {missingPercentage}% of rows
          </small>
        </div>

        <div className="quality-stat">
          <span>
            Duplicate Records
          </span>

          <strong>
            {duplicateRows}
          </strong>

          <small>
            {totalRows > 0
              ? Math.round(
                  (duplicateRows /
                    totalRows) *
                    100
                )
              : 0}
            % of rows
          </small>
        </div>

        <div className="quality-stat">
          <span>
            Invalid Records
          </span>

          <strong>
            {invalidRows}
          </strong>

          <small>
            {invalidPercentage}% of rows
          </small>
        </div>

      </div>

      {/* SUMMARY */}

      <div className="quality-summary">

        <div>
          <span>
            Total Rows
          </span>

          <strong>
            {totalRows}
          </strong>
        </div>

        <div>
          <span>
            Total Columns
          </span>

          <strong>
            {totalColumns}
          </strong>
        </div>

        <div>
          <span>
            Quality Status
          </span>

          <strong>
            {qualityStatus === "good"
              ? "Good"
              : qualityStatus === "warning"
              ? "Warning"
              : qualityStatus}
          </strong>
        </div>

      </div>

    </section>
  );
}

export default DataQualityCard;
