import { useState } from 'react';
import { analyzeGpx } from '../services/api';

function GpxUpload({ onProfileAnalyzed }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [fileName, setFileName] = useState(null);

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.gpx')) {
      setError('Please select a GPX file');
      return;
    }

    setFileName(file.name);
    setLoading(true);
    setError(null);

    try {
      const profile = await analyzeGpx(file);
      onProfileAnalyzed(profile);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to analyze GPX file');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="gpx-upload">
      <h3>Upload GPX File</h3>
      <p className="description">
        Upload a GPX file from a race or route to analyze its elevation profile.
      </p>

      <label className="file-input-label">
        <input
          type="file"
          accept=".gpx"
          onChange={handleFileChange}
          disabled={loading}
        />
        <span className="file-input-button">
          {loading ? 'Analyzing...' : 'Choose GPX File'}
        </span>
      </label>

      {fileName && !error && (
        <p className="file-name">Selected: {fileName}</p>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  );
}

export default GpxUpload;
