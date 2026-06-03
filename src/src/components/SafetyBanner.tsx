/**
 * SafetyBanner — 动态安全提示横幅组件。
 *
 * 根据 SafetyDirective 的 action 类型显示不同级别的提示：
 * - ALLOW: 不显示
 * - SOFT_BREAK: 黄色提示条
 * - HARD_BREAK: 红色提示条
 * - ESCALATE: 深红色紧急提示条
 */
interface SafetyDirective {
  action: string;
  reason?: string;
  cooldown_minutes?: number;
}

interface SafetyBannerProps {
  directive: SafetyDirective | null;
  onDismiss?: () => void;
}

/** 动作级别配置 */
const ACTION_CONFIG: Record<string, { bg: string; icon: string; label: string }> = {
  SOFT_BREAK: {
    bg: "#FEF3C7",
    icon: "⚠️",
    label: "温馨提醒",
  },
  HARD_BREAK: {
    bg: "#FEE2E2",
    icon: "🛑",
    label: "会话暂停",
  },
  ESCALATE: {
    bg: "#991B1B",
    icon: "🆘",
    label: "安全提醒",
  },
};

function SafetyBanner({ directive, onDismiss }: SafetyBannerProps): React.ReactElement | null {
  // ALLOW 或无指令时不显示
  if (!directive || directive.action === "ALLOW") {
    return null;
  }

  const config = ACTION_CONFIG[directive.action];
  if (!config) {
    return null;
  }

  const isEscalate = directive.action === "ESCALATE";
  const textColor = isEscalate ? "#ffffff" : "#1a1a1a";
  const dismissColor = isEscalate ? "#ffffff" : "#666666";

  return (
    <div
      className="safety-banner"
      style={{ backgroundColor: config.bg }}
    >
      <div className="safety-banner-content">
        <span className="safety-banner-icon">{config.icon}</span>
        <span className="safety-banner-text" style={{ color: textColor }}>
          {config.label} — {directive.reason || "系统检测到安全风险"}
        </span>
        {directive.cooldown_minutes && directive.cooldown_minutes > 0 && (
          <span className="safety-banner-cooldown" style={{ color: textColor, opacity: 0.8 }}>
            （冷却 {directive.cooldown_minutes} 分钟）
          </span>
        )}
        {onDismiss && (
          <button
            className="safety-banner-close"
            onClick={onDismiss}
            aria-label="关闭安全提示"
            style={{ color: dismissColor }}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

export default SafetyBanner;