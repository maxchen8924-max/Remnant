/**
 * Destroy page — data destruction placeholder.
 *
 * Future implementation will support:
 * - Scope-level secure deletion (crypto shredding)
 * - Confirmation workflow with safety evaluation
 * - Destruction audit log
 */
function Destroy(): React.ReactElement {
  return (
    <div className="page-destroy">
      <h2>数据销毁</h2>
      <p className="text-muted">安全销毁指定 Scope 下的所有数据，操作不可逆。</p>
      <div className="placeholder-card destructive">
        <span className="placeholder-icon">🧨</span>
        <span>Scope 级加密粉碎 · 安全评估 · 审计日志</span>
      </div>
    </div>
  );
}

export default Destroy;