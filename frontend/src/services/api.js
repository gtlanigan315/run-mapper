import axios from 'axios';

const API_BASE_URL = 'http://127.0.0.1:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
});

export const checkHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

export const analyzeGpx = async (file) => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await api.post('/analyze-gpx', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const findRoutes = async (location, targetDistanceKm, targetElevationGainM, numResults = 5) => {
  const response = await api.post('/find-routes', {
    location,
    target_distance_km: targetDistanceKm,
    target_elevation_gain_m: targetElevationGainM,
    num_results: numResults,
  }, {
    timeout: 120000, // 2 minute timeout - route finding can be slow
  });
  return response.data;
};

export default api;
