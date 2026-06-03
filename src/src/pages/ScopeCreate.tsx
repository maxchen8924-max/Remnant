/**
 * ScopeCreate — 创建关系空间向导页面。
 *
 * 提供表单让用户创建新的关系空间，包括：
 * - profile_name（逝者档案名称）
 * - scope_name（关系空间名称）
 * - relationship_type（关系类型，下拉选择）
 * - scope_description（关系空间描述，可选）
 *
 * 创建成功后自动跳转到 /settings（关系空间管理页面）。
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import useSidecar, { type JsonValue } from "../hooks/useSidecar";

/** 关系类型选项，与白皮书 Ch9 一致 */
const RELATIONSHIP_OPTIONS: Array<{ value: string; label: string; description: string }> = [
  { value: "spouse", label: "配偶", description: "逝者的丈夫或妻子" },
  { value: "child", label: "子女", description: "逝者的儿子或女儿" },
  { value: "sibling", label: "兄弟姐妹", description: "逝者的兄弟或姐妹" },
  { value: "parent", label: "父母", description: "逝者的父亲或母亲" },
  { value: "friend", label: "朋友", description: "逝者的朋友" },
  { value: "colleague", label: "同事", description: "逝者的同事" },
  { value: "other", label: "其他", description: "其他关系" },
];

