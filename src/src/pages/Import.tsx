/**
 * Import page — data source adapter entry placeholder.
 *
 * Future implementation will support:
 * - Universal chat JSON
 * - Regional chat adapters such as WeChat TXT
 * - Email, document, photo, and manual-note sources
 */
function Import(): React.ReactElement {
  return (
    <div className="page-import">
      <h2>数据导入</h2>
      <p className="text-muted">导入聊天记录、邮件、文档、照片和手动记录等记忆数据源。</p>
      <div className="placeholder-card">
        <span>通用聊天 JSON · WeChat TXT · Email · Documents · Photos</span>
      </div>
    </div>
  );
}

export default Import;
