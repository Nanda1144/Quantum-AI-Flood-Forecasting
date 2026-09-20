function DataQualityCard() {
  return (
    <section className="data-quality-card">
      <div className="section-header">
        <div>
          <h2>Data Quality</h2>
          <p>Overview of the quality and completeness of uploaded datasets.</p>
        </div>

        <span className="quality-status">Good Quality</span>
      </div>

      <div className="quality-grid">
        <div className="quality-item">
          <span className="quality-label">Completeness</span>
          <strong>92%</strong>
          <div className="quality-bar">
            <div className="quality-fill" style={{ width: "92%" }}></div>
          </div>
        </div>

        <div className="quality-item">
          <span className="quality-label">Valid Records</span>
          <strong>96%</strong>
          <div className="quality-bar">
            <div className="quality-fill" style={{ width: "96%" }}></div>
          </div>
        </div>

        <div className="quality-item">
          <span className="quality-label">Missing Values</span>
          <strong>4%</strong>
          <div className="quality-bar">
            <div className="quality-fill" style={{ width: "4%" }}></div>
          </div>
        </div>

        <div className="quality-item">
          <span className="quality-label">Duplicate Records</span>
          <strong>2%</strong>
          <div className="quality-bar">
            <div className="quality-fill" style={{ width: "2%" }}></div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default DataQualityCard;