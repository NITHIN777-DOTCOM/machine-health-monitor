// Formatting helpers: states -> label + icon + colour class, ML status text, forecast text,
// the "recovering" banner rule, number and limit formatting. Pure functions (unit-tested).
// Nothing here knows about specific sensors; names and units come from the registry.

import type {
  AlertSource, AnalysisDevice, DevState, Direction, ForecastEntry, Link, MlBlock, MlCause, Mode,
  Sensor, SourceType,
} from "../types";

/** Icon names drawn by components/Icon.tsx. */
export type IconName =
  | "ok" | "warning" | "critical" | "info" | "pulse" | "clock" | "off" | "spark"
  | "up" | "down" | "flat" | "plug" | "sun" | "moon" | "dot";

/** A colour tone: maps to CSS variables --tone-<tone>-bg / -fg / -line. */
export type Tone = "normal" | "warning" | "critical" | "ml" | "neutral" | "info";

export interface View {
  label: string;
  icon: IconName;
  tone: Tone;
}

// ---- device / overall state -----------------------------------------------------------

const STATE_VIEWS: Record<DevState, View> = {
  NORMAL: { label: "NORMAL", icon: "ok", tone: "normal" },
  WARNING: { label: "WARNING", icon: "warning", tone: "warning" },
  CRITICAL: { label: "CRITICAL", icon: "critical", tone: "critical" },
};

/** State -> label, icon and colour tone. State is never shown by colour alone. */
export function stateView(state: DevState | null | undefined): View {
  return state ? STATE_VIEWS[state] : { label: "NO DATA", icon: "dot", tone: "neutral" };
}

const ALERT_SOURCE_LABELS: Record<AlertSource, string | null> = {
  rules: "Rules",
  ml: "ML",
  both: "Both",
  none: null,
};

/** Chip text for analysis.alert_source; null when nothing is alerting. */
export function alertSourceLabel(source: AlertSource | null | undefined): string | null {
  return source ? ALERT_SOURCE_LABELS[source] : null;
}

// ---- "recovering" rule -------------------------------------------------------------------

const RECOVERING_PREFIX = "recovering, was: ";

/** Backend text for display: ">=" / "<=" as "≥" / "≤" (easier to read on a projector). */
export function prettyOps(text: string): string {
  return text.replace(/>=/g, "≥").replace(/<=/g, "≤");
}

/** Strip the backend's "recovering, was: " prefix from a reason or headline. */
export function stripRecovering(text: string | null | undefined): string {
  return prettyOps((text ?? "").split(RECOVERING_PREFIX).join(""));
}

/** How far the hold countdown must have progressed before "Recovering" is shown. A single
 *  row inside the margin band starts the counter; showing "recovering" then would make the
 *  banner flicker during an ongoing fault. */
export const RECOVERING_MIN_PROGRESS_S = 2;

/** True when the banner may say "Recovering": the device is clearing and the hold
 *  countdown has actually progressed (hold_remaining_s <= hold_seconds - 2). */
export function isRecovering(holdRemaining: number | null | undefined, holdSeconds: number): boolean {
  return holdRemaining != null && holdRemaining <= holdSeconds - RECOVERING_MIN_PROGRESS_S;
}

/** One level down: where the device goes when the hold countdown finishes. */
export function nextLevelDown(state: DevState): DevState {
  return state === "CRITICAL" ? "WARNING" : "NORMAL";
}

export interface BannerText {
  /** Main sentence. */
  headline: string;
  /** Smaller second line (e.g. what the alarm was), or null. */
  detail: string | null;
  recovering: boolean;
}

/** Banner text from the analysis block. Shows "Recovering - back to normal in N s" only
 *  when the rules' hold countdown has progressed; otherwise the active state and reason
 *  (without the "recovering, was:" wording). ML usually still flags the fault during the
 *  countdown (its window still holds it), and ML alone keeps the overall at WARNING, so
 *  WARNING -> NORMAL with an ML anomaly says the rules clear but ML is still active. */
