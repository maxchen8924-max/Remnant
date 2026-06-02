import { NavLink } from "react-router-dom";

/**
 * Sidebar navigation component for Remnant.
 * Provides navigation links to all major sections.
 */
function Sidebar(): React.ReactElement {
  const navItems = [
    { path: "/import", label: "数据导入", icon: "📥" },
    { path: "/timeline", label: "记忆时间线", icon: "🕐" },
    { path: "/query", label: "问答", icon: "💬" },
    { path: "/evidence", label: "证据卡片", icon: "🔍" },
    { path: "/settings", label: "安全设置", icon: "⚙️" },
    { path: "/destroy", label: "数据销毁", icon: "🧨" },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1 className="sidebar-title">残响</h1>
        <span className="sidebar-subtitle">Remnant</span>
      </div>
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }: { isActive: boolean }) =>
              `sidebar-nav-item ${isActive ? "active" : ""}`
            }
          >
            <span className="sidebar-nav-icon">{item.icon}</span>
            <span className="sidebar-nav-label">{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="sidebar-version">v0.1.0</span>
      </div>
    </aside>
  );
}

export default Sidebar;