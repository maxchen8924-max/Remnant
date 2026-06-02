/**
 * Header component for Remnant.
 * Displays the deceased person's name and current scope.
 * Will be enhanced with scope switching and quick actions.
 */
function Header(): React.ReactElement {
  return (
    <header className="header">
      <div className="header-left">
        <span className="header-scope-label">当前 Scope:</span>
        <span className="header-scope-name">默认</span>
      </div>
      <div className="header-right">
        <span className="header-status">Sidecar: 未知</span>
      </div>
    </header>
  );
}

export default Header;