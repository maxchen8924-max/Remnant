import { Routes, Route, Navigate } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import SafetyBanner from "./components/SafetyBanner";
import Import from "./pages/Import";
import Timeline from "./pages/Timeline";
import Query from "./pages/Query";
import Evidence from "./pages/Evidence";
import ScopeManage from "./pages/ScopeManage";
import ScopeCreate from "./pages/ScopeCreate";
import Destroy from "./pages/Destroy";

/**
 * Root application layout for Remnant.
 * Provides sidebar navigation, header, and safety banner
 * alongside a main content area that renders routed pages.
 */
function App(): React.ReactElement {
  return (
    <div className="app-layout">
      <SafetyBanner />
      <div className="app-body">
        <Sidebar />
        <div className="app-main">
          <Header />
          <main className="app-content">
            <Routes>
              <Route path="/" element={<Navigate to="/timeline" replace />} />
              <Route path="/import" element={<Import />} />
              <Route path="/timeline" element={<Timeline />} />
              <Route path="/query" element={<Query />} />
              <Route path="/evidence" element={<Evidence />} />
              <Route path="/settings" element={<ScopeManage />} />
              <Route path="/scope/create" element={<ScopeCreate />} />
              <Route path="/destroy" element={<Destroy />} />
            </Routes>
          </main>
        </div>
      </div>
    </div>
  );
}

export default App;