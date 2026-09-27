import React, { useState } from 'react';
import { X, Send, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { postLiveSensorData } from '../services/api';

const IngestModal = ({ isOpen, onClose, onSuccess }) => {
  const [sensorId, setSensorId] = useState('S101');
  const [waterLevel, setWaterLevel] = useState(5.4);
  const [rainfall, setRainfall] = useState(42.0);
  const [flowRate, setFlowRate] = useState(3.1);
  const [temperature, setTemperature] = useState(29.0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  if (!isOpen) return null;

  const quickPresets = [
    { label: 'LOW Risk (<2m)', water: 1.5, rain: 5.0, flow: 1.1, temp: 25.0 },
    { label: 'MEDIUM Risk (2-4m)', water: 3.2, rain: 22.0, flow: 2.4, temp: 27.0 },
    { label: 'HIGH Risk (4-6m)', water: 5.4, rain: 42.0, flow: 3.1, temp: 29.0 },
    { label: 'CRITICAL (>=6m)', water: 7.2, rain: 78.0, flow: 6.5, temp: 31.0 }
  ];

  const applyPreset = (p) => {
    setWaterLevel(p.water);
    setRainfall(p.rain);
    setFlowRate(p.flow);
    setTemperature(p.temp);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    const payload = {
      sensor_id: sensorId,
      water_level: parseFloat(waterLevel),
      rainfall: parseFloat(rainfall),
      flow_rate: parseFloat(flowRate),
      temperature: parseFloat(temperature),
      timestamp: new Date().toISOString()
    };

    try {
      const response = await postLiveSensorData(payload);
      setSuccessMsg(`Telemetry ingested! Processed Risk: ${response.risk_level} (Status: ${response.status})`);
      setTimeout(() => {
        onSuccess();
        onClose();
        setSuccessMsg(null);
      }, 1200);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setErrorMsg(typeof detail === 'string' ? detail : 'Validation error occurred while ingesting payload.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative">
        
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
          <div>
            <h3 className="text-lg font-bold text-white">Ingest Live Telemetry Payload</h3>
            <p className="text-xs text-slate-400">REST API Endpoint: <code className="text-cyan-400 font-mono">POST /api/live-sensor</code></p>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Quick Presets */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Preset Risk Test Cases:</label>
          <div className="grid grid-cols-2 gap-2">
            {quickPresets.map((p, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => applyPreset(p)}
                className="px-2.5 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 text-left transition"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Feedback Alerts */}
        {errorMsg && (
          <div className="mb-4 p-3 rounded-lg bg-rose-950/80 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 flex-shrink-0 text-rose-400" />
            <span>{errorMsg}</span>
          </div>
        )}
        {successMsg && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-950/80 border border-emerald-800/80 text-emerald-300 text-xs flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-emerald-400" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Sensor Code (sensor_id)</label>
            <input
              type="text"
              required
              value={sensorId}
              onChange={(e) => setSensorId(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-white font-mono focus:border-cyan-500 focus:outline-none"
              placeholder="e.g. S101, S102"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Water Level (m)</label>
              <input
                type="number"
                step="0.1"
                min="0"
                required
                value={waterLevel}
                onChange={(e) => setWaterLevel(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-white font-mono focus:border-cyan-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Rainfall (mm)</label>
              <input
                type="number"
                step="0.1"
                min="0"
                required
                value={rainfall}
                onChange={(e) => setRainfall(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-white font-mono focus:border-cyan-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Flow Rate (m³/s)</label>
              <input
                type="number"
                step="0.1"
                min="0"
                required
                value={flowRate}
                onChange={(e) => setFlowRate(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-white font-mono focus:border-cyan-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Temperature (°C)</label>
              <input
                type="number"
                step="0.1"
                required
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-white font-mono focus:border-cyan-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 px-5 py-2 text-xs font-bold rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 shadow-md shadow-cyan-500/20 transition disabled:opacity-50"
            >
              <Send className="h-3.5 w-3.5" />
              <span>{isSubmitting ? 'Ingesting...' : 'Ingest Reading'}</span>
            </button>
          </div>
        </form>

      </div>
    </div>
  );
};

export default IngestModal;
