
function ValidationResults({ validation }) {
  if (!validation) {
    return (
      <section className="validation-card">
        <div className="section-header">
          <div>
            <h2>Validation Results</h2>
            <p>
              Basic checks performed on the selected flood dataset.
            </p>
          </div>
        </div>

        <div className="validation-empty-state">
          <p>Validate the selected dataset to view validation results.</p>
        </div>
      </section>
    );
  }

  const qualityResult =
    validation?.quality_result ||
    validation?.result ||
    validation;

  const qualityStatus = String(
    qualityResult?.quality_status ||
      qualityResult?.status ||
      "unknown"
  ).toLowerCase();

  const totalRows = Number(qualityResult?.total_rows) || 0;
  const totalColumns =
    Number(qualityResult?.total_columns) || 0;
  const missingValues =
    Number(qualityResult?.missing_values) || 0;
  const duplicateRows =
    Number(qualityResult?.duplicate_rows) || 0;
  const invalidRows =
    Number(qualityResult?.invalid_rows) || 0;

  const passed = qualityStatus === "good";

  const getStatusText = () => {
    if (qualityStatus === "good") {
      return "Passed";
    }

    if (qualityStatus === "warning") {
      return "Warning";
    }

    if (
      qualityStatus === "bad" ||
      qualityStatus === "error"
    ) {
      return "Failed";
    }

    return "Completed";
  };

  const getCheckMark = (isGood) => {
    return isGood ? "✓" : "!";
  };

  return (
    <section className="validation-card">
      <div className="section-header">
        <div>
          <h2>Validation Results</h2>
          <p>
            Basic checks performed on the selected flood dataset.
          </p>
        </div>

        <span
          className={`validation-status validation-status-${qualityStatus}`}
        >
          {getStatusText()}
        </span>
      </div>

      <div className="validation-summary">
        <div>
          <span>Total Rows</span>
          <strong>{totalRows}</strong>
        </div>

        <div>
          <span>Total Columns</span>
          <strong>{totalColumns}</strong>
        </div>

        <div>
          <span>Quality Status</span>
          <strong>
            {qualityStatus === "good"
              ? "Good"
              : qualityStatus === "warning"
              ? "Warning"
              : qualityStatus}
          </strong>
        </div>
      </div>

      <div className="validation-list">
        <div className="validation-row">
          <div>
            <strong>Required Columns</strong>
            <span>
              {totalColumns > 0
                ? "Dataset columns detected successfully"
                : "No columns detected"}
            </span>
          </div>

          <span className="check-mark">
            {getCheckMark(totalColumns > 0)}
          </span>
        </div>

        <div className="validation-row">
          <div>
            <strong>Missing Values</strong>
            <span>
              {missingValues === 0
                ? "No missing values detected"
                : `${missingValues} missing values detected`}
            </span>
          </div>

          <span className="check-mark">
            {getCheckMark(missingValues === 0)}
          </span>
        </div>

        <div className="validation-row">
          <div>
            <strong>Invalid Values</strong>
            <span>
              {invalidRows === 0
                ? "No invalid records detected"
                : `${invalidRows} invalid records detected`}
            </span>
          </div>

          <span className="check-mark">
            {getCheckMark(invalidRows === 0)}
          </span>
        </div>

        <div className="validation-row">
          <div>
            <strong>Duplicate Records</strong>
            <span>
              {duplicateRows === 0
                ? "No duplicate records detected"
                : `${duplicateRows} duplicate records detected`}
            </span>
          </div>

          <span className="check-mark">
            {getCheckMark(duplicateRows === 0)}
          </span>
        </div>
      </div>

      {validation?.message && (
        <div className="validation-message">
          {validation.message}
        </div>
      )}
    </section>
  );
}

export default ValidationResults;

