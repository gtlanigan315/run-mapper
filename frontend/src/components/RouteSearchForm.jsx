import { useState } from 'react';
import { findRoutes } from '../services/api';

function RouteSearchForm({ onRoutesFound, onSearchStart }) {
  const [location, setLocation] = useState('');
  const [distance, setDistance] = useState(5);
  const [elevationGain, setElevationGain] = useState(50);
  const [numResults, setNumResults] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!location.trim()) {
      setError('Please enter a location');
      return;
    }

    setLoading(true);
    setError(null);
    onSearchStart?.();

    try {
      const response = await findRoutes(location, distance, elevationGain, numResults);
      onRoutesFound(response.routes);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to find routes');
      onRoutesFound([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="route-search-form">
      <h3>Find Routes</h3>
      <p className="description">
        Search for running routes near a location that match your criteria.
      </p>

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="location">Location</label>
          <input
            type="text"
            id="location"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="e.g., Boston, MA"
            disabled={loading}
          />
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="distance">Distance (km)</label>
            <input
              type="number"
              id="distance"
              value={distance}
              onChange={(e) => setDistance(parseFloat(e.target.value) || 0)}
              min="0.5"
              max="50"
              step="0.5"
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="elevation">Elevation Gain (m)</label>
            <input
              type="number"
              id="elevation"
              value={elevationGain}
              onChange={(e) => setElevationGain(parseFloat(e.target.value) || 0)}
              min="0"
              max="2000"
              step="10"
              disabled={loading}
            />
          </div>
        </div>

        <div className="form-group">
          <label htmlFor="numResults">Number of Results</label>
          <input
            type="number"
            id="numResults"
            value={numResults}
            onChange={(e) => setNumResults(parseInt(e.target.value) || 5)}
            min="1"
            max="20"
            disabled={loading}
          />
        </div>

        <button type="submit" disabled={loading}>
          {loading ? 'Searching...' : 'Find Routes'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}
    </div>
  );
}

export default RouteSearchForm;
