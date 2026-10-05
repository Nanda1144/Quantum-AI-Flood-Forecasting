import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const fetchDashboardSummary = async () => {
  const response = await api.get('/dashboard');
  return response.data;
};

export const fetchLatestData = async () => {
  const response = await api.get('/latest-data');
  return response.data;
};

export const fetchSensors = async () => {
  const response = await api.get('/sensors');
  return response.data;
};

export const postLiveSensorData = async (payload) => {
  const response = await api.post('/live-sensor', payload);
  return response.data;
};

export const seedSampleData = async () => {
  const response = await api.post('/seed');
  return response.data;
};

// Simulation Engine API calls
export const startSimulation = async (scenario) => {
  const response = await api.post('/simulation/start', { scenario });
  return response.data;
};

export const stopSimulation = async () => {
  const response = await api.post('/simulation/stop');
  return response.data;
};

export const fetchSimulationStatus = async () => {
  const response = await api.get('/simulation/status');
  return response.data;
};

export const fetchSimulationHistory = async () => {
  const response = await api.get('/simulation/history');
  return response.data;
};

export const fetchSimulationAnalytics = async () => {
  const response = await api.get('/simulation/analytics');
  return response.data;
};

export default api;
