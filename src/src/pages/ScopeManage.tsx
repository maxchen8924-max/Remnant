/**
 * ScopeManage — 作用域管理和权限配置页面。
 *
 * 替代原有的 Settings 占位页面，提供：
 * - Scope 列表（按逝者档案 ID 查询）
 * - 当前活跃 Scope 切换
 * - 权限矩阵（10 个 permission_key 的查看/编辑）
 * - 安全策略查看
 * - 删除操作（软删除 / 硬删除需二次确认）
 */
import { useState, useCallback, useEffect } from "react";
import useSidecar from "../hooks/useSidecar";

/** 权限键名称中文映射 */
const PERMISSION_LABELS: Record<string, string> = {
  can_query_memory: "查询记忆",
  can_browse_original: "浏览原文",
  can_add_oral_history: "添加口述历史",
  can_elevate_shared: "提升可见性",
  can_export_data: "导出数据",
  can_view_financial: "查看财务信息",
  can_view_medical: "查看医疗信息",
  can_view_intimate: "查看私密信息",
  can_interact_level3: "深度交互",
  can_delete_scope: "删除作用域",
};

/** 权限值选项 */
const PERMISSION_VALUES = ["allow", "deny", "ask"] as const;

const VALUE_LABELS: Record<string, string> = {
  allow: "允许",
  deny: "拒绝",
  ask: "需确认",
};

const VALUE_COLORS: Record<string, string> = {
  allow: "var(--color-success)",
  deny: "var(--color-danger)",
  ask: "var(--color-warning)",
};

/** 关系类型中文映射 */
const RELATIONSHIP_LABELS: Record<string, string> = {
  spouse: "配偶",
  child: "子女",
  sibling: "兄弟姐妹",
  parent: "父母",
  friend: "朋友",
  colleague: "同事",
  other: "其他",
};

/** 安全策略字段中文映射 */
const SAFETY_LABELS: Record<string, string> = {
  max_session_minutes: "单次会话最大时长（分钟）",
  max_sessions_daily: "每日最大会话数",
  late_night_start: "深夜时段开始",
  late_night_end: "深夜时段结束",
  max_late_night_sessions: "深夜最大会话数",
  dependency_threshold: "情绪依赖阈值",
  farewell_refusal_limit: "拒绝结束次数上限",
  hard_break_enabled: "启用硬熔断",
  cooldown_minutes: "冷却期（分钟）",
  escalate_on_crisis: "危机表达触发升级",
};

interface PermissionItem {
  id: string;
  permission_key: string;
  permission_value: string;
}

interface SafetyPolicyItem {
  [key: string]: unknown;
}

