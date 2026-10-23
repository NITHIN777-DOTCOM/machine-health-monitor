import { useMemo } from "react";
import { DeviceCard } from "./components/DeviceCard";
import { Footer } from "./components/Footer";
import { ForecastPanel } from "./components/ForecastPanel";
import { Icon } from "./components/Icon";
import { MlCard } from "./components/MlCard";
import { SensorCards } from "./components/SensorCards";
import { StatusBanner } from "./components/StatusBanner";
import { TopBar } from "./components/TopBar";
import { TrendCharts } from "./components/TrendCharts";
import { useDashboard, type DashboardData } from "./hooks/useDashboard";
import { useTheme } from "./hooks/useTheme";
import { enabledSensors } from "./lib/cards";
import { linkView, modeView } from "./lib/format";

const DEFAULT_HOLD_S = 5;
const HEALTH_LINES = [{ y: 50, label: "anomaly 50", kind: "crit" as const }];

/** Why the data on screen may be old; null when it is current. */
function connectionNotice(d: DashboardData): string | null {
  if (d.ws === "closed") {
    const when = d.retryInS ? `in ${d.retryInS} s` : "now";
    return `Connection to the backend lost - reconnecting ${when}. Showing the last data received.`;
  }
  if (d.ws === "connecting") return d.loaded ? "Reconnecting to the backend..." : "Connecting to the backend...";
  switch (d.status?.link) {
    case "no_data":
      return `The data source is silent (no rows for ${d.status.data_age_s ?? "?"} s). Check the USB cable and the Arduino.`;
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
  const link = linkView(d.ws, d.status?.link);
  const mode = modeView(d.row?.mode, d.status?.source);
  const sensors = useMemo(() => enabledSensors(d.registry), [d.registry]);
  const holdSeconds = d.status?.device.hold_seconds ?? DEFAULT_HOLD_S;
  const notice = connectionNotice(d);

  return (
    <div className="app">
      <TopBar mode={mode} link={link} theme={theme} onToggleTheme={toggleTheme} />
      {notice && (
        <div className={`notice ${link.stale ? "notice-bad" : ""}`} role="status" data-testid="notice">
            <Icon name={link.icon} />
          {notice}
        </div>
      )}
      <main className={link.stale && d.loaded ? "stale" : undefined}>
        <StatusBanner analysis={d.analysis} holdSeconds={holdSeconds} />
        <div className="cards-row">
          <DeviceCard device={d.analysis?.device ?? null} holdSeconds={holdSeconds} />
          <MlCard ml={d.analysis?.ml ?? null} />
          <ForecastPanel analysis={d.analysis} registry={d.registry} />
        </div>
        <SensorCards registry={d.registry} row={d.row} />
        <TrendCharts sensors={sensors} points={d.points} healthLines={HEALTH_LINES} />
      </main>
      <Footer status={d.status} />
    </div>
  );
}
