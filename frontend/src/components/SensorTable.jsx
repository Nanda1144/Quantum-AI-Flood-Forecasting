import React, { useState } from 'react';
import { Search, ArrowUpDown, MapPin, Gauge, Thermometer, Droplet, Clock } from 'lucide-react';
import RiskBadge from './RiskBadge';

const SensorTable = ({ readings }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterRisk, setFilterRisk] = useState('ALL');

  const filteredReadings = (readings || []).filter((r) => {
    const matchesSearch = 
      r.sensor_code?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.location_name?.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRisk = filterRisk === 'ALL' || r.risk_level === filterRisk;
    return matchesSearch && matchesRisk;
  });

  const formatDate = (isoString) => {
    if (!isoString) return 'N/A';
    try {
      const date = new Date(isoString);
      return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden backdrop-blur-sm shadow-xl">
      
      {/* Table Header & Controls */}
      <div className="p-4 sm:p-5 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <span>Live Flood Monitoring Sensors</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
              {filteredReadings.length} records
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">Real-time water level, rainfall, flow rate, and risk evaluation stream</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Search Input */}
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Filter by ID or location..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-700/70 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 w-48 sm:w-60"
            />
          </div>

          {/* Risk Level Filter Pill Group */}
          <div className="flex items-center gap-1 bg-slate-950 p-1 border border-slate-800 rounded-lg text-xs font-medium">
            {['ALL', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((level) => (
              <button
                key={level}
                onClick={() => setFilterRisk(level)}
                className={`px-2.5 py-1 rounded-md transition ${
                  filterRisk === level 
                    ? 'bg-slate-800 text-cyan-400 font-semibold shadow-sm' 
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Table View */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950/70 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
            <tr>
              <th className="py-3.5 px-4">Sensor ID</th>
              <th className="py-3.5 px-4">Location</th>
              <th className="py-3.5 px-4 text-right">Water Level (m)</th>
              <th className="py-3.5 px-4 text-right">Rainfall (mm)</th>
              <th className="py-3.5 px-4 text-right">Flow Rate (m³/s)</th>
              <th className="py-3.5 px-4 text-right">Temp (°C)</th>
              <th className="py-3.5 px-4 text-center">Risk Level</th>
              <th className="py-3.5 px-4 text-center">Status</th>
              <th className="py-3.5 px-4 text-right">Timestamp</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
            {filteredReadings.length === 0 ? (
              <tr>
                <td colSpan="9" className="py-8 text-center text-slate-500 font-sans">
                  No telemetry records found matching selected filters.
                </td>
              </tr>
            ) : (
              filteredReadings.map((reading) => {
                const isCritical = reading.risk_level === 'CRITICAL';
                return (
                  <tr 
                    key={reading.id || reading.sensor_code}
                    className={`hover:bg-slate-800/50 transition-colors ${isCritical ? 'bg-rose-950/20' : ''}`}
                  >
                    <td className="py-3.5 px-4 font-bold text-white flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full bg-cyan-400"></span>
                      <span>{reading.sensor_code}</span>
                    </td>
                    <td className="py-3.5 px-4 font-sans text-slate-300">
                      <div className="flex items-center gap-1.5 truncate max-w-[200px]" title={reading.location_name}>
                        <MapPin className="h-3.5 w-3.5 text-slate-500 flex-shrink-0" />
                        <span className="truncate">{reading.location_name || 'N/A'}</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-right font-bold text-white">
                      {reading.water_level.toFixed(2)}
                    </td>
                    <td className="py-3.5 px-4 text-right text-cyan-300">
                      {reading.rainfall.toFixed(1)}
                    </td>
                    <td className="py-3.5 px-4 text-right text-slate-300">
                      {reading.flow_rate.toFixed(1)}
                    </td>
                    <td className="py-3.5 px-4 text-right text-slate-400">
                      {reading.temperature.toFixed(1)}
                    </td>
                    <td className="py-3.5 px-4 text-center font-sans">
                      <RiskBadge riskLevel={reading.risk_level} showPulse={isCritical} />
                    </td>
                    <td className="py-3.5 px-4 text-center font-sans">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        reading.status === 'CRITICAL' 
                          ? 'bg-rose-900/80 text-rose-300 border border-rose-700' 
                          : 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/60'
                      }`}>
                        {reading.status}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right text-slate-400 font-sans text-[11px]">
                      <div className="flex items-center justify-end gap-1">
                        <Clock className="h-3 w-3 text-slate-500" />
                        <span>{formatDate(reading.recorded_at)}</span>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SensorTable;