function ScopeManage(): React.ReactElement {
  const { createScope, loading, error } = useSidecar();

  // 状态
  const [deceasedProfileId, setDeceasedProfileId] = useState<string>("");
  const [scopes, setScopes] = useState<Array<Record<string, unknown>>>([]);
  const [selectedScopeId, setSelectedScopeId] = useState<string>("");
  const [scopeDetail, setScopeDetail] = useState<Record<string, unknown> | null>(null);
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [safetyPolicy, setSafetyPolicy] = useState<SafetyPolicyItem | null>(null);

  // 操作状态
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [confirmHardDelete, setConfirmHardDelete] = useState(false);
  const [confirmSoftDelete, setConfirmSoftDelete] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  /** 加载 Scope 列表 */
  const fetchScopes = useCallback(async (): Promise<void> => {
    if (!deceasedProfileId.trim()) return;

    setFetching(true);
    setFetchError(null);

    try {
      const result = await invoke<Record<string, unknown>>("invoke_scope_list", {
        request: { deceased_profile_id: deceasedProfileId.trim() },
      });
      const scopeList = (result?.scopes as Array<Record<string, unknown>>) || [];
      setScopes(scopeList);

      if (scopeList.length > 0 && !selectedScopeId) {
        setSelectedScopeId(scopeList[0].id as string);
      }
    } catch (err) {
      setFetchError(String(err));
      setScopes([]);
    } finally {
      setFetching(false);
    }
  }, [deceasedProfileId, selectedScopeId]);

  /** 加载选中 Scope 的详情、权限、安全策略 */
  const loadScopeDetail = useCallback(async (): Promise<void> => {
    if (!selectedScopeId) {
      setScopeDetail(null);
      setPermissions([]);
      setSafetyPolicy(null);
      return;
    }

    setFetching(true);
    setFetchError(null);

    try {
      const [detailResult, permResult, policyResult] = await Promise.all([
        invoke<Record<string, unknown>>("invoke_scope_get", {
          request: { scope_id: selectedScopeId },
        }),
        invoke<Record<string, unknown>>("invoke_scope_permissions", {
          request: { scope_id: selectedScopeId },
        }),
        invoke<Record<string, unknown>>("invoke_scope_safety_policy", {
          request: { scope_id: selectedScopeId },
        }),
      ]);

      setScopeDetail((detailResult?.scope as Record<string, unknown>) || null);
      setPermissions((permResult?.permissions as PermissionItem[]) || []);
      setSafetyPolicy((policyResult?.safety_policy as SafetyPolicyItem) || null);
    } catch (err) {
      setFetchError(String(err));
    } finally {
      setFetching(false);
    }
  }, [selectedScopeId]);

  /** 组件挂载时加载 scope 列表 */
  useEffect(() => {
    if (deceasedProfileId.trim()) {
      fetchScopes();
    }
  }, [deceasedProfileId, fetchScopes]);

  /** 选中 scope 变化时加载详情 */
  useEffect(() => {
    if (selectedScopeId) {
      loadScopeDetail();
    }
  }, [selectedScopeId, loadScopeDetail]);

  /** 更新权限值 */
  const handlePermissionChange = async (
    permissionKey: string,
    newValue: string,
  ): Promise<void> => {
    if (!selectedScopeId) return;

    try {
      await invoke("invoke_scope_set_permission", {
        request: {
          scope_id: selectedScopeId,
          permission_key: permissionKey,
          permission_value: newValue,
        },
      });

      // 更新本地权限列表
      setPermissions((prev) =>
        prev.map((p) =>
          p.permission_key === permissionKey
            ? { ...p, permission_value: newValue }
            : p,
        ),
      );
      setSuccessMessage(`权限 "${PERMISSION_LABELS[permissionKey] || permissionKey}" 已更新为 "${VALUE_LABELS[newValue]}"`);
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setFetchError(`更新权限失败: ${err}`);
    }
  };

  /** 软删除 */
  const handleSoftDelete = async (): Promise<void> => {
    if (!selectedScopeId) return;

    try {
      await invoke("invoke_scope_soft_delete", {
        request: { scope_id: selectedScopeId },
      });

      setSuccessMessage("作用域已软删除");
      setConfirmSoftDelete(false);
      setSelectedScopeId("");
      setTimeout(() => {
        setSuccessMessage(null);
        fetchScopes();
      }, 1500);
    } catch (err) {
      setFetchError(`软删除失败: ${err}`);
      setConfirmSoftDelete(false);
    }
  };

  /** 硬删除 */
  const handleHardDelete = async (): Promise<void> => {
    if (!selectedScopeId) return;

    try {
      await invoke("invoke_scope_hard_delete", {
        request: { scope_id: selectedScopeId },
      });

      setSuccessMessage("作用域已永久删除");
      setConfirmHardDelete(false);
      setSelectedScopeId("");
      setTimeout(() => {
        setSuccessMessage(null);
        fetchScopes();
      }, 1500);
    } catch (err) {
      setFetchError(`硬删除失败: ${err}`);
      setConfirmHardDelete(false);
    }
  };

  return (
    <div className="page-scope-manage">
      <h2>作用域管理</h2>
      <p className="text-muted">
        管理关系作用域、配置权限和安全策略。
      </p>

      {successMessage && (
        <div className="scope-success-message">{successMessage}</div>
      )}

      {(error || fetchError) && (
        <div className="scope-error-message">
          ❌ {fetchError || error}
        </div>
      )}

      {/* 逝者档案 ID 输入 */}
      <div className="scope-section">
        <div className="scope-section-header">
          <h3>选择逝者档案</h3>
        </div>
        <div className="scope-profile-input">
          <input
            type="text"
            className="form-input"
            placeholder="输入逝者档案 ID 以加载作用域列表"
            value={deceasedProfileId}
            onChange={(e) => setDeceasedProfileId(e.target.value)}
          />
          <button
            className="btn btn-primary"
            onClick={fetchScopes}
            disabled={fetching || !deceasedProfileId.trim()}
          >
            {fetching ? "加载中..." : "加载"}
          </button>
        </div>
      </div>

      {/* Scope 列表 */}
      {scopes.length > 0 && (
        <div className="scope-section">
          <div className="scope-section-header">
            <h3>作用域列表</h3>
            <span className="scope-count">{scopes.length} 个作用域</span>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>选择</th>
                <th>名称</th>
                <th>关系</th>
                <th>状态</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {scopes.map((scope) => (
                <tr
                  key={scope.id as string}
                  className={scope.id === selectedScopeId ? "scope-row-selected" : ""}
                  onClick={() => setSelectedScopeId(scope.id as string)}
                >
                  <td>
                    <input
                      type="radio"
                      name="scope_select"
                      checked={scope.id === selectedScopeId}
                      onChange={() => setSelectedScopeId(scope.id as string)}
                    />
                  </td>
                  <td>{scope.scope_name as string}</td>
                  <td>{RELATIONSHIP_LABELS[scope.relationship_type as string] || (scope.relationship_type as string)}</td>
                  <td>
                    <span className={`scope-status ${(scope.is_active as number) === 1 ? "status-active" : "status-inactive"}`}>
                      {(scope.is_active as number) === 1 ? "活跃" : "已停用"}
                    </span>
                  </td>
                  <td>{formatTime(scope.created_at as string)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 选中 Scope 的详情 */}
      {selectedScopeId && scopeDetail && (
        <>
          {/* Scope 基本信息 */}
          <div className="scope-section">
            <div className="scope-section-header">
              <h3>作用域详情</h3>
            </div>
            <div className="scope-detail-grid">
              <div className="scope-detail-item">
                <span className="scope-detail-label">ID</span>
                <span className="scope-detail-value">{scopeDetail.id as string}</span>
              </div>
              <div className="scope-detail-item">
                <span className="scope-detail-label">名称</span>
                <span className="scope-detail-value">{scopeDetail.scope_name as string}</span>
              </div>
              <div className="scope-detail-item">
                <span className="scope-detail-label">关系类型</span>
                <span className="scope-detail-value">
                  {RELATIONSHIP_LABELS[scopeDetail.relationship_type as string] || (scopeDetail.relationship_type as string)}
                </span>
              </div>
              <div className="scope-detail-item">
                <span className="scope-detail-label">描述</span>
                <span className="scope-detail-value">
                  {(scopeDetail.scope_description as string) || "无"}
                </span>
              </div>
            </div>
          </div>

          {/* 权限矩阵 */}
          <div className="scope-section">
            <div className="scope-section-header">
              <h3>权限配置</h3>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>权限项</th>
                  <th>当前值</th>
                  <th>修改</th>
                </tr>
              </thead>
              <tbody>
                {permissions.map((perm) => (
                  <tr key={perm.id}>
                    <td>{PERMISSION_LABELS[perm.permission_key] || perm.permission_key}</td>
                    <td>
                      <span
                        className="perm-badge"
                        style={{ color: VALUE_COLORS[perm.permission_value] || "var(--color-text)" }}
                      >
                        {VALUE_LABELS[perm.permission_value] || perm.permission_value}
                      </span>
                    </td>
                    <td>
                      <select
                        className="form-select form-select-small"
                        value={perm.permission_value}
                        onChange={(e) =>
                          handlePermissionChange(perm.permission_key, e.target.value)
                        }
                        disabled={loading}
                      >
                        {PERMISSION_VALUES.map((v) => (
                          <option key={v} value={v}>
                            {VALUE_LABELS[v]}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 安全策略 */}
          {safetyPolicy && (
            <div className="scope-section">
              <div className="scope-section-header">
                <h3>安全策略</h3>
              </div>
              <div className="safety-policy-grid">
                {Object.entries(SAFETY_LABELS).map(([key, label]) => {
                  const rawValue = safetyPolicy[key];
                  const displayValue = typeof rawValue === "boolean"
                    ? (rawValue ? "是" : "否")
                    : String(rawValue ?? "—");
                  return (
                    <div key={key} className="safety-policy-item">
                      <span className="safety-policy-label">{label}</span>
                      <span className="safety-policy-value">{displayValue}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 删除操作 */}
          <div className="scope-section scope-delete-section">
            <div className="scope-section-header">
              <h3>删除操作</h3>
            </div>
            <div className="scope-delete-actions">
              <div className="scope-delete-option">
                <p>软删除将标记作用域为已删除，关联数据暂时不可访问，但可以恢复。</p>
                {!confirmSoftDelete ? (
                  <button
                    className="btn btn-warning"
                    onClick={() => setConfirmSoftDelete(true)}
                    disabled={loading}
                  >
                    软删除此作用域
                  </button>
                ) : (
                  <div className="scope-confirm-dialog">
                    <p className="scope-confirm-text">确认要软删除此作用域吗？</p>
                    <button className="btn btn-danger" onClick={handleSoftDelete} disabled={loading}>
                      确认软删除
                    </button>
                    <button className="btn btn-secondary" onClick={() => setConfirmSoftDelete(false)}>
                      取消
                    </button>
                  </div>
                )}
              </div>

              <div className="scope-delete-option">
                <p>硬删除将永久销毁作用域的所有数据，<strong>此操作不可逆</strong>。</p>
                {!confirmHardDelete ? (
                  <button
                    className="btn btn-danger"
                    onClick={() => setConfirmHardDelete(true)}
                    disabled={loading}
                  >
                    永久删除此作用域
                  </button>
                ) : (
                  <div className="scope-confirm-dialog scope-confirm-danger">
                    <p className="scope-confirm-text">
                      ⚠️ <strong>警告：</strong>永久删除将销毁所有关联数据，包括记忆分块、交互记录、证据追踪等。
                      <br />
                      <strong>此操作不可逆，无法恢复！</strong>
                    </p>
                    <button className="btn btn-danger" onClick={handleHardDelete} disabled={loading}>
                      我已了解风险，确认永久删除
                    </button>
                    <button className="btn btn-secondary" onClick={() => setConfirmHardDelete(false)}>
                      取消
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* 无数据提示 */}
      {deceasedProfileId.trim() && scopes.length === 0 && !fetching && !fetchError && (
        <div className="placeholder-card">
          <span className="placeholder-icon">📋</span>
          <span>该逝者档案下暂无作用域，请先创建一个。</span>
        </div>
      )}
    </div>
  );
}

/** 格式化时间 */
function formatTime(isoTime: string | null | undefined): string {
  if (!isoTime) return "—";
  try {
    const date = new Date(isoTime);
    return date.toLocaleString("zh-CN");
  } catch {
    return isoTime;
  }
}

// invoke 的类型安全包装 — 这里直接使用 Tauri invoke
// 因 useSidecar 未提供所有 scope 相关方法，使用 invoke 直调
async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke<T>(cmd, args);
}

export default ScopeManage;