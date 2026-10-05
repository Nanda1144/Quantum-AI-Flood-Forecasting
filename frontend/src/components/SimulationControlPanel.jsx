import React, { useState } from 'react';
import { Play, Square, Cpu, Zap, Activity, Clock, Layers } from 'lucide-react';
import RiskBadge from './RiskBadge';

const SimulationControlPanel = ({
  simStatus,
  onStartSimulation,
  onStopSimulation,
  isProcessing
}) => {
  const [selectedScenario, setSelectedScenario] = useState('CRITICAL_FLOOD');

  const isRunning = simStatus?.running || false;
  const currentScenario = simStatus?.scenario || 'NONE';
  const recordsCount = simStatus?.generated_records || 0;
  const lastReading = simStatus?.last_reading;

  const scenarios = [
    { value: 'NORMAL', label: 'NORMAL (Water: 0.5-2m | Rain: 0-15mm | LOW Risk)' },
    { value: 'MODERATE_RAIN', label: 'MODERATE RAIN (Water: 2-4m | Rain: 15-35mm | MEDIUM Risk)' },
    { value: 'HEAVY_RAIN', label: 'HEAVY RAIN (Water: 4-6m | Rain: 35-60mm | HIGH Risk)' },
    { value: 'CRITICAL_FLOOD', label: 'CRITICAL FLOOD (Water: 6-10m | Rain: 60-120mm | CRITICAL Risk)' }
  ];

  const handleStart = () => {
    onStartSimulation(selectedScenario);
  };

  return (
    <div className="mb-6 bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-md">
      
      {/* Panel Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-950/80 border border-cyan-800/60 text-cyan-400">
            <Cpu className="h-5 w-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white">Flood & Sensor Simulation Engine</h2>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                isRunning 
                  ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800 animate-pulse' 
                  : 'bg-slate-800 text-slate-400 border-slate-700'
              }`}>
                <span className={`h-2 w-2 rounded-full ${isRunning ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                <span>{isRunning ? 'RUNNING (5s Loop)' : 'IDLE / STOPPED'}</span>
              </span>
            </div>
            <p className="text-xs text-slate-400">Simulate synthetic flood scenarios & feed telemetry into live pipeline</p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedScenario}
            onChange={(e) => setSelectedScenario(e.target.value)}
            className="px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-xl text-slate-200 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
          >
            {scenarios.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>

          {isRunning ? (
            <button
              onClick={onStopSimulation}
              disabled={isProcessing}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-xl bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-950/40 transition active:scale-95 disabled:opacity-50"
            >
              <Square className="h-4 w-4 fill-white" />
              <span>Stop Simulation</span>
            </button>
          ) : (
            <button
              onClick={handleStart}
              disabled={isProcessing}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-slate-950 shadow-lg shadow-emerald-950/40 transition active:scale-95 disabled:opacity-50"
            >
              <Play className="h-4 w-4 fill-slate-950" />
              <span>Start Simulation</span>
            </button>
          )}

          {isRunning && (
            <button
              onClick={handleStart}
              disabled={isProcessing}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-xl bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 transition"
              title="Apply newly selected scenario mode"
            >
              <Zap className="h-3.5 w-3.5 text-cyan-400" />
              <span>Change Scenario</span>
            </button>
          )}
        </div>
      </div>

      {/* Status Stats & Ticker */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        
        {/* Current Scenario Badge */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-3 flex items-center justify-between">
          <div>
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">Active Mode</span>
            <span className="text-sm font-extrabold text-cyan-300 font-mono">{currentScenario}</span>
          </div>
          <Layers className="h-5 w-5 text-slate-600" />
        </div>

        {/* Total Records Counter */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-3 flex items-center justify-between">
          <div>
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">Session Generated Records</span>
            <span className="text-base font-extrabold text-white font-mono">{recordsCount} records</span>
          </div>
          <Activity className="h-5 w-5 text-slate-600" />
        </div>

        {/* Last Generated Ticker */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-3 flex items-center justify-between">
          <div className="truncate">
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">Latest Generator Reading</span>
            {lastReading ? (
              <div className="flex items-center gap-2 mt-0.5 text-xs font-mono text-slate-300 truncate">
                <span className="font-bold text-white">{lastReading.sensor_code}</span>
                <span>Water: {lastReading.water_level}m</span>
                <RiskBadge riskLevel={lastReading.generated_risk} />
              </div>
            ) : (
              <span className="text-xs text-slate-500 italic">No telemetry generated yet</span>
            )}
          </div>
          <Clock className="h-5 w-5 text-slate-600 flex-shrink-0" />
        </div>

      </div>

    </div>
  );
};

export default SimulationControlPanel;
