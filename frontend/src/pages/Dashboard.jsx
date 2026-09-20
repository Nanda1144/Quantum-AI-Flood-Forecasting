import {
  Database,
  CloudRain,
  Map,
  Activity,
  AlertTriangle,
  Radio,
} from "lucide-react";

function Dashboard() {
  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <h1>Q-FLARE Dashboard</h1>
          <p>
            Quantum-AI Flood Forecasting & Disaster-Response Platform
          </p>
        </div>

        <div className="system-status">
          <span className="status-dot"></span>
          System Online
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <Database size={28} />
          <div>
            <span>Total Datasets</span>
            <strong>0</strong>
          </div>
        </div>

        <div className="stat-card">
          <CloudRain size={28} />
          <div>
            <span>Forecast Status</span>
            <strong>Ready</strong>
          </div>
        </div>

        <div className="stat-card">
          <Map size={28} />
          <div>
            <span>GIS Status</span>
            <strong>Ready</strong>
          </div>
        </div>

        <div className="stat-card">
          <Radio size={28} />
          <div>
            <span>Active Sensors</span>
            <strong>0</strong>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-card">
          <div className="card-title">
            <Activity size={22} />
            Platform Workflow
          </div>

          <div className="workflow">
            <div>DATA</div>
            <span>→</span>
            <div>FORECASTING</div>
            <span>→</span>
            <div>RISK</div>
            <span>→</span>
            <div>GIS</div>
            <span>→</span>
            <div>RESPONSE</div>
          </div>
        </div>

        <div className="dashboard-card">
          <div className="card-title">
            <AlertTriangle size={22} />
            Current Alerts
          </div>

          <div className="empty-state">
            No active flood alerts
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;