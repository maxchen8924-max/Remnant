import { useState } from "react";
import useSidecar, { type JsonValue } from "../hooks/useSidecar";

interface TraceCounts {
  fts: number | null;
  vector: number | null;
  reranked: number | null;
}

interface EvidenceSpan {
  span_id: string;
  source_speaker: string | null;
  source_timestamp: string | null;
  excerpt: string | null;
}

interface SourceArtifact {
  artifact_id: string | null;
  file_type: string | null;
  file_hash: string | null;
  source_path_status: string | null;
}

interface EvidenceItem {
  rank: number | null;
  chunk_id: string | null;
  chunk_type: string | null;
  source: string | null;
  combined_score: number | null;
  content: string;
  source_artifact: SourceArtifact;
  spans: EvidenceSpan[];
}

interface EvidenceTrace {
  trace_id: string;
  scope_id: string | null;
  query_text: string | null;
  duration_ms: number | null;
  result_counts: TraceCounts;
  evidence_count: number;
  evidences: EvidenceItem[];
}

function Evidence(): React.ReactElement {
  const { getEvidenceTrace, loading, error } = useSidecar();
  const [traceId, setTraceId] = useState(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return new URLSearchParams(window.location.search).get("trace") || "";
  });
  const [trace, setTrace] = useState<EvidenceTrace | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLocalError(null);
    setTrace(null);

    const trimmedTraceId = traceId.trim();
    if (!trimmedTraceId) {
      setLocalError("Trace ID 必填。");
      return;
    }

    try {
      const payload = await getEvidenceTrace(trimmedTraceId);
      setTrace(toEvidenceTrace(payload));
    } catch (caughtError) {
      setLocalError(String(caughtError));
    }
  };

  return (
    <div className="page-evidence">
      <div className="evidence-shell">
        <section className="evidence-console" aria-label="Evidence console">
          <div className="evidence-header">
            <div>
              <h2>证据检查</h2>
              <p className="text-muted">按 retrieval trace 查看本地证据来源。</p>
            </div>
            <span className="evidence-mode">Trace based</span>
          </div>

          <form className="evidence-form" onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="evidence-trace-id" className="form-label">
                Trace ID
              </label>
              <input
                id="evidence-trace-id"
                className="form-input"
                value={traceId}
                onChange={(event) => setTraceId(event.target.value)}
                autoComplete="off"
                placeholder="retrieval_trace_id"
              />
            </div>

            {(localError || error) && (
              <div className="scope-error-message" role="alert">
                {localError || error}
              </div>
            )}

            <div className="form-actions">
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? "加载中" : "加载证据"}
              </button>
            </div>
          </form>
        </section>

        <section className="evidence-result" aria-label="Evidence result">
          {trace ? (
            <>
              <div className="evidence-result-header">
                <h3>Trace</h3>
                <span className="evidence-status">{trace.evidence_count} evidence</span>
              </div>

              <div className="evidence-metrics">
                <Metric label="Trace ID" value={trace.trace_id} />
                <Metric label="Scope" value={trace.scope_id || "未返回"} />
                <Metric label="Query" value={trace.query_text || "未返回"} />
                <Metric
                  label="Latency"
                  value={trace.duration_ms === null ? "未记录" : `${trace.duration_ms} ms`}
                />
                <Metric label="FTS" value={formatNullableNumber(trace.result_counts.fts)} />
                <Metric label="Vector" value={formatNullableNumber(trace.result_counts.vector)} />
                <Metric
                  label="Reranked"
                  value={formatNullableNumber(trace.result_counts.reranked)}
                />
              </div>

              <div className="evidence-cards" aria-label="Evidence cards">
                {trace.evidences.length > 0 ? (
                  trace.evidences.map((item) => (
                    <article
                      className="evidence-card"
                      key={`${item.rank ?? "rank"}-${item.chunk_id ?? item.content}`}
                    >
                      <div className="evidence-card-header">
                        <span className="evidence-rank">
                          #{item.rank === null ? "?" : item.rank}
                        </span>
                        <div>
                          <h4>{item.chunk_id || "unknown chunk"}</h4>
                          <span className="text-muted">
                            {item.chunk_type || "unknown"} · {item.source || "retrieval"}
                          </span>
                        </div>
                        <span className="evidence-score">
                          {formatScore(item.combined_score)}
                        </span>
                      </div>

                      <p className="evidence-content">{item.content}</p>

                      <div className="evidence-source-grid">
                        <Metric
                          label="Artifact"
                          value={item.source_artifact.artifact_id || "未返回"}
                        />
                        <Metric
                          label="Type"
                          value={item.source_artifact.file_type || "未返回"}
                        />
                        <Metric
                          label="Hash"
                          value={item.source_artifact.file_hash || "未返回"}
                        />
                        <Metric
                          label="Source Path"
                          value={item.source_artifact.source_path_status || "unknown"}
                        />
                      </div>

                      {item.spans.length > 0 && (
                        <ol className="evidence-spans" aria-label="Evidence spans">
                          {item.spans.map((span) => (
                            <li key={span.span_id}>
                              <span>{span.source_speaker || "unknown speaker"}</span>
                              <span>{span.source_timestamp || "unknown time"}</span>
                              <p>{span.excerpt || "未返回摘录"}</p>
                            </li>
                          ))}
                        </ol>
                      )}
                    </article>
                  ))
                ) : (
                  <p className="text-muted">该 trace 没有可见证据。</p>
                )}
              </div>
            </>
          ) : (
            <div className="evidence-empty">
              <h3>Trace</h3>
              <p className="text-muted">等待加载证据。</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="evidence-metric">
      <span className="evidence-metric-label">{label}</span>
      <span className="evidence-metric-value">{value}</span>
    </div>
  );
}

