/**
 * Timeline page — memory timeline placeholder.
 *
 * Future implementation will display:
 * - Chronological memory fragments
 * - Filterable by tag, source, date range
 * - Expandable to view evidence chain
 */
function Timeline(): React.ReactElement {
  return (
    <div className="page-timeline">
      <h2>记忆时间线</h2>
      <p className="text-muted">记忆时间线视图即将上线，按时间排列所有已导入的记忆碎片。</p>
      <div className="placeholder-card">
        <span className="placeholder-icon">🕐</span>
        <span>按时间排列的记忆碎片 · 标签筛选 · 证据链追溯</span>
      </div>
    </div>
  );
}

export default Timeline;