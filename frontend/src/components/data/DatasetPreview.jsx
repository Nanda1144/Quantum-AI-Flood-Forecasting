function DatasetPreview() {
  const previewData = [
    {
      date: "2026-09-18",
      location: "Vijayawada",
      rainfall: "42.6 mm",
      riverLevel: "12.4 m",
      temperature: "29.1 °C",
      flowRate: "842 m³/s",
    },
    {
      date: "2026-09-18",
      location: "Rajahmundry",
      rainfall: "38.2 mm",
      riverLevel: "11.8 m",
      temperature: "28.7 °C",
      flowRate: "765 m³/s",
    },
    {
      date: "2026-09-17",
      location: "Amalapuram",
      rainfall: "51.4 mm",
      riverLevel: "10.9 m",
      temperature: "30.2 °C",
      flowRate: "698 m³/s",
    },
    {
      date: "2026-09-17",
      location: "Eluru",
      rainfall: "31.7 mm",
      riverLevel: "9.6 m",
      temperature: "29.8 °C",
      flowRate: "621 m³/s",
    },
  ];

  return (
    <section className="dataset-preview-card">
      <div className="section-header">
        <div>
          <h2>Dataset Preview</h2>
          <p>
            Preview of recent records from the selected flood dataset.
          </p>
        </div>

        <span className="preview-count">
          4 records
        </span>
      </div>

      <div className="preview-table-wrapper">
        <table className="preview-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Location</th>
              <th>Rainfall</th>
              <th>River Level</th>
              <th>Temperature</th>
              <th>Flow Rate</th>
            </tr>
          </thead>

          <tbody>
            {previewData.map((row, index) => (
              <tr key={index}>
                <td>{row.date}</td>
                <td>{row.location}</td>
                <td>{row.rainfall}</td>
                <td>{row.riverLevel}</td>
                <td>{row.temperature}</td>
                <td>{row.flowRate}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default DatasetPreview;
