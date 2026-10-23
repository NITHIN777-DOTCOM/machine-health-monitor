import type { Theme } from "../hooks/useTheme";
import type { LinkView, ModeView } from "../lib/format";
import { Icon } from "./Icon";

interface Props {
  mode: ModeView | null;
  link: LinkView;
  theme: Theme;
  onToggleTheme: () => void;
}

const MODE_ICON = { live: "dot", recorded: "clock", simulated: "spark" } as const;

export function TopBar({ mode, link, theme, onToggleTheme }: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        <Icon name="pulse" size={28} />
        <span>Machine Health Monitor</span>
      </div>
      <div className="topbar-right">
        {mode ? (
          <span className={`mode-badge mode-${mode.cls}`} title={mode.title} data-testid="mode-badge">
            <Icon name={MODE_ICON[mode.cls]} size={18} />
            {mode.label}
          </span>
        ) : (
          <span className="mode-badge mode-unknown">NO SOURCE</span>
        )}
        <span className={`link tone-text-${link.tone}`} data-testid="link">
          <Icon name={link.icon} size={20} />
          {link.label}
        </span>
        <button
          type="button"
          className="theme-toggle"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
          {theme === "dark" ? "Light" : "Dark"}
        </button>
      </div>
    </header>
  );
}
