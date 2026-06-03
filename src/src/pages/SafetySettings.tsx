/**
 * SafetySettings — 安全策略配置和安全事件查看页面。
 *
 * 功能：
 * - 编辑当前 scope 的安全策略（max_session_minutes, max_sessions_daily 等）
 * - 保存策略（通过 Tauri invoke）
 * - 查看最近7天安全事件
 */
import { useState, useCallback } from "react";
import useSidecar from "../hooks/useSidecar";
import {
  formatRelationshipSpaceLabel,
  getProfileId,
  getRelationshipSpaces,
  type RelationshipSpace,
} from "../lib/relationshipSpace";

/** 安全策略字段中文映射 */
const POLICY_LABELS: Record<string, string> = {
  max_session_minutes: "单次会话最大时长（分钟）",
  max_sessions_daily: "每日最大会话数",
  late_night_start: "深夜时段开始",
  late_night_end: "深夜时段结束",
  max_late_night_sessions: "深夜最大会话数",
  dependency_threshold: "情绪依赖阈值（0~1）",
  farewell_refusal_limit: "拒绝结束次数上限",
  hard_break_enabled: "启用硬熔断",
  cooldown_minutes: "冷却期（分钟）",
  escalate_on_crisis: "危机表达触发升级",
};

/** 安全策略字段类型映射（用于确定 input type） */
const POLICY_TYPES: Record<string, "number" | "string" | "boolean"> = {
  max_session_minutes: "number",
  max_sessions_daily: "number",
  late_night_start: "string",
  late_night_end: "string",
  max_late_night_sessions: "number",
  dependency_threshold: "number",
  farewell_refusal_limit: "number",
  hard_break_enabled: "boolean",
  cooldown_minutes: "number",
  escalate_on_crisis: "boolean",
};

/** 安全策略默认值 */
const POLICY_DEFAULTS: Record<string, unknown> = {
  max_session_minutes: 60,
  max_sessions_daily: 5,
  late_night_start: "22:00",
  late_night_end: "06:00",
  max_late_night_sessions: 2,
  dependency_threshold: 0.7,
  farewell_refusal_limit: 3,
  hard_break_enabled: true,
  cooldown_minutes: 30,
  escalate_on_crisis: true,
};

/** 安全策略字段排列顺序 */
const POLICY_ORDER = [
  "max_session_minutes",
  "max_sessions_daily",
  "late_night_start",
  "late_night_end",
  "max_late_night_sessions",
  "dependency_threshold",
  "farewell_refusal_limit",
  "hard_break_enabled",
  "cooldown_minutes",
  "escalate_on_crisis",
];

/** 安全事件记录 */
interface SafetyEvent {
  id: string;
  scope_id: string;
  event_type: string;
  action_taken: string;
  reason: string;
  timestamp: string;
  [key: string]: unknown;
}

/** 事件类型中文映射 */
const EVENT_TYPE_LABELS: Record<string, string> = {
  soft_break: "温和熔断",
  hard_break: "强制熔断",
  escalate: "危机升级",
  allow: "正常放行",
};

const ACTION_LABELS: Record<string, string> = {
  soft_break: "继续对话（提醒）",
  hard_break: "强制暂停会话",
  escalate: "触发危机资源",
  allow: "正常通过",
};

