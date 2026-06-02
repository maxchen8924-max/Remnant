/**
 * Import page — data import wizard placeholder.
 *
 * Future implementation will support:
 * - WeChat / QQ chat history parsing
 * - Photo metadata extraction
 * - Document ingestion
 * - Manual entry / voice-to-text
 */
function Import(): React.ReactElement {
  return (
    <div className="page-import">
      <h2>数据导入</h2>
      <p className="text-muted">导入向导即将上线，支持微信聊天记录、照片、文档等多种数据源。</p>
      <div className="placeholder-card">
        <span className="placeholder-icon">📥</span>
        <span>支持格式：微信聊天记录 · 照片 EXIF · 文档 · 手动录入</span>
      </div>
    </div>
  );
}

export default Import;