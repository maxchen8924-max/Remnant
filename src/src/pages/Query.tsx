import { useMemo, useState } from "react";
import useSidecar, { type JsonValue } from "../hooks/useSidecar";
import {
  formatRelationshipSpaceLabel,
  getProfileId,
  getRelationshipSpaces,
  type RelationshipSpace,
} from "../lib/relationshipSpace";

interface QueryResult {
  content: string;
  retrieval_trace_id: string | null;
  duration_ms: number | null;
  safety_flags: string[];
}

function Query(): React.ReactElement {
  const { query, resolveProfile, listScopes, loading, error } = useSidecar();
  const [profileName, setProfileName] = useState("");
  const [relationshipSpaces, setRelationshipSpaces] = useState<RelationshipSpace[]>([]);
  const [selectedScopeId, setSelectedScopeId] = useState("");
  const [question, setQuestion] = useState("西湖");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [spaceLoading, setSpaceLoading] = useState(false);

  const evidenceRows = useMemo(
    () => (result ? extractEvidenceRows(result.content) : []),
    [result]
  );

  const selectedSpace = useMemo(
    () => relationshipSpaces.find((space) => space.id === selectedScopeId) ?? null,
    [relationshipSpaces, selectedScopeId]
  );

  const handleLoadSpaces = async () => {
    setLocalError(null);
    setResult(null);

    const trimmedProfileName = profileName.trim();
    if (!trimmedProfileName) {
      setLocalError("逝者档案必填。");
      return;
    }

    setSpaceLoading(true);
    try {
      const profilePayload = await resolveProfile({
        profile_name: trimmedProfileName,
      });
      const deceasedProfileId = getProfileId(profilePayload);
      const scopePayload = await listScopes(deceasedProfileId);
      const spaces = getRelationshipSpaces(scopePayload);

      setRelationshipSpaces(spaces);
      setSelectedScopeId(spaces[0]?.id ?? "");
      if (spaces.length === 0) {
        setLocalError("该逝者档案下暂无关系空间，请先创建一个。");
      }
    } catch (err) {
      setRelationshipSpaces([]);
      setSelectedScopeId("");
      setLocalError(String(err));
    } finally {
      setSpaceLoading(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLocalError(null);

    const trimmedQuestion = question.trim();

    if (!selectedScopeId) {
      setLocalError("请选择关系空间。");
      return;
    }

    if (!trimmedQuestion) {
      setLocalError("问题必填。");
      return;
    }

    const payload = await query({
      scope_id: selectedScopeId,
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
              <label htmlFor="query-profile-name" className="form-label">
                逝者档案
              </label>
              <input
                id="query-profile-name"
                className="form-input"
                value={profileName}
                onChange={(event) => {
                  setProfileName(event.target.value);
                  setRelationshipSpaces([]);
                  setSelectedScopeId("");
                  setResult(null);
                }}
                placeholder="输入名字，如 妈妈"
                autoComplete="off"
              />
            </div>

            <div className="form-group">
              <button
                className="btn btn-secondary"
                type="button"
                onClick={handleLoadSpaces}
                disabled={loading || spaceLoading}
              >
                {spaceLoading ? "加载中" : "加载关系空间"}
              </button>
            </div>

            <div className="form-group">
              <label htmlFor="query-relationship-space" className="form-label">
                关系空间
              </label>
              <select
                id="query-relationship-space"
                className="form-select"
                value={selectedScopeId}
                onChange={(event) => {
                  setSelectedScopeId(event.target.value);
                  setResult(null);
                }}
                disabled={relationshipSpaces.length === 0}
              >
                <option value="">请选择关系空间</option>
                {relationshipSpaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {formatRelationshipSpaceLabel(space)}
                  </option>
                ))}
              </select>
              {selectedSpace && (
                <span className="form-hint">
                  当前关系空间: {selectedSpace.scope_name}
                </span>
              )}
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
