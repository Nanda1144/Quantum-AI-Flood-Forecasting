import React from 'react';
import { Activity, RefreshCw, PlusCircle, Database, ShieldAlert } from 'lucide-react';

const Header = ({ 
  countdown, 
  autoRefresh, 
  setAutoRefresh, 
  onRefresh, 
  onOpenIngestModal, 
  onSeedData,
  isRefreshing 
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          
          {/* Logo & Platform Name */}
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-cyan-600 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 ring-1 ring-cyan-400/30">
              <Activity className="h-6 w-6 text-white animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold bg-gradient-to-r from-white via-slate-200 to-cyan-300 bg-clip-text text-transparent">
                  Quantum-AI Flood Telemetry
                </h1>
                <span className="px-2 py-0.5 text-[10px] font-mono font-semibold rounded bg-cyan-950/80 text-cyan-400 border border-cyan-800/60">
                  REAL-TIME MODULE
                </span>
              </div>
              <p className="text-xs text-slate-400">Sensor Data Ingestion, Risk Assessment & Disaster Response Engine</p>
            </div>
          </div>

          {/* Actions & Refresh Controls */}
          <div className="flex flex-wrap items-center gap-3">
            
            {/* Auto Refresh Toggle */}
            <div className="flex items-center gap-2 bg-slate-800/80 border border-slate-700/60 px-3 py-1.5 rounded-lg text-xs">
              <button 
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${autoRefresh ? 'bg-cyan-500' : 'bg-slate-700'}`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition duration-200 ease-in-out ${autoRefresh ? 'translate-x-4' : 'translate-x-0'}`} />
              </button>
              <span className="text-slate-300 font-medium">Auto (10s)</span>
              {autoRefresh && (
                <span className="ml-1 text-cyan-400 font-mono font-bold w-4">
                  {countdown}s
                </span>
              )}
            </div>

            {/* Manual Refresh Button */}
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? 'animate-spin text-cyan-400' : ''}`} />
              <span>Sync</span>
            </button>

            {/* Seed DB Button */}
            <button
              onClick={onSeedData}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
              title="Populate database with sample sensors and readings"
            >
              <Database className="h-3.5 w-3.5 text-slate-400" />
              <span>Seed Data</span>
            </button>

            {/* Ingest Telemetry Modal Trigger */}
            <button
              onClick={onOpenIngestModal}
              className="inline-flex items-center gap-2 px-4 py-1.5 text-xs font-semibold rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white shadow-md shadow-cyan-900/30 transition hover:scale-[1.02] active:scale-[0.98]"
            >
              <PlusCircle className="h-4 w-4" />
              <span>Ingest Reading</span>
            </button>

          </div>

        </div>
      </div>
    </header>
  );
};

export default Header;
