/**
 * Escalate — ESCALATE 危机资源组件。
 *
 * 当 SafetyMiddleware 返回 ESCALATE 动作时显示此组件。
 * 完全阻断对话，显示危机热线和专业帮助信息。
 */
interface SafetyDirective {
  action: string;
  reason?: string;
  cooldown_minutes?: number;
  template_id?: string;
}

interface EscalateProps {
  directive: SafetyDirective;
  templateText: string;
  onAcknowledge?: () => void;
}

/** 危机热线资源列表 */
const CRISIS_RESOURCES = [
  {
    name: "全国24小时心理援助热线",
    phone: "400-161-9995",
    description: "提供全天候免费心理危机干预服务",
  },
  {
    name: "北京心理危机研究与干预中心",
    phone: "010-82951332",
    description: "专业心理危机干预热线",
  },
  {
    name: "生命热线",
    phone: "400-821-1215",
    description: "全天候自杀预防热线",
  },
  {
    name: "希望24热线",
    phone: "400-161-9995",
    description: "24小时心理危机干预热线",
  },
];

function Escalate({ directive, templateText, onAcknowledge }: EscalateProps): React.ReactElement {
  return (
    <div className="safety-escalate">
      <div className="safety-escalate-icon">🆘</div>
      <div className="safety-escalate-content">
        <div className="safety-escalate-title">我们关心您的安全</div>
        <div className="safety-escalate-text">
          {templateText || directive.reason || "系统检测到您可能正在经历困难时刻，请寻求专业帮助。"}
        </div>

        <div className="safety-escalate-divider" />
        <div className="safety-escalate-subtitle">以下资源可以为您提供帮助：</div>

        <div className="safety-escalate-resources">
          {CRISIS_RESOURCES.map((resource) => (
            <div key={resource.phone} className="safety-escalate-resource">
              <div className="safety-escalate-resource-name">{resource.name}</div>
              <a
                className="safety-escalate-phone"
                href={`tel:${resource.phone}`}
              >
                📞 {resource.phone}
              </a>
              <div className="safety-escalate-resource-desc">{resource.description}</div>
            </div>
          ))}
        </div>

        <div className="safety-escalate-actions">
          <button className="btn safety-escalate-btn" onClick={onAcknowledge}>
            我已了解，寻求帮助
          </button>
        </div>
      </div>
    </div>
  );
}

export default Escalate;