export function bannerText(
  headline: string,
  device: Pick<AnalysisDevice, "state" | "reported" | "reason" | "hold_remaining_s">,
  alertSource: AlertSource,
  holdSeconds: number,
): BannerText {
  const rules = device.reported ?? device.state;
  if (rules !== "NORMAL" && alertSource !== "ml" && isRecovering(device.hold_remaining_s, holdSeconds)) {
    const target = nextLevelDown(rules);
    const secs = device.hold_remaining_s;
    const was = stripRecovering(device.reason);
    const text = target === "WARNING"
      ? `Recovering - down to WARNING in ${secs} s`
      : alertSource === "both"
        ? `Recovering - rules clear in ${secs} s; ML anomaly still active`
        : `Recovering - back to normal in ${secs} s`;
    return {
      headline: text,
      detail: was ? `was: ${was}` : null,
      recovering: true,
    };
  }
  return { headline: stripRecovering(headline), detail: null, recovering: false };
}

// ---- ML ------------------------------------------------------------------------------------

export interface MlView extends View {
  /** Second line, e.g. "7 s left" or the backend's message. */
  detail: string | null;
}

/** ML block -> label, icon, tone and a short detail line. */
export function mlView(ml: MlBlock | null | undefined): MlView {
  if (!ml) return { label: "NO DATA", icon: "dot", tone: "neutral", detail: null };
  if (ml.settling_remaining_s != null) {
    return { label: "SETTLING", icon: "clock", tone: "info", detail: `${ml.settling_remaining_s} s left (after warm start)` };
  }
  switch (ml.status) {
    case "OK":
      return { label: "OK", icon: "ok", tone: "normal", detail: "pattern looks normal" };
    case "ANOMALY":
      return {
        label: "ANOMALY", icon: "spark", tone: "ml",
        detail: ml.clear_remaining_s != null ? `clearing in ${ml.clear_remaining_s} s` : "pattern differs from normal",
      };
    case "WARMING_UP": {
      const s = ml.warmup_remaining_s;
      return { label: "WARMING UP", icon: "clock", tone: "info", detail: s != null ? `${Math.ceil(s)} s left` : null };
    }
    case "ML_UNAVAILABLE":
      return { label: "ML UNAVAILABLE", icon: "off", tone: "neutral", detail: ml.message };
    case "NO_MODEL":
      return { label: "NO MODEL", icon: "off", tone: "neutral", detail: ml.message ?? "rules only" };
    case "NEEDS_RETRAIN":
      return { label: "NEEDS RETRAIN", icon: "off", tone: "neutral", detail: ml.message ?? "sensor list changed; rules only" };
  }
}

/** Health 0-100 -> band. 50 is the anomaly threshold by construction of the score
 *  (100 = median normal, 50 = threshold); 60 is where an anomaly clears. */
export function healthTone(health: number | null | undefined): Tone {
  if (health == null) return "neutral";
  if (health < 50) return "ml";
  if (health <= 60) return "warning";
  return "normal";
}

export function healthLabel(health: number | null | undefined): string {
  if (health == null) return "no score";
  if (health < 50) return "unusual";
  if (health <= 60) return "borderline";
  return "healthy";
}

/** "Vibration unstable, z=4.1". */
export function causeText(cause: MlCause): string {
  return `${cause.text}, z=${cause.z.toFixed(1)}`;
}

// ---- forecast ----------------------------------------------------------------------------

function etaPart(level: "WARNING" | "CRITICAL", eta: string | null): string | null {
  if (eta == null) return null;
  return eta === "reached" ? `${level} reached` : `${level} in ${eta}`;
}

/** "Temperature: WARNING in ~1 min, CRITICAL in ~3 min", "Temperature: stable", ... from the
 *  forecast fields. Once critical is reached, the warn part is no longer news. */
export function forecastText(name: string, f: ForecastEntry | null | undefined): string {
  if (!f || f.status === "insufficient_data") return `${name}: collecting data`;
  if (f.to_critical === "reached") return `${name}: CRITICAL reached`;
  const parts = [etaPart("WARNING", f.to_warn), etaPart("CRITICAL", f.to_critical)]
    .filter((p): p is string => p != null);
  return `${name}: ${parts.length ? parts.join(", ") : "stable"}`;
}

