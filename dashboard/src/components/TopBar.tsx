import type { ReactNode } from "react";
import type { Theme } from "../hooks/useTheme";
import type { LinkView, ModeView } from "../lib/format";
import { Icon } from "./Icon";

interface Props {
  mode: ModeView | null;
  link: LinkView;
  theme: Theme;
  onToggleTheme: () => void;
  /** Extra buttons on the right (the Controls toggle). */
  children?: ReactNode;
}

export function TopBar({ mode, link, theme, onToggleTheme, children }: Props) {
  const other = theme === "dark" ? "light" : "dark";
  return (
    <header className="topbar">
      <div className="brand">
        <Icon name="pulse" size={20} className="brand-mark" />
        <div>
          <h1>Machine Health Monitor</h1>
          <div className="brand-sub">BCSE305L Embedded Systems</div>
        </div>
      </div>
      <div className="topbar-right">
        {mode ? (
          <span className={`mode-badge mode-${mode.cls}`} title={mode.title} data-testid="mode-badge">
            <span className="mode-dot" aria-hidden="true" />
            {mode.label}
          </span>
        ) : (
          <span className="mode-badge mode-unknown"><span className="mode-dot" aria-hidden="true" />NO SOURCE</span>
        )}
        <span className="link" data-testid="link">
          <span className={`dot dot-${link.tone}`} aria-hidden="true" />
          {link.label}
        </span>
        {children}
        <button
          type="button"
          className="btn btn-icon"
          onClick={onToggleTheme}
          aria-label={`Switch to ${other} theme`}
          title={`Switch to ${other} theme`}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} />
        </button>
      </div>
    </header>
  );
}
