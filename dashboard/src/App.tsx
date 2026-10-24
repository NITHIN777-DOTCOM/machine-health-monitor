import { useMemo, useState } from "react";
import { ControlsPanel } from "./components/ControlsPanel";
import { DeviceCard } from "./components/DeviceCard";
import { Footer } from "./components/Footer";
import { ForecastPanel } from "./components/ForecastPanel";
import { Icon } from "./components/Icon";
import { MlCard } from "./components/MlCard";
import { RecIndicator } from "./components/RecIndicator";
import { SensorCards } from "./components/SensorCards";
import { StatusBanner } from "./components/StatusBanner";
import { TopBar } from "./components/TopBar";
import { TrendCharts } from "./components/TrendCharts";
import { useDashboard, type DashboardData } from "./hooks/useDashboard";
import { useTheme } from "./hooks/useTheme";
import { enabledSensors } from "./lib/cards";
import { DEFAULT_HEALTH_LEVELS, linkView, modeView, noDataNotice } from "./lib/format";

const DEFAULT_HOLD_S = 5;

/** Why the data on screen may be old; null when it is current. */
function connectionNotice(d: DashboardData): string | null {
  if (d.ws === "closed") {
    const when = d.retryInS ? `in ${d.retryInS} s` : "now";
    return `Connection to the backend lost - reconnecting ${when}. Showing the last data received.`;
  }
  if (d.ws === "connecting") return d.loaded ? "Reconnecting to the backend..." : "Connecting to the backend...";
  switch (d.status?.link) {
    case "no_data":
      return noDataNotice(d.status);
    case "down":
      return `Data source error: ${d.status.last_error ?? "source is down"}. Showing the last data received.`;
    case "finished":
      return "Replay finished. Showing the last data of the recording.";
    default:
      return d.error ? `Could not load from the backend: ${d.error}` : null;
  }
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const d = useDashboard();
  const [controlsOpen, setControlsOpen] = useState(false);
  const link = linkView(d.ws, d.status?.link);
  const mode = modeView(d.row?.mode, d.status?.source);
  const sensors = useMemo(() => enabledSensors(d.registry), [d.registry]);
  const holdSeconds = d.status?.device.hold_seconds ?? DEFAULT_HOLD_S;
  const notice = connectionNotice(d);
  const levels = d.status?.ml_thresholds ?? DEFAULT_HEALTH_LEVELS;
  const healthLines = useMemo(() => [
    { y: levels.clear_health, label: `clear ${levels.clear_health}`, kind: "warn" as const, dy: -7 },
    { y: levels.anomaly_health, label: `anomaly ${levels.anomaly_health}`, kind: "crit" as const, dy: 7 },
  ], [levels.anomaly_health, levels.clear_health]);

  return (
    <div className="app">
      <TopBar mode={mode} link={link} theme={theme} onToggleTheme={toggleTheme}>
        <RecIndicator rec={d.status?.recording} />
        <button type="button" className="btn" aria-pressed={controlsOpen} aria-expanded={controlsOpen}
          onClick={() => setControlsOpen((o) => !o)} data-testid="controls-toggle">
          <Icon name="settings" /> Controls
        </button>
      </TopBar>
      {notice && (
        <div className={`notice ${link.stale ? "notice-bad" : ""}`} role="status" data-testid="notice">
            <Icon name={link.icon} />
          {notice}
        </div>
      )}
      <div className="layout">
      <main className={link.stale && d.loaded ? "stale" : undefined}>
        <StatusBanner analysis={d.analysis} holdSeconds={holdSeconds} />
        <div className="cards-row">
          <DeviceCard device={d.analysis?.device ?? null} holdSeconds={holdSeconds} />
          <MlCard ml={d.analysis?.ml ?? null} registry={d.registry} levels={levels} />
          <ForecastPanel analysis={d.analysis} registry={d.registry} />
        </div>
        <SensorCards registry={d.registry} row={d.row} />
        <TrendCharts sensors={sensors} points={d.points} healthLines={healthLines} />
      </main>
      {controlsOpen && <ControlsPanel status={d.status} onClose={() => setControlsOpen(false)} />}
      </div>
      <Footer status={d.status} />
    </div>
  );
}
