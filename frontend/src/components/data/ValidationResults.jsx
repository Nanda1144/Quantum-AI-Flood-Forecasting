function ValidationResults() {
  return (
    <section className="validation-card">
      <div className="section-header">
        <div>
          <h2>Validation Results</h2>
          <p>
            Basic checks performed on the selected flood dataset.
          </p>
        </div>

        <span className="validation-status">
          Passed
        </span>
      </div>

      <div className="validation-list">
        <div className="validation-row">
          <div>
            <strong>Required Columns</strong>
            <span>All required fields are available</span>
          </div>

          <span className="check-mark">✓</span>
        </div>

        <div className="validation-row">
          <div>
            <strong>Missing Values</strong>
            <span>Within acceptable limits</span>
          </div>

          <span className="check-mark">✓</span>
        </div>

        <div className="validation-row">
          <div>
            <strong>Invalid Values</strong>
            <span>No invalid sensor values detected</span>
          </div>

          <span className="check-mark">✓</span>
        </div>

        <div className="validation-row">
          <div>
            <strong>Duplicate Records</strong>
            <span>No critical duplicate records detected</span>
          </div>

          <span className="check-mark">✓</span>
        </div>
      </div>
    </section>
  );
}

export default ValidationResults;