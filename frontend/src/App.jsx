import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import DashboardCards from './components/DashboardCards';
import SensorTable from './components/SensorTable';
import IngestModal from './components/IngestModal';
import SimulationControlPanel from './components/SimulationControlPanel';
import SimulationAnalyticsCard from './components/SimulationAnalyticsCard';
import { 
  fetchDashboardSummary, 
  seedSampleData,
  fetchSimulationStatus,
  fetchSimulationAnalytics,
  startSimulation,
  stopSimulation
} from './services/api';
import { AlertCircle, Waves, CheckCircle2 } from 'lucide-react';

function App() {
  const [summary, setSummary] = useState(null);
  const [simStatus, setSimStatus] = useState(null);
  const [simAnalytics, setSimAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSimProcessing, setIsSimProcessing] = useState(false);
  const [error, setError] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [countdown, setCountdown] = useState(5); // 5s auto refresh cycle
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [notification, setNotification] = useState(null);

  const loadData = useCallback(async (showLoader = false) => {
    if (showLoader) setIsRefreshing(true);
    try {
      const [dashData, simStat, simAna] = await Promise.all([
        fetchDashboardSummary(),
        fetchSimulationStatus(),
        fetchSimulationAnalytics()
      ]);
      setSummary(dashData);
      setSimStatus(simStat);
      setSimAnalytics(simAna);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch platform dashboard data:', err);
      setError('Unable to connect to FastAPI backend server. Ensure backend is running at http://localhost:8000.');
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadData(true);
  }, [loadData]);

  // Auto Refresh 5 second timer to match simulation generator loop
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          loadData(false);
          return 5;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [autoRefresh, loadData]);

  const handleManualRefresh = () => {
    setCountdown(5);
    loadData(true);
  };

  const handleStartSimulation = async (scenario) => {
    try {
      setIsSimProcessing(true);
      const res = await startSimulation(scenario);
      setSimStatus(res);
      showNotification(`Flood Simulation started in '${scenario}' scenario mode!`);
      await loadData(false);
    } catch (err) {
      console.error('Failed to start simulation:', err);
      showNotification('Failed to start simulation scenario.', 'error');
    } finally {
      setIsSimProcessing(false);
    }
  };

  const handleStopSimulation = async () => {
    try {
      setIsSimProcessing(true);
      const res = await stopSimulation();
      setSimStatus(res);
      showNotification('Flood Simulation engine stopped.');
      await loadData(false);
    } catch (err) {
      console.error('Failed to stop simulation:', err);
      showNotification('Failed to stop simulation.', 'error');
    } finally {
      setIsSimProcessing(false);
    }
  };

  const handleSeedData = async () => {
    try {
      setIsRefreshing(true);
      await seedSampleData();
      showNotification('Database successfully seeded with sample flood sensors & readings.');
      await loadData(false);
    } catch (err) {
      console.error('Seed data error:', err);
      showNotification('Notice: Database seed triggered or already populated.', 'info');
    } finally {
      setIsRefreshing(false);
    }
  };

  const showNotification = (msg, type = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 4000);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      
      {/* Top Header */}
      <Header 
        countdown={countdown}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
        onRefresh={handleManualRefresh}
        onOpenIngestModal={() => setIsModalOpen(true)}
        onSeedData={handleSeedData}
        isRefreshing={isRefreshing}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        
        {/* Toast Notification */}
        {notification && (
          <div className="mb-6 p-4 rounded-xl bg-cyan-950/90 border border-cyan-800 text-cyan-300 text-sm flex items-center justify-between shadow-xl animate-fadeIn">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-cyan-400" />
              <span>{notification.msg}</span>
            </div>
            <button onClick={() => setNotification(null)} className="text-cyan-500 hover:text-white">✕</button>
          </div>
        )}

        {/* Backend Disconnection Banner */}
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-rose-950/80 border border-rose-800 text-rose-300 text-xs sm:text-sm flex items-start gap-3 shadow-lg">
            <AlertCircle className="h-5 w-5 text-rose-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-bold">Backend Connection Warning</p>
              <p className="text-rose-400/90 mt-1">{error}</p>
            </div>
          </div>
        )}

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-4 text-slate-500">
            <Waves className="h-10 w-10 text-cyan-500 animate-bounce" />
            <p className="text-sm font-medium">Connecting to Quantum-AI Telemetry & Simulation Stream...</p>
          </div>
        ) : (
          <>
            {/* Flood & Sensor Simulation Engine Control Panel */}
            <SimulationControlPanel 
              simStatus={simStatus}
              onStartSimulation={handleStartSimulation}
              onStopSimulation={handleStopSimulation}
              isProcessing={isSimProcessing}
            />

            {/* Simulation Audit Analytics Card */}
            <SimulationAnalyticsCard analytics={simAnalytics} />

            {/* Metric Summary Cards */}
            <DashboardCards summary={summary} />

            {/* Risk Distribution Summary Bar */}
            {summary?.risk_distribution && (
              <div className="mb-6 p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Risk Level Breakdown:</span>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
                  <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-emerald-950/50 border border-emerald-900/60 text-emerald-400">
                    <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
                    <span>LOW (&lt;2m): {summary.risk_distribution.LOW}</span>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-amber-950/50 border border-amber-900/60 text-amber-400">
                    <span className="h-2 w-2 rounded-full bg-amber-400"></span>
                    <span>MEDIUM (2-4m): {summary.risk_distribution.MEDIUM}</span>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-orange-950/50 border border-orange-900/60 text-orange-400">
                    <span className="h-2 w-2 rounded-full bg-orange-400"></span>
                    <span>HIGH (4-6m): {summary.risk_distribution.HIGH}</span>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-rose-950/60 border border-rose-800/80 text-rose-300 font-bold">
                    <span className="h-2 w-2 rounded-full bg-rose-500 animate-ping"></span>
                    <span>CRITICAL (&gt;=6m): {summary.risk_distribution.CRITICAL}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Sensor Table */}
            <SensorTable readings={summary?.latest_readings || []} />
          </>
        )}

      </main>

      {/* Ingest Payload Modal */}
      <IngestModal 
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={() => {
          showNotification('Sensor payload ingested and processed successfully!');
          loadData(false);
        }}
      />

      {/* Footer */}
      <footer className="border-t border-slate-900 py-4 text-center text-xs text-slate-600 font-mono">
        Quantum-AI Flood Forecasting Platform &bull; Sensor Data Management & Simulation Module &bull; Production v1.1.0
      </footer>

    </div>
  );
}

export default App;
