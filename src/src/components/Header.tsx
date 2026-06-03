/**
 * Header component for Remnant.
 * Displays the current relationship space and sidecar status.
 */
function Header(): React.ReactElement {
  return (
    <header className="header">
      <div className="header-left">
        <span className="header-scope-label">当前关系空间:</span>
        <span className="header-scope-name">默认</span>
      </div>
      <div className="header-right">
        <span className="header-status">Sidecar: 未知</span>
      </div>
    </header>
  );
}

export default Header;
