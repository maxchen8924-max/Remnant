/**
 * ChunkVisibility — chunk 可见性管理组件。
 *
 * 显示当前 scope 下可见的 chunk 列表，支持：
 * - 查看 chunk 内容摘要、类型、可见性级别
 * - 提升 scope_private chunk 为 scope_shared（需 can_elevate_shared 权限）
 * - 提升操作需要确认弹窗
 */
import { useState, useEffect, useCallback } from "react";

/** 权限项类型 */
interface PermissionItem {
  id: string;
  permission_key: string;
  permission_value: string;
}

/** chunk 可见性记录 */
interface VisibilityRecord {
  id: string;
  chunk_id: string;
  relationship_scope_id: string;
  visibility: string;
  elevated_at: string | null;
  elevated_by_scope: string | null;
}

/** chunk 信息 */
interface ChunkItem {
  id: string;
  content: string;
  chunk_type: string;
  status: string;
  relationship_scope_id: string | null;
  token_count: number;
  metadata: string;
}

const VISIBILITY_LABELS: Record<string, string> = {
  scope_private: "私有",
  scope_shared: "共享",
  deceased_shared: "逝者公开",
};

const VISIBILITY_COLORS: Record<string, string> = {
  scope_private: "var(--color-danger)",
  scope_shared: "var(--color-warning)",
  deceased_shared: "var(--color-success)",
};

const CHUNK_TYPE_LABELS: Record<string, string> = {
  conversation_segment: "对话片段",
  diary_entry: "日记条目",
  letter: "信件",
  mixed: "混合",
  user_provided_context: "用户补充",
  transcription: "转录",
};

interface ChunkVisibilityProps {
  scopeId: string;
}

function ChunkVisibility({ scopeId }: ChunkVisibilityProps): React.ReactElement {
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [visibilityMap, setVisibilityMap] = useState<Record<string, VisibilityRecord>>({});
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [upgradingChunkId, setUpgradingChunkId] = useState<string | null>(null);
  const [confirmUpgrade, setConfirmUpgrade] = useState<string | null>(null);

  /** 检查是否有提升共享权限 */
  const canElevate = permissions.some(
    (p) =>
      p.permission_key === "can_elevate_shared" &&
      (p.permission_value === "allow" || p.permission_value === "ask"),
  );

  /** 加载可见 chunk 列表和权限 */
  const loadData = useCallback(async (): Promise<void> => {
    if (!scopeId) return;

    setLoading(true);
    setError(null);

    try {
      const [chunkResult, visResult, permResult] = await Promise.all([
        invoke<{ visible_chunks: ChunkItem[] }>(
          "invoke_scope_visibility",
          { request: { scope_id: scopeId } },
        ).catch(() => ({ visible_chunks: [] })),
        invoke<{ visibility: VisibilityRecord[] }>(
          "invoke_scope_visibility_detail",
          { request: { scope_id: scopeId } },
        ).catch(() => ({ visibility: [] })),
        invoke<{ permissions: PermissionItem[] }>(
          "invoke_scope_permissions",
          { request: { scope_id: scopeId } },
        ).catch(() => ({ permissions: [] })),
      ]);

      setChunks(chunkResult.visible_chunks || []);
      setPermissions(permResult.permissions || []);

      // 构建 visibilityMap: chunk_id -> visibility record
      const visMap: Record<string, VisibilityRecord> = {};
      const visList = visResult.visibility || [];
      for (const v of visList) {
        visMap[v.chunk_id] = v;
      }
      setVisibilityMap(visMap);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [scopeId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /** 提升 chunk 可见性 */
  const handleUpgrade = async (chunkId: string): Promise<void> => {
    try {
      await invoke("invoke_scope_visibility_upgrade", {
        request: { scope_id: scopeId, chunk_id: chunkId },
      });

      // 刷新数据
      setUpgradingChunkId(null);
      setConfirmUpgrade(null);
      await loadData();
    } catch (err) {
      setError(`提升可见性失败: ${err}`);
      setUpgradingChunkId(null);
      setConfirmUpgrade(null);
    }
  };

  /** 获取 chunk 的显示可见性 */
  const getChunkVisibility = (chunk: ChunkItem): string => {
    // 如果有 visibility 记录，使用记录中的值
    if (visibilityMap[chunk.id]) {
      return visibilityMap[chunk.id].visibility;
    }
    // 如果 chunk 有 scope_id，默认为 scope_private
    if (chunk.relationship_scope_id) {
      return "scope_private";
    }
    // 否则为全局可见
    return "deceased_shared";
  };

  /** 截断内容摘要 */
  const truncateContent = (content: string, maxLen: number = 80): string => {
    if (!content) return "—";
    if (content.length <= maxLen) return content;
    return content.substring(0, maxLen) + "...";
  };

  return (
    <div className="chunk-visibility">
      <div className="chunk-visibility-header">
        <h4>记忆分块可见性</h4>
        <button
          className="btn btn-secondary btn-small"
          onClick={loadData}
          disabled={loading}
        >
          {loading ? "加载中..." : "刷新"}
        </button>
      </div>

      {error && <div className="scope-error-message">❌ {error}</div>}

      {loading && chunks.length === 0 ? (
        <div className="chunk-visibility-empty">加载中...</div>
      ) : chunks.length === 0 ? (
        <div className="chunk-visibility-empty">当前作用域下暂无可见的记忆分块</div>
      ) : (
        <table className="table table-compact">
          <thead>
            <tr>
              <th>内容摘要</th>
              <th>类型</th>
              <th>可见性</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {chunks.map((chunk) => {
              const visibility = getChunkVisibility(chunk);
              const canUpgradeThis = canElevate && visibility === "scope_private";

              return (
                <tr key={chunk.id}>
                  <td className="chunk-content-cell" title={chunk.content}>
                    {truncateContent(chunk.content)}
                  </td>
                  <td>
                    {CHUNK_TYPE_LABELS[chunk.chunk_type] || chunk.chunk_type}
                  </td>
                  <td>
                    <span
                      className="visibility-badge"
                      style={{ color: VISIBILITY_COLORS[visibility] || "var(--color-text-muted)" }}
                    >
                      {VISIBILITY_LABELS[visibility] || visibility}
                    </span>
                  </td>
                  <td>
                    {canUpgradeThis && (
                      <>
                        {confirmUpgrade === chunk.id ? (
                          <div className="chunk-confirm-upgrade">
                            <p>确认将此分块从「私有」提升为「共享」？</p>
                            <button
                              className="btn btn-warning btn-small"
                              onClick={() => handleUpgrade(chunk.id)}
                              disabled={upgradingChunkId === chunk.id}
                            >
                              确认提升
                            </button>
                            <button
                              className="btn btn-secondary btn-small"
                              onClick={() => setConfirmUpgrade(null)}
                            >
                              取消
                            </button>
                          </div>
                        ) : (
                          <button
                            className="btn btn-small btn-outline-warning"
                            onClick={() => setConfirmUpgrade(chunk.id)}
                            disabled={upgradingChunkId !== null}
                          >
                            提升可见性
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// invoke 的类型安全包装
async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke<T>(cmd, args);
}

export default ChunkVisibility;