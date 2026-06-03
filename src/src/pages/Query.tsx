import { useMemo, useState } from "react";
import useSidecar, { type JsonValue } from "../hooks/useSidecar";

interface QueryResult {
  content: string;
  retrieval_trace_id: string | null;
  duration_ms: number | null;
  safety_flags: string[];
}

function Query(): React.ReactElement {
  const { query, loading, error } = useSidecar();
  const [scopeId, setScopeId] = useState("");
  const [question, setQuestion] = useState("西湖");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const evidenceRows = useMemo(
    () => (result ? extractEvidenceRows(result.content) : []),
    [result]
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLocalError(null);

    const trimmedScopeId = scopeId.trim();
    const trimmedQuestion = question.trim();

    if (!trimmedScopeId) {
      setLocalError("Scope ID 必填。");
      return;
    }

    if (!trimmedQuestion) {
      setLocalError("问题必填。");
      return;
    }

    const payload = await query({
      scope_id: trimmedScopeId,
      query: trimmedQuestion,
      stream: false,
    });
    setResult(toQueryResult(payload));
  };

  return (
    <div className="page-query">
      <div className="query-shell">
        <section className="query-console" aria-label="Query console">
          <div className="query-header">
            <h2>问答</h2>
            <span className="query-mode">Evidence first</span>
          </div>

          <form className="query-form" onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="query-scope-id" className="form-label">
                Scope ID
              </label>
              <input
                id="query-scope-id"
                className="form-input"
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                autoComplete="off"
              />
            </div>

            <div className="form-group">
              <label htmlFor="query-question" className="form-label">
                问题
              </label>
              <textarea
                id="query-question"
                className="form-textarea query-textarea"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              />
            </div>

            {(localError || error) && (
              <div className="scope-error-message" role="alert">
                {localError || error}
              </div>
            )}

            <div className="form-actions">
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? "查询中" : "查询证据"}
              </button>
            </div>
          </form>
        </section>

        <section className="query-result" aria-label="Query result">
          {result ? (
            <>
              <div className="query-result-meta">
                <div>
                  <span className="query-meta-label">Trace</span>
                  <span className="query-meta-value">
                    {result.retrieval_trace_id || "无 trace"}
                  </span>
                </div>
                <div>
                  <span className="query-meta-label">Latency</span>
                  <span className="query-meta-value">
                    {result.duration_ms === null ? "未记录" : `${result.duration_ms} ms`}
                  </span>
                </div>
              </div>

              {result.safety_flags.length > 0 && (
                <div className="query-flags" aria-label="Safety flags">
                  {result.safety_flags.map((flag) => (
                    <span className="query-flag" key={flag}>
                      {flag}
                    </span>
                  ))}
                </div>
              )}

              <div className="query-answer">
                <h3>Answer</h3>
                <pre>{result.content}</pre>
              </div>

              <div className="query-evidence">
                <h3>Evidence</h3>
                {evidenceRows.length > 0 ? (
                  <ol aria-label="Evidence rows">
                    {evidenceRows.map((row) => (
                      <li key={`${row.index}-${row.text}`}>{row.text}</li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-muted">未返回证据片段。</p>
                )}
              </div>
            </>
          ) : (
            <div className="query-empty">
              <h3>Evidence</h3>
              <p className="text-muted">等待查询结果。</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function toQueryResult(value: JsonValue): QueryResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {
      content: "",
      retrieval_trace_id: null,
      duration_ms: null,
      safety_flags: ["invalid_query_response"],
    };
  }

  const record = value as Record<string, JsonValue>;
  const safetyFlags = Array.isArray(record.safety_flags)
    ? record.safety_flags.filter((item): item is string => typeof item === "string")
    : [];

  return {
    content: typeof record.content === "string" ? record.content : "",
    retrieval_trace_id:
      typeof record.retrieval_trace_id === "string" ? record.retrieval_trace_id : null,
    duration_ms: typeof record.duration_ms === "number" ? record.duration_ms : null,
    safety_flags: safetyFlags,
  };
}

function extractEvidenceRows(content: string): Array<{ index: number; text: string }> {
  return content
    .split(/\r?\n/)
    .map((line) => line.match(/^(\d+)\.\s+(.+)$/))
    .filter((match): match is RegExpMatchArray => match !== null)
    .map((match) => ({
      index: Number(match[1]),
      text: match[2],
    }));
}

export default Query;
