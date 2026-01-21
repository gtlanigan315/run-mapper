import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1';

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

export const findRoutes = async (
  location,
  targetDistanceKm,
  targetElevationGainM,
  numResults = 5,
  stravaAccessToken = null,
  targetElevationLossM = 0,
  targetProfile = null
) => {
  const payload = {
    location,
    target_distance_km: targetDistanceKm,
    target_elevation_gain_m: targetElevationGainM,
    target_elevation_loss_m: targetElevationLossM,
    num_results: numResults,
  };

  if (stravaAccessToken) {
    payload.strava_access_token = stravaAccessToken;
  }

  if (targetProfile && targetProfile.length > 0) {
    payload.target_profile = targetProfile;
  }

  const response = await api.post('/find-routes', payload, {
    timeout: 180000, // 3 minute timeout - route finding + elevation can be slow
  });
  return response.data;
};

// Strava OAuth functions
export const getStravaAuthUrl = async () => {
  const response = await api.get('/strava/auth-url');
  return response.data.url;
};

export const exchangeStravaToken = async (code) => {
  const response = await api.post(`/strava/exchange-token?code=${encodeURIComponent(code)}`);
  return response.data;
};

export const refreshStravaToken = async (refreshToken) => {
  const response = await api.post(`/strava/refresh-token?refresh_token=${encodeURIComponent(refreshToken)}`);
  return response.data;
};

// Strava token management (localStorage)
const STRAVA_TOKEN_KEY = 'strava_tokens';

export const saveStravaTokens = (tokens) => {
  localStorage.setItem(STRAVA_TOKEN_KEY, JSON.stringify(tokens));
};

export const getStravaTokens = () => {
  const tokens = localStorage.getItem(STRAVA_TOKEN_KEY);
  return tokens ? JSON.parse(tokens) : null;
};

export const clearStravaTokens = () => {
  localStorage.removeItem(STRAVA_TOKEN_KEY);
};

export const isStravaTokenValid = () => {
  const tokens = getStravaTokens();
  if (!tokens) return false;
  // Check if token is expired (with 5 minute buffer)
  const now = Math.floor(Date.now() / 1000);
  return tokens.expires_at > now + 300;
};

export const getValidStravaToken = async () => {
  const tokens = getStravaTokens();
  if (!tokens) return null;

  const now = Math.floor(Date.now() / 1000);

  // If token is still valid, return it
  if (tokens.expires_at > now + 300) {
    return tokens.access_token;
  }

  // Try to refresh the token
  try {
    const newTokens = await refreshStravaToken(tokens.refresh_token);
    saveStravaTokens(newTokens);
    return newTokens.access_token;
  } catch (error) {
    console.error('Failed to refresh Strava token:', error);
    clearStravaTokens();
    return null;
  }
};

export default api;
