/**
 * HardBreak — HARD_BREAK 强制暂停组件。
 *
 * 当 SafetyMiddleware 返回 HARD_BREAK 动作时显示此组件。
 * 强制暂停对话，用户不可继续，显示冷却时间。
 */
interface SafetyDirective {
  action: string;
  reason?: string;
  cooldown_minutes?: number;
  template_id?: string;
}

interface HardBreakProps {
  directive: SafetyDirective;
  templateText: string;
  onAcknowledge?: () => void;
}

function HardBreak({ directive, templateText, onAcknowledge }: HardBreakProps): React.ReactElement {
  return (
    <div className="safety-hard-break">
      <div className="safety-hard-break-icon">🛑</div>
      <div className="safety-hard-break-content">
        <div className="safety-hard-break-title">会话暂停</div>
        <div className="safety-hard-break-text">{templateText || directive.reason || "当前会话已达到安全限制，需要休息。"}</div>
        {directive.cooldown_minutes && directive.cooldown_minutes > 0 && (
          <div className="safety-hard-break-cooldown">
            冷却时间：{directive.cooldown_minutes} 分钟后可重新开始
          </div>
        )}
        <div className="safety-hard-break-actions">
          <button className="btn btn-danger" onClick={onAcknowledge}>
            我明白了
          </button>
        </div>
      </div>
    </div>
  );
}

export default HardBreak;