function SafetySettings(): React.ReactElement {
  const {
    resolveProfile,
    listScopes,
    getSafetyPolicy,
    updateSafetyPolicy,
    getSafetyEvents,
    loading,
    error,
  } = useSidecar();

  const [profileName, setProfileName] = useState<string>("");
  const [relationshipSpaces, setRelationshipSpaces] = useState<RelationshipSpace[]>([]);
  const [selectedScopeId, setSelectedScopeId] = useState<string>("");
  const [policy, setPolicy] = useState<Record<string, unknown>>({ ...POLICY_DEFAULTS });
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [loadedScopeId, setLoadedScopeId] = useState<string>("");
  const [loadedScopeName, setLoadedScopeName] = useState<string>("");
  const [spaceLoading, setSpaceLoading] = useState(false);

  const selectedSpace = relationshipSpaces.find((space) => space.id === selectedScopeId) ?? null;

  /** 加载当前逝者档案下的关系空间 */
  const loadRelationshipSpaces = useCallback(async (): Promise<void> => {
    setFetchError(null);
    setSuccessMessage(null);
    setLoadedScopeId("");
    setLoadedScopeName("");
    setEvents([]);

    const trimmedProfileName = profileName.trim();
    if (!trimmedProfileName) {
      setFetchError("逝者档案必填。");
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
        setFetchError("该逝者档案下暂无关系空间，请先创建一个。");
      }
    } catch (err) {
      setRelationshipSpaces([]);
      setSelectedScopeId("");
      setFetchError(String(err));
    } finally {
      setSpaceLoading(false);
    }
  }, [profileName, resolveProfile, listScopes]);

  /** 同时加载策略和事件 */
  const loadAll = useCallback(async (): Promise<void> => {
    if (!selectedScopeId) {
      setFetchError("请选择关系空间。");
      return;
    }

    setFetching(true);
    setFetchError(null);
    setSuccessMessage(null);

    try {
      const [policyResult, eventsResult] = await Promise.all([
        getSafetyPolicy(selectedScopeId),
        getSafetyEvents(selectedScopeId, 7),
      ]);

      const policyData = (policyResult as Record<string, unknown>)?.safety_policy as Record<string, unknown> | undefined;
      if (policyData) {
        setPolicy({ ...POLICY_DEFAULTS, ...policyData });
      }
      setLoadedScopeId(selectedScopeId);
      setLoadedScopeName(selectedSpace?.scope_name ?? selectedScopeId);

      const eventList = (eventsResult as Record<string, unknown>)?.events as SafetyEvent[] | undefined;
      setEvents(eventList || []);
    } catch (err) {
      setFetchError(String(err));
    } finally {
      setFetching(false);
    }
  }, [selectedScopeId, selectedSpace, getSafetyPolicy, getSafetyEvents]);

  /** 保存安全策略 */
  const handleSave = async (): Promise<void> => {
    if (!loadedScopeId) return;

    setFetching(true);
    setFetchError(null);

    try {
      await updateSafetyPolicy(loadedScopeId, policy);
      setSuccessMessage("安全策略已保存");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setFetchError(`保存失败: ${err}`);
    } finally {
      setFetching(false);
    }
  };

  /** 更新策略字段值 */
  const handlePolicyChange = (key: string, value: unknown): void => {
    setPolicy((prev) => ({ ...prev, [key]: value }));
  };

  /** 格式化时间 */
  const formatTime = (isoTime: string | null | undefined): string => {
    if (!isoTime) return "—";
    try {
      const date = new Date(isoTime);
      return date.toLocaleString("zh-CN");
    } catch {
      return isoTime;
    }
  };

  return (
    <div className="page-safety-settings">
      <h2>安全设置</h2>
      <p className="text-muted">
        配置安全策略和查看安全事件记录，保护您的心理健康。
      </p>

      {successMessage && (
        <div className="scope-success-message">{successMessage}</div>
      )}

      {(error || fetchError) && (
        <div className="scope-error-message">
          {fetchError || error}
        </div>
      )}

      {/* 选择关系空间 */}
      <div className="scope-section">
        <div className="scope-section-header">
          <h3>选择关系空间</h3>
        </div>
        <div className="scope-profile-input">
          <label htmlFor="safety-profile-name" className="form-label">
            逝者档案
          </label>
          <input
            id="safety-profile-name"
            type="text"
            className="form-input"
            placeholder="输入名字，如 妈妈"
            value={profileName}
            onChange={(e) => {
              setProfileName(e.target.value);
              setRelationshipSpaces([]);
              setSelectedScopeId("");
              setLoadedScopeId("");
              setLoadedScopeName("");
            }}
          />
          <button
            className="btn btn-primary"
            onClick={loadRelationshipSpaces}
            disabled={fetching || spaceLoading || loading}
          >
            {spaceLoading ? "加载中..." : "加载关系空间"}
          </button>
        </div>
        <div className="scope-profile-input">
          <label htmlFor="safety-relationship-space" className="form-label">
            关系空间
          </label>
          <select
            id="safety-relationship-space"
            className="form-select"
            value={selectedScopeId}
            onChange={(e) => setSelectedScopeId(e.target.value)}
            disabled={relationshipSpaces.length === 0}
          >
            <option value="">请选择关系空间</option>
            {relationshipSpaces.map((space) => (
              <option key={space.id} value={space.id}>
                {formatRelationshipSpaceLabel(space)}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary"
            onClick={loadAll}
            disabled={fetching || !selectedScopeId}
          >
            {fetching ? "加载中..." : "加载安全策略"}
          </button>
        </div>
      </div>

      {loadedScopeId && (
        <>
          {/* 安全策略编辑 */}
          <div className="scope-section">
            <div className="scope-section-header">
              <h3>安全策略配置</h3>
              <span className="scope-count">关系空间: {loadedScopeName}</span>
            </div>
            <div className="safety-settings-grid">
              {POLICY_ORDER.map((key) => {
                const label = POLICY_LABELS[key];
                const type = POLICY_TYPES[key];
                const value = policy[key];

                if (type === "boolean") {
                  return (
                    <div key={key} className="safety-settings-item">
                      <div className="safety-settings-item-header">
                        <span className="safety-settings-label">{label}</span>
                        <label className="safety-settings-toggle">
                          <input
                            type="checkbox"
                            checked={Boolean(value)}
                            onChange={(e) => handlePolicyChange(key, e.target.checked)}
                            disabled={fetching}
                          />
                          <span className="safety-settings-toggle-slider" />
                        </label>
                      </div>
                      <span className="safety-settings-value">
                        {value ? "已启用" : "已关闭"}
                      </span>
                    </div>
                  );
                } else if (type === "string") {
                  return (
                    <div key={key} className="safety-settings-item">
                      <span className="safety-settings-label">{label}</span>
                      <input
                        type="time"
                        className="form-input safety-settings-input"
                        value={String(value || "")}
                        onChange={(e) => handlePolicyChange(key, e.target.value)}
                        disabled={fetching}
                      />
                    </div>
                  );
                } else {
                  return (
                    <div key={key} className="safety-settings-item">
                      <span className="safety-settings-label">{label}</span>
                      <input
                        type="number"
                        className="form-input safety-settings-input"
                        value={value !== undefined && value !== null ? String(value) : ""}
                        onChange={(e) => {
                          const numVal = e.target.value === "" ? 0 : Number(e.target.value);
                          handlePolicyChange(key, key === "dependency_threshold" ? numVal : Math.round(numVal));
                        }}
                        step={key === "dependency_threshold" ? 0.1 : 1}
                        min={0}
                        disabled={fetching}
                      />
                    </div>
                  );
                }
              })}
            </div>
            <div className="form-actions">
              <button
                className="btn btn-primary"
                onClick={handleSave}
                disabled={fetching}
              >
                {fetching ? "保存中..." : "保存策略"}
              </button>
              <button
                className="btn btn-secondary"
                onClick={loadAll}
                disabled={fetching}
              >
                重置
              </button>
            </div>
          </div>

          {/* 安全事件历史 */}
          <div className="scope-section">
            <div className="scope-section-header">
              <h3>安全事件记录</h3>
              <span className="scope-count">近 7 天</span>
            </div>
            {events.length === 0 ? (
              <div className="placeholder-card">
                <span className="placeholder-icon">📋</span>
                <span>近7天内无安全事件记录</span>
              </div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>事件类型</th>
                    <th>处理动作</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id}>
                      <td>{formatTime(event.timestamp)}</td>
                      <td>
                        <span className="safety-event-type" data-type={event.event_type}>
                          {EVENT_TYPE_LABELS[event.event_type] || event.event_type}
                        </span>
                      </td>
                      <td>
                        <span className="safety-event-action" data-action={event.action_taken}>
                          {ACTION_LABELS[event.action_taken] || event.action_taken}
                        </span>
                      </td>
                      <td className="safety-event-reason">{event.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {!loadedScopeId && selectedScopeId && !fetching && !fetchError && (
        <div className="placeholder-card">
          <span className="placeholder-icon">🛡️</span>
          <span>请选择关系空间并加载安全策略</span>
        </div>
      )}
    </div>
  );
}

export default SafetySettings;
