
import { useState } from "react";
import DatasetUpload from "../components/data/DatasetUpload";
import DatasetTable from "../components/data/DatasetTable";
import DataQualityCard from "../components/data/DataQualityCard";
import ValidationResults from "../components/data/ValidationResults";
import DatasetPreview from "../components/data/DatasetPreview";

function DataManagement() {
  const [datasetRefreshKey, setDatasetRefreshKey] = useState(0);

  const handleUploadSuccess = () => {
    setDatasetRefreshKey((previousKey) => previousKey + 1);
  };

  return (
    <div className="data-management-page">
      <div className="page-heading">
        <div>
          <h1>Data Management</h1>
          <p>
            Upload, inspect, validate, and manage flood-related datasets.
          </p>
        </div>
      </div>

      <DatasetUpload
        onUploadSuccess={handleUploadSuccess}
      />

      <DataQualityCard />

      <ValidationResults />

      <DatasetPreview />

      <DatasetTable
        refreshKey={datasetRefreshKey}
      />
    </div>
  );
}

export default DataManagement;

