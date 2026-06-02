/**
 * Evidence page — evidence card placeholder.
 *
 * Future implementation will display:
 * - Detailed evidence cards with source references
 * - Confidence scores
 * - Chain of provenance
 * - Linked memory fragments
 */
function Evidence(): React.ReactElement {
  return (
    <div className="page-evidence">
      <h2>证据卡片</h2>
      <p className="text-muted">查看每条回答的证据来源、置信度和追溯链。</p>
      <div className="placeholder-card">
        <span className="placeholder-icon">🔍</span>
        <span>证据来源 · 置信度评分 · 追溯链 · 关联记忆</span>
      </div>
    </div>
  );
}

export default Evidence;