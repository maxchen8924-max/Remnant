/**
 * Query page — Q&A interface placeholder.
 *
 * Future implementation will support:
 * - Natural language queries against the memory store
 * - SSE streaming responses from Python sidecar
 * - Evidence citation display
 * - Scope-scoped queries
 */
function Query(): React.ReactElement {
  return (
    <div className="page-query">
      <h2>问答</h2>
      <p className="text-muted">
        向记忆库提问，AI 将基于已导入的数据给出引用证据的回答。
      </p>
      <div className="placeholder-card">
        <span className="placeholder-icon">💬</span>
        <span>自然语言问答 · 流式响应 · 证据溯源</span>
      </div>
    </div>
  );
}

export default Query;