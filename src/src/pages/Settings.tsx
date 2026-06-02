/**
 * Settings page — safety and configuration placeholder.
 *
 * Future implementation will support:
 * - Scope management (create / delete)
 * - Safety threshold configuration
 * - Data encryption settings
 * - Sidecar status monitoring
 * - Auto-shutdown timer
 */
function Settings(): React.ReactElement {
  return (
    <div className="page-settings">
      <h2>安全设置</h2>
      <p className="text-muted">管理 Scope、安全阈值、加密选项和运行状态。</p>
      <div className="placeholder-card">
        <span className="placeholder-icon">⚙️</span>
        <span>Scope 管理 · 安全阈值 · 加密配置 · Sidecar 状态</span>
      </div>
    </div>
  );
}

export default Settings;