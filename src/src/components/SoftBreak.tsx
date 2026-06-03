/**
 * SoftBreak — SOFT_BREAK 安全提示组件。
 *
 * 当 SafetyMiddleware 返回 SOFT_BREAK 动作时显示此组件。
 * 温和提示用户注意安全，但不阻断对话，用户可以选择继续。
 */
interface SafetyDirective {
  action: string;
  reason?: string;
  cooldown_minutes?: number;
  template_id?: string;
}

interface SoftBreakProps {
  directive: SafetyDirective;
  templateText: string;
  onAcknowledge?: () => void;
  onContinue?: () => void;
}

function SoftBreak({ directive, templateText, onAcknowledge, onContinue }: SoftBreakProps): React.ReactElement {
  return (
    <div className="safety-soft-break">
      <div className="safety-soft-break-icon">⚠️</div>
      <div className="safety-soft-break-content">
        <div className="safety-soft-break-title">温馨提醒</div>
        <div className="safety-soft-break-text">{templateText || directive.reason || "系统检测到您可能需要休息一下。"}</div>
        {directive.cooldown_minutes && directive.cooldown_minutes > 0 && (
          <div className="safety-soft-break-cooldown">
            建议冷却时间：{directive.cooldown_minutes} 分钟
          </div>
        )}
        <div className="safety-soft-break-actions">
          <button className="btn btn-secondary" onClick={onAcknowledge}>
            我知道了
          </button>
          <button className="btn btn-warning" onClick={onContinue}>
            继续对话
          </button>
        </div>
      </div>
    </div>
  );
}

export default SoftBreak;