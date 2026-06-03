import { useMemo, useState } from "react";
import useSidecar, { type JsonValue } from "../hooks/useSidecar";

interface SourceAdapterOption {
  value: string;
  label: string;
  detail: string;
}

interface ImportResult {
  artifact_id: string | null;
  file_hash: string | null;
  message_count: number | null;
  chunk_count: number | null;
  parse_status: string | null;
  errors: string[];
}

const SOURCE_ADAPTERS: SourceAdapterOption[] = [
  {
    value: "universal_chat_json",
    label: "Universal Chat JSON",
    detail: "全球通用聊天格式",
  },
  {
    value: "wechat_txt",
    label: "WeChat TXT",
    detail: "微信文本导出",
  },
];

function Import(): React.ReactElement {
  const { importData, resolveProfile, loading, error } = useSidecar();
  const [profileName, setProfileName] = useState("");
  const [filePath, setFilePath] = useState("");
  const [scopeId, setScopeId] = useState("");
  const [fileType, setFileType] = useState(SOURCE_ADAPTERS[0].value);
  const [encoding, setEncoding] = useState("utf-8");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [localError, setLocalError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const selectedAdapter = useMemo(
    () => SOURCE_ADAPTERS.find((adapter) => adapter.value === fileType) || SOURCE_ADAPTERS[0],
    [fileType]
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLocalError(null);
    setResult(null);

    const trimmedProfileName = profileName.trim();
    const trimmedFilePath = filePath.trim();
    const trimmedScopeId = scopeId.trim();
    const nextErrors: Record<string, string> = {};

    if (!trimmedProfileName) {
      nextErrors.deceasedProfileId = "逝者档案必填。";
    }

    if (!trimmedFilePath) {
      nextErrors.filePath = "本地文件路径必填。";
    }

    setFieldErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    try {
      const profilePayload = await resolveProfile({
        profile_name: trimmedProfileName,
      });
      const deceasedProfileId = getProfileId(profilePayload);
      const payload = await importData({
        deceased_profile_id: deceasedProfileId,
        file_path: trimmedFilePath,
        file_type: selectedAdapter.value,
        scope_id: trimmedScopeId || undefined,
        encoding,
        metadata: {
          source_adapter: selectedAdapter.value,
          source_adapter_label: selectedAdapter.label,
          profile_name: trimmedProfileName,
        },
      });
      setResult(toImportResult(payload));
    } catch (caughtError) {
      setLocalError(String(caughtError));
    }
  };

  return (
    <div className="page-import">
      <div className="import-shell">
        <section className="import-console" aria-label="Import console">
          <div className="import-header">
            <div>
              <h2>数据导入</h2>
              <p className="text-muted">导入聊天记录、邮件、文档、照片和手动记录等记忆数据源。</p>
            </div>
            <span className="import-mode">Adapter based</span>
          </div>

          <form className="import-form" onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="import-file-type" className="form-label">
                来源类型
              </label>
              <select
                id="import-file-type"
                className="form-select"
                value={fileType}
                onChange={(event) => setFileType(event.target.value)}
              >
                {SOURCE_ADAPTERS.map((adapter) => (
                  <option key={adapter.value} value={adapter.value}>
                    {adapter.label}
                  </option>
                ))}
              </select>
              <span className="form-hint">{selectedAdapter.detail}</span>
            </div>

            <div className="form-group">
              <label htmlFor="import-profile-id" className="form-label">
                逝者档案
              </label>
              <input
                id="import-profile-id"
                className={`form-input ${
                  fieldErrors.deceasedProfileId ? "form-input-error" : ""
                }`}
                value={profileName}
                onChange={(event) => setProfileName(event.target.value)}
                autoComplete="off"
                placeholder="输入名字，如 妈妈"
              />
              {fieldErrors.deceasedProfileId && (
                <span className="form-error">{fieldErrors.deceasedProfileId}</span>
              )}
            </div>

            <div className="form-group">
              <label htmlFor="import-scope-id" className="form-label">
                记忆空间
              </label>
              <input
                id="import-scope-id"
                className="form-input"
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                autoComplete="off"
                placeholder="可选"
              />
            </div>

            <div className="form-group">
              <label htmlFor="import-file-path" className="form-label">
                本地文件路径
              </label>
              <input
                id="import-file-path"
                className={`form-input ${fieldErrors.filePath ? "form-input-error" : ""}`}
                value={filePath}
                onChange={(event) => setFilePath(event.target.value)}
                autoComplete="off"
                placeholder="/Users/me/chat-export.json"
              />
              {fieldErrors.filePath && (
                <span className="form-error">{fieldErrors.filePath}</span>
              )}
            </div>

            <div className="form-group">
              <label htmlFor="import-encoding" className="form-label">
                编码
              </label>
              <select
                id="import-encoding"
                className="form-select"
                value={encoding}
                onChange={(event) => setEncoding(event.target.value)}
              >
                <option value="utf-8">utf-8</option>
                <option value="gb18030">gb18030</option>
              </select>
            </div>

            {(localError || error) && (
              <div className="scope-error-message" role="alert">
                {localError || error}
              </div>
            )}

            <div className="form-actions">
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? "导入中" : "开始导入"}
              </button>
            </div>
          </form>
        </section>

        <section className="import-result" aria-label="Import result">
          {result ? (
            <>
              <div className="import-result-header">
                <h3>导入结果</h3>
                <span className="import-status">{result.parse_status || "unknown"}</span>
              </div>

              <div className="import-result-grid">
                <Metric label="Artifact" value={result.artifact_id || "未返回"} />
                <Metric label="Messages" value={formatNumber(result.message_count)} />
                <Metric label="Chunks" value={formatNumber(result.chunk_count)} />
                <Metric label="File Hash" value={result.file_hash || "未返回"} />
              </div>

              {result.errors.length > 0 && (
                <div className="import-errors">
                  <h4>Errors</h4>
                  <ul>
                    {result.errors.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <div className="import-empty">
              <h3>导入结果</h3>
              <p className="text-muted">等待导入任务完成。</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="import-metric">
      <span className="import-metric-label">{label}</span>
      <span className="import-metric-value">{value}</span>
    </div>
  );
}

function getProfileId(value: JsonValue): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("无法解析逝者档案。");
  }

  const record = value as Record<string, JsonValue>;
  if (typeof record.deceased_profile_id !== "string" || !record.deceased_profile_id) {
    throw new Error("无法解析逝者档案。");
  }

  return record.deceased_profile_id;
}

function toImportResult(value: JsonValue): ImportResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {
      artifact_id: null,
      file_hash: null,
      message_count: null,
      chunk_count: null,
      parse_status: "invalid_import_response",
      errors: ["Sidecar returned an invalid import response."],
    };
  }

  const record = value as Record<string, JsonValue>;
  const errors = Array.isArray(record.errors)
    ? record.errors.filter((item): item is string => typeof item === "string")
    : [];

  return {
    artifact_id: typeof record.artifact_id === "string" ? record.artifact_id : null,
    file_hash: typeof record.file_hash === "string" ? record.file_hash : null,
    message_count: typeof record.message_count === "number" ? record.message_count : null,
    chunk_count: typeof record.chunk_count === "number" ? record.chunk_count : null,
    parse_status: typeof record.parse_status === "string" ? record.parse_status : null,
    errors,
  };
}

function formatNumber(value: number | null): string {
  return value === null ? "未返回" : String(value);
}

export default Import;