/** Tone of a forecast: how soon a limit will be reached. */
export function forecastTone(f: ForecastEntry | null | undefined): Tone {
  if (!f) return "neutral";
  if (f.to_critical === "reached" || f.seconds_to_critical != null) return "critical";
  if (f.to_warn === "reached" || f.seconds_to_warn != null) return "warning";
  return f.status === "insufficient_data" ? "neutral" : "normal";
}

export function trendIcon(trend: ForecastEntry["trend"]): IconName {
  return trend === "rising" ? "up" : trend === "falling" ? "down" : "flat";
}

// ---- sensor values and limits -------------------------------------------------------------

function breaches(value: number, limit: number | null, direction: Direction): boolean {
  if (limit == null) return false;
  return direction === "above" ? value >= limit : value <= limit;
}

/** A sensor's own level from its value vs. its warn/critical limits (no hysteresis:
 *  this is the instant reading, the device state machine adds the hold). */
export function sensorLevel(sensor: Pick<Sensor, "warn" | "critical" | "direction">, value: number): DevState {
  if (breaches(value, sensor.critical, sensor.direction)) return "CRITICAL";
  if (breaches(value, sensor.warn, sensor.direction)) return "WARNING";
  return "NORMAL";
}

/** Up to 2 decimals, no trailing zeros: 29.5, 64, 4.98. */
export function formatValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return String(Math.round(value * 100) / 100);
}

/** "warn ≥ 32 · crit ≥ 35 °C", or "no limits set" when both are TBD. */
export function limitsText(sensor: Pick<Sensor, "warn" | "critical" | "direction" | "unit">): string {
  const op = sensor.direction === "above" ? "≥" : "≤";
  const parts: string[] = [];
  if (sensor.warn != null) parts.push(`warn ${op} ${formatValue(sensor.warn)}`);
  if (sensor.critical != null) parts.push(`crit ${op} ${formatValue(sensor.critical)}`);
  if (!parts.length) return "no limits set";
  return `${parts.join(" · ")} ${sensor.unit}`.trim();
}

// ---- top bar: mode badge and connection -----------------------------------------------------

export interface ModeView {
  label: string;
  cls: Mode;
  title: string;
}

const MODE_VIEWS: Record<Mode, ModeView> = {
  live: { label: "LIVE", cls: "live", title: "Live data from the Arduino" },
  recorded: { label: "RECORDED", cls: "recorded", title: "Replaying a recording" },
  simulated: { label: "SIMULATED", cls: "simulated", title: "Generated by the backend simulator" },
};

const SOURCE_MODE: Record<SourceType, Mode> = { serial: "live", replay: "recorded", simulator: "simulated" };

/** The mode of the newest row; before any row, the mode implied by the source type. */
export function modeView(rowMode: Mode | null | undefined, source: SourceType | null | undefined): ModeView | null {
  const mode = rowMode ?? (source ? SOURCE_MODE[source] : null);
  return mode ? MODE_VIEWS[mode] : null;
}

export interface LinkView extends View {
  /** True when the shown data is not current (grey it out). */
  stale: boolean;
}

/** Connection indicator. The WebSocket state wins: if the dashboard itself is cut off,
 *  the backend's link field is old news. */
export function linkView(ws: "connecting" | "open" | "closed", link: Link | null | undefined): LinkView {
  if (ws !== "open") {
    return ws === "connecting"
      ? { label: "Connecting", icon: "clock", tone: "info", stale: true }
      : { label: "Backend offline", icon: "plug", tone: "critical", stale: true };
  }
  switch (link) {
    case "ok": return { label: "Receiving data", icon: "pulse", tone: "normal", stale: false };
    case "starting": return { label: "Starting", icon: "clock", tone: "info", stale: false };
    case "no_data": return { label: "No data", icon: "warning", tone: "warning", stale: true };
    case "down": return { label: "Source down", icon: "plug", tone: "critical", stale: true };
    case "finished": return { label: "Replay finished", icon: "info", tone: "neutral", stale: true };
    default: return { label: "Waiting", icon: "clock", tone: "neutral", stale: true };
  }
}

/** "23 Oct 2026, 20:16" from an ISO timestamp; the input if it can't be parsed. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
