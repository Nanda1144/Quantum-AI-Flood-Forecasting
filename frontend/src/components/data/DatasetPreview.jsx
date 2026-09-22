function DatasetPreview({ preview, dataset }) {
  const rows =
    preview?.preview_rows ||
    preview?.data ||
    preview?.rows ||
    [];

  const previewRows = Array.isArray(rows) ? rows : [];

  const columns =
    previewRows.length > 0
      ? Object.keys(previewRows[0])
      : [];

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
          {previewRows.length} records
        </span>
      </div>

      {!dataset && (
        <div className="preview-empty-state">
          <p>Select a dataset to preview its records.</p>
        </div>
      )}

      {dataset && previewRows.length === 0 && (
        <div className="preview-empty-state">
          <p>No preview records available for this dataset.</p>
        </div>
      )}

      {dataset && previewRows.length > 0 && (
        <div className="preview-table-wrapper">
          <table className="preview-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>
                    {column
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (char) => char.toUpperCase())}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {previewRows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {columns.map((column) => (
                    <td key={`${rowIndex}-${column}`}>
                      {row[column] !== null &&
                      row[column] !== undefined
                        ? String(row[column])
                        : "-"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default DatasetPreview;