function ScopeCreate(): React.ReactElement {
  const navigate = useNavigate();
  const { createScope, resolveProfile, loading, error } = useSidecar();

  const [formData, setFormData] = useState({
    profile_name: "",
    scope_name: "",
    relationship_type: "",
    scope_description: "",
  });

  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [submitSuccess, setSubmitSuccess] = useState(false);

  /** 验证表单字段 */
  const validate = (): boolean => {
    const errors: Record<string, string> = {};

    if (!formData.profile_name.trim()) {
      errors.profile_name = "请输入逝者档案名称";
    }
    if (!formData.scope_name.trim()) {
      errors.scope_name = "请输入关系空间名称";
    }
    if (!formData.relationship_type) {
      errors.relationship_type = "请选择关系类型";
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  /** 处理表单提交 */
  const handleSubmit = async (e: FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();

    if (!validate()) {
      return;
    }

    try {
      const profilePayload = await resolveProfile({
        profile_name: formData.profile_name.trim(),
      });
      const deceasedProfileId = getProfileId(profilePayload);

      await createScope({
        deceased_profile_id: deceasedProfileId,
        scope_name: formData.scope_name.trim(),
        relationship_type: formData.relationship_type,
        scope_description: formData.scope_description.trim() || undefined,
      });

      setSubmitSuccess(true);

      // 延迟跳转，让用户看到成功提示
      setTimeout(() => {
        navigate("/settings");
      }, 1500);
    } catch (err) {
      // 错误已由 useSidecar 处理
      console.error("创建关系空间失败:", err);
    }
  };

  /** 处理表单字段变更 */
  const handleChange = (
    field: string,
    value: string,
  ): void => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    // 清除对应字段的错误
    if (formErrors[field]) {
      setFormErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  return (
    <div className="page-scope-create">
      <h2>创建关系空间</h2>
      <p className="text-muted">
        为逝者创建一个关系空间。不同类型的关系将继承不同的默认权限。
      </p>

      {submitSuccess && (
        <div className="scope-create-success">
          ✅ 关系空间创建成功！正在跳转到管理页面...
        </div>
      )}

      {error && !submitSuccess && (
        <div className="scope-create-error">
          ❌ 创建失败：{error}
        </div>
      )}

      <form className="scope-create-form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="profile_name" className="form-label">
            逝者档案名称 <span className="form-required">*</span>
          </label>
          <input
            id="profile_name"
            type="text"
            className={`form-input ${formErrors.profile_name ? "form-input-error" : ""}`}
            placeholder="输入名字，如 妈妈"
            value={formData.profile_name}
            onChange={(e) => handleChange("profile_name", e.target.value)}
            disabled={loading || submitSuccess}
          />
          {formErrors.profile_name && (
            <span className="form-error">{formErrors.profile_name}</span>
          )}
        </div>

        <div className="form-group">
          <label htmlFor="scope_name" className="form-label">
            关系空间名称 <span className="form-required">*</span>
          </label>
          <input
            id="scope_name"
            type="text"
            className={`form-input ${formErrors.scope_name ? "form-input-error" : ""}`}
            placeholder="例如：作为女儿、老同学"
            value={formData.scope_name}
            onChange={(e) => handleChange("scope_name", e.target.value)}
            disabled={loading || submitSuccess}
          />
          {formErrors.scope_name && (
            <span className="form-error">{formErrors.scope_name}</span>
          )}
        </div>

        <div className="form-group">
          <label htmlFor="relationship_type" className="form-label">
            关系类型 <span className="form-required">*</span>
          </label>
          <select
            id="relationship_type"
            className={`form-select ${formErrors.relationship_type ? "form-input-error" : ""}`}
            value={formData.relationship_type}
            onChange={(e) => handleChange("relationship_type", e.target.value)}
            disabled={loading || submitSuccess}
          >
            <option value="">— 请选择关系类型 —</option>
            {RELATIONSHIP_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label} — {opt.description}
              </option>
            ))}
          </select>
          {formErrors.relationship_type && (
            <span className="form-error">{formErrors.relationship_type}</span>
          )}
          {formData.relationship_type && (
            <span className="form-hint">
              {RELATIONSHIP_OPTIONS.find((o) => o.value === formData.relationship_type)?.description}
            </span>
          )}
        </div>

        <div className="form-group">
          <label htmlFor="scope_description" className="form-label">
            关系空间描述 <span className="form-optional">（可选）</span>
          </label>
          <textarea
            id="scope_description"
            className="form-textarea"
            placeholder="描述你与逝者的关系，帮助 AI 更好地理解你的需求"
            rows={3}
            value={formData.scope_description}
            onChange={(e) => handleChange("scope_description", e.target.value)}
            disabled={loading || submitSuccess}
          />
        </div>

        {/* 权限预览 */}
        {formData.relationship_type && (
          <div className="scope-permission-preview">
            <h3>默认权限预览</h3>
            <PermissionPreview relationshipType={formData.relationship_type} />
          </div>
        )}

        <div className="form-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => navigate("/settings")}
            disabled={loading || submitSuccess}
          >
            取消
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || submitSuccess}
          >
            {loading ? "创建中..." : "创建关系空间"}
          </button>
        </div>
      </form>
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

/** 关系类型对应的默认权限映射 */
const PERMISSION_OVERRIDES: Record<string, Record<string, string>> = {
  spouse: {
    can_view_intimate: "ask",
    can_interact_level3: "allow",
    can_view_medical: "allow",
    can_export_data: "allow",
  },
  child: {
    can_view_intimate: "deny",
    can_interact_level3: "ask",
    can_view_medical: "allow",
    can_view_financial: "ask",
  },
  sibling: {
    can_view_intimate: "ask",
    can_interact_level3: "ask",
    can_view_medical: "allow",
  },
  parent: {
    can_view_intimate: "deny",
    can_interact_level3: "ask",
    can_view_medical: "allow",
    can_view_financial: "ask",
  },
  friend: {
    can_view_intimate: "deny",
    can_view_financial: "deny",
    can_interact_level3: "deny",
  },
  colleague: {
    can_view_intimate: "deny",
    can_view_financial: "deny",
    can_interact_level3: "deny",
  },
  other: {},
};

const BASE_PERMISSIONS: Record<string, string> = {
  can_query_memory: "allow",
  can_browse_original: "ask",
  can_add_oral_history: "allow",
  can_elevate_shared: "ask",
  can_export_data: "deny",
  can_view_financial: "deny",
  can_view_medical: "deny",
  can_view_intimate: "deny",
  can_interact_level3: "ask",
  can_delete_scope: "deny",
};

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
  can_delete_scope: "删除关系空间",
};

const VALUE_LABELS: Record<string, string> = {
  allow: "✅ 允许",
  deny: "❌ 拒绝",
  ask: "⚠️ 需确认",
};

/** 权限预览组件：根据关系类型显示默认权限 */
function PermissionPreview({ relationshipType }: { relationshipType: string }): React.ReactElement {
  const overrides = PERMISSION_OVERRIDES[relationshipType] || {};
  const permissions = Object.entries(BASE_PERMISSIONS).map(([key, baseValue]) => ({
    key,
    label: PERMISSION_LABELS[key] || key,
    value: overrides[key] || baseValue,
    overridden: key in overrides,
  }));

  return (
    <table className="table table-compact">
      <thead>
        <tr>
          <th>权限</th>
          <th>默认值</th>
        </tr>
      </thead>
      <tbody>
        {permissions.map((perm) => (
          <tr key={perm.key} className={perm.overridden ? "perm-overridden" : ""}>
            <td>{perm.label}</td>
            <td>
              <span className={`perm-value perm-${perm.value}`}>
                {VALUE_LABELS[perm.value] || perm.value}
              </span>
              {perm.overridden && <span className="perm-override-badge">继承</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default ScopeCreate;
