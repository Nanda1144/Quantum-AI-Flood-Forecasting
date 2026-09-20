
import { useRef, useState } from "react";
import {
  Upload,
  FileText,
  X,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { uploadDataset } from "../../services/api";

function DatasetUpload({ onUploadSuccess }) {
  const fileInputRef = useRef(null);

  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState("");
  const [uploadError, setUploadError] = useState("");

  const handleFileChange = (event) => {
    const file = event.target.files[0];

    setUploadSuccess("");
    setUploadError("");

    if (!file) {
      return;
    }

    const allowedTypes = [".csv", ".json"];
    const fileName = file.name.toLowerCase();

    const isValidFile = allowedTypes.some((extension) =>
      fileName.endsWith(extension)
    );

    if (!isValidFile) {
      setUploadError("Please select a CSV or JSON file.");
      setSelectedFile(null);
      return;
    }

    setSelectedFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadError("Please select a dataset first.");
      return;
    }

    setUploading(true);
    setUploadSuccess("");
    setUploadError("");

    try {
      const result = await uploadDataset(selectedFile);

      console.log("Dataset upload response:", result);

      setUploadSuccess("Dataset uploaded successfully.");

      if (onUploadSuccess) {
        onUploadSuccess();
      }
    } catch (error) {
      console.error("Dataset upload error:", error);

      setUploadError(
        error.message || "Unable to upload dataset."
      );
    } finally {
      setUploading(false);
    }
  };

  const removeFile = () => {
    setSelectedFile(null);
    setUploadSuccess("");
    setUploadError("");

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="upload-card">
      <div className="upload-header">
        <div>
          <h2>Upload Dataset</h2>
          <p>
            Upload CSV or JSON data for flood forecasting and analysis.
          </p>
        </div>
      </div>

      {!selectedFile ? (
        <div
          className="upload-area"
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload size={34} />

          <h3>Choose a dataset</h3>

          <p>
            Drag and drop your file here or click to browse
          </p>

          <span>Supported formats: CSV, JSON</span>

          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.json"
            onChange={handleFileChange}
            hidden
          />
        </div>
      ) : (
        <>
          <div className="selected-file">
            <div className="file-info">
              <FileText size={28} />

              <div>
                <strong>{selectedFile.name}</strong>

                <span>
                  {(selectedFile.size / 1024).toFixed(1)} KB
                </span>
              </div>
            </div>

            <button
              type="button"
              className="remove-file"
              onClick={removeFile}
              disabled={uploading}
            >
              <X size={18} />
            </button>
          </div>

          <button
            type="button"
            className="upload-button"
            onClick={handleUpload}
            disabled={uploading}
          >
            {uploading ? "Uploading..." : "Upload Dataset"}
          </button>
        </>
      )}

      {uploadSuccess && (
        <div className="upload-message success-message">
          <CheckCircle size={18} />
          <span>{uploadSuccess}</span>
        </div>
      )}

      {uploadError && (
        <div className="upload-message error-message">
          <AlertCircle size={18} />
          <span>{uploadError}</span>
        </div>
      )}
    </div>
  );
}

export default DatasetUpload;
