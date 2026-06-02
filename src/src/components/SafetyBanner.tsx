import { useState } from "react";

/**
 * Safety banner component for Remnant.
 * Displays a warning banner when the safety fuse is triggered.
 * By default, the banner is hidden and only shows when safety issues are detected.
 */
function SafetyBanner(): React.ReactElement | null {
  const [visible, setVisible] = useState<boolean>(false);

  if (!visible) {
    return null;
  }

  return (
    <div className="safety-banner">
      <div className="safety-banner-content">
        <span className="safety-banner-icon">⚠️</span>
        <span className="safety-banner-text">
          安全熔断已触发 — 部分功能已暂停，请在安全设置中检查详情
        </span>
        <button
          className="safety-banner-close"
          onClick={() => setVisible(false)}
          aria-label="关闭安全提示"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export default SafetyBanner;