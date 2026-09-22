import {
  LayoutDashboard,
  Database,
  Lightbulb,
  History,
  CloudRain,
  Map,
  Radio,
  Cpu,
  Bell,
} from "lucide-react";

function Sidebar({ currentPage, setCurrentPage }) {
  const menuItems = [
    { label: "Dashboard", icon: LayoutDashboard },
    { label: "Data Management", icon: Database },
    { label: "Existing Solutions", icon: Lightbulb },
    { label: "Import History", icon: History },
    { label: "Flood Forecasting", icon: CloudRain },
    { label: "Risk Map", icon: Map },
    { label: "Sensors", icon: Radio },
    { label: "Optimization", icon: Cpu },
    { label: "Alerts", icon: Bell },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-icon">Q</div>

        <div>
          <h2>Q-FLARE</h2>
          <span>Flood Intelligence</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {menuItems.map((item) => {
          const Icon = item.icon;

          return (
            <button
              key={item.label}
              className={`sidebar-item ${
                currentPage === item.label ? "active" : ""
              }`}
              onClick={() => setCurrentPage(item.label)}
            >
              <Icon size={19} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <span className="status-dot"></span>
        Platform Online
      </div>
    </aside>
  );
}

export default Sidebar;