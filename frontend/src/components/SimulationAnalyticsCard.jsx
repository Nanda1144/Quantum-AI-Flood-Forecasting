import React from 'react';
import { History, Droplets, CloudRain, ShieldAlert, Database } from 'lucide-react';
import RiskBadge from './RiskBadge';

const SimulationAnalyticsCard = ({ analytics }) => {
  const totalSessions = analytics?.total_sessions || 0;
  const avgWaterLevel = analytics?.avg_water_level !== undefined ? analytics.avg_water_level.toFixed(2) : '0.00';
  const avgRainfall = analytics?.avg_rainfall !== undefined ? analytics.avg_rainfall.toFixed(1) : '0.0';
  const highestRisk = analytics?.highest_risk_generated || 'LOW';
  const totalRecords = analytics?.total_records_generated || 0;

  return (
    <div className="mb-6 bg-slate-900/60 border border-slate-800/80 rounded-xl p-4 backdrop-blur-sm">
      <div className="flex items-center gap-2 mb-3 border-b border-slate-800/60 pb-2">
        <History className="h-4 w-4 text-cyan-400" />
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
          Simulation Analytics & Audit Summary
        </h3>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
        
        {/* Total Sessions */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <span className="text-[11px] text-slate-400 block font-medium">Total Sessions</span>
          <span className="text-lg font-extrabold text-white font-mono mt-1 block">{totalSessions}</span>
        </div>

        {/* Avg Water Level */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <span className="text-[11px] text-slate-400 block font-medium">Avg Water Level</span>
          <div className="flex items-center gap-1 mt-1 font-mono">
            <Droplets className="h-3.5 w-3.5 text-cyan-400" />
            <span className="text-base font-bold text-cyan-300">{avgWaterLevel} m</span>
          </div>
        </div>

        {/* Avg Rainfall */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <span className="text-[11px] text-slate-400 block font-medium">Avg Rainfall</span>
          <div className="flex items-center gap-1 mt-1 font-mono">
            <CloudRain className="h-3.5 w-3.5 text-indigo-400" />
            <span className="text-base font-bold text-indigo-300">{avgRainfall} mm</span>
          </div>
        </div>

        {/* Highest Risk Generated */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <span className="text-[11px] text-slate-400 block font-medium">Peak Risk Triggered</span>
          <div className="mt-1">
            <RiskBadge riskLevel={highestRisk} showPulse={highestRisk === 'CRITICAL'} />
          </div>
        </div>

        {/* Total Records Generated */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <span className="text-[11px] text-slate-400 block font-medium">Total Logs Saved</span>
          <div className="flex items-center gap-1 mt-1 font-mono">
            <Database className="h-3.5 w-3.5 text-emerald-400" />
            <span className="text-base font-extrabold text-white">{totalRecords}</span>
          </div>
        </div>

      </div>
    </div>
  );
};

export default SimulationAnalyticsCard;
