
import { useState } from "react";
import Dashboard from "./pages/Dashboard";
import DataManagement from "./pages/DataManagement";
import ExistingSolutions from "./pages/ExistingSolutions";
import Sidebar from "./components/Sidebar";

function App() {
  const [currentPage, setCurrentPage] = useState("Dashboard");

  const renderPage = () => {
    switch (currentPage) {
      case "Data Management":
        return <DataManagement />;

      case "Existing Solutions":
        return <ExistingSolutions />;

      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="app-layout">
      <Sidebar
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />

      <main className="main-content">
        {renderPage()}
      </main>
    </div>
  );
}

export default App;