function toEvidenceTrace(value: JsonValue): EvidenceTrace {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Sidecar returned an invalid evidence trace.");
  }

  const record = value as Record<string, JsonValue>;
  const evidences = Array.isArray(record.evidences)
    ? record.evidences.map(toEvidenceItem)
    : [];

  return {
    trace_id: toStringValue(record.trace_id) || "",
    scope_id: toStringValue(record.scope_id),
    query_text: toStringValue(record.query_text),
    duration_ms: toNumberValue(record.duration_ms),
    result_counts: toTraceCounts(record.result_counts),
    evidence_count: toNumberValue(record.evidence_count) ?? evidences.length,
    evidences,
  };
}

function toEvidenceItem(value: JsonValue): EvidenceItem {
  const record: Record<string, JsonValue> = isRecord(value) ? value : {};
  const sourceArtifact: Record<string, JsonValue> = isRecord(record.source_artifact)
    ? record.source_artifact
    : {};
  const spans = Array.isArray(record.spans) ? record.spans.map(toEvidenceSpan) : [];

  return {
    rank: toNumberValue(record.rank),
    chunk_id: toStringValue(record.chunk_id),
    chunk_type: toStringValue(record.chunk_type),
    source: toStringValue(record.source),
    combined_score: toNumberValue(record.combined_score),
    content: toStringValue(record.content) || "",
    source_artifact: {
      artifact_id: toStringValue(sourceArtifact.artifact_id),
      file_type: toStringValue(sourceArtifact.file_type),
      file_hash: toStringValue(sourceArtifact.file_hash),
      source_path_status: toStringValue(sourceArtifact.source_path_status),
    },
    spans,
  };
}

function toEvidenceSpan(value: JsonValue): EvidenceSpan {
  const record: Record<string, JsonValue> = isRecord(value) ? value : {};
  return {
    span_id: toStringValue(record.span_id) || "",
    source_speaker: toStringValue(record.source_speaker),
    source_timestamp: toStringValue(record.source_timestamp),
    excerpt: toStringValue(record.excerpt),
  };
}

function toTraceCounts(value: JsonValue): TraceCounts {
  const record: Record<string, JsonValue> = isRecord(value) ? value : {};
  return {
    fts: toNumberValue(record.fts),
    vector: toNumberValue(record.vector),
    reranked: toNumberValue(record.reranked),
  };
}

function isRecord(value: JsonValue | undefined): value is Record<string, JsonValue> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function toStringValue(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function toNumberValue(value: JsonValue | undefined): number | null {
  return typeof value === "number" ? value : null;
}

function formatNullableNumber(value: number | null): string {
  return value === null ? "未返回" : String(value);
}

function formatScore(value: number | null): string {
  return value === null ? "score n/a" : `score ${value.toFixed(2)}`;
}

export default Evidence;
