// Formatting helpers: states -> label + icon + colour class, ML status text, forecast text,
// the "recovering" banner rule, number and limit formatting. Pure functions (unit-tested).
// Nothing here knows about specific sensors; names and units come from the registry.

import type {
  AlertSource, AnalysisDevice, DevState, Direction, ForecastEntry, Link, MlBlock, MlCause, Mode,
  Sensor, SourceType, Status, VersionInfo,
} from "../types";

/** Icon names drawn by components/Icon.tsx. */
export type IconName =
  | "ok" | "warning" | "critical" | "info" | "pulse" | "clock" | "off" | "spark"
  | "up" | "down" | "flat" | "plug" | "sun" | "moon" | "settings" | "play" | "pause" | "stop"
  | "record" | "file" | "sim" | "loop" | "close";

/** A colour tone: maps to CSS variables --tone-<tone>-bg / -fg / -line. */
export type Tone = "normal" | "warning" | "critical" | "ml" | "neutral" | "info";

export interface View {
  label: string;
  icon: IconName;
  tone: Tone;
}

// ---- device / overall state -----------------------------------------------------------

const STATE_VIEWS: Record<DevState, View> = {
  NORMAL: { label: "Normal", icon: "ok", tone: "normal" },
  WARNING: { label: "Warning", icon: "warning", tone: "warning" },
  CRITICAL: { label: "Critical", icon: "critical", tone: "critical" },
};

/** State -> label, icon and colour tone. State is never shown by colour alone. */
export function stateView(state: DevState | null | undefined): View {
  return state ? STATE_VIEWS[state] : { label: "No data", icon: "clock", tone: "neutral" };
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

/** Banner text from the analysis block (headline + its detail line). Shows "Recovering - back to normal in N s" only
 *  when the rules' hold countdown has progressed; otherwise the active state and reason
 *  (without the "recovering, was:" wording). ML usually still flags the fault during the
 *  countdown (its window still holds it), and ML alone keeps the overall at WARNING, so
 *  WARNING -> NORMAL with an ML anomaly says the rules clear but ML is still active. */
export function bannerText(
  headline: string,
  headlineDetail: string | null,
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
  return { headline: stripRecovering(headline), detail: headlineDetail ? prettyOps(headlineDetail) : null, recovering: false };
}

// ---- ML ------------------------------------------------------------------------------------

export interface MlView extends View {
  /** Second line, e.g. "7 s left" or the backend's message. */
  detail: string | null;
}

/** ML block -> label, icon, tone and a short detail line. */
export function mlView(ml: MlBlock | null | undefined): MlView {
  if (!ml) return { label: "No data", icon: "clock", tone: "neutral", detail: null };
  if (ml.settling_remaining_s != null) {
    return { label: "Settling", icon: "clock", tone: "info", detail: `${ml.settling_remaining_s} s left (after warm start)` };
  }
  switch (ml.status) {
    case "OK":
      return { label: "OK", icon: "ok", tone: "normal", detail: "pattern looks normal" };
    case "ANOMALY":
      return {
        label: "Anomaly", icon: "spark", tone: "ml",
        detail: ml.clear_remaining_s != null ? `clearing in ${ml.clear_remaining_s} s` : "pattern differs from normal",
      };
    case "WARMING_UP": {
      const s = ml.warmup_remaining_s;
      return { label: "Warming up", icon: "clock", tone: "info", detail: s != null ? `${Math.ceil(s)} s left` : null };
    }
    case "ML_UNAVAILABLE":
      return { label: "ML unavailable", icon: "off", tone: "neutral", detail: ml.message };
    case "NO_MODEL":
      return { label: "No model", icon: "off", tone: "neutral", detail: ml.message ?? "rules only" };
    case "NEEDS_RETRAIN":
      return { label: "Needs retrain", icon: "off", tone: "neutral", detail: ml.message ?? "sensor list changed; rules only" };
  }
}

/** ML anomaly / clear health levels; the backend sends the real ones (status.ml_thresholds). */
export interface HealthLevels {
  anomaly_health: number;
  clear_health: number;
}

/** Used only until the first status message arrives. */
export const DEFAULT_HEALTH_LEVELS: HealthLevels = { anomaly_health: 50, clear_health: 60 };

/** Health 0-100 -> band: below the anomaly level "unusual", up to the clear level
 *  "borderline", above it "healthy". */
export function healthTone(health: number | null | undefined, levels: HealthLevels = DEFAULT_HEALTH_LEVELS): Tone {
  if (health == null) return "neutral";
  if (health < levels.anomaly_health) return "ml";
  if (health <= levels.clear_health) return "warning";
  return "normal";
}

export function healthLabel(health: number | null | undefined, levels: HealthLevels = DEFAULT_HEALTH_LEVELS): string {
  if (health == null) return "no score";
  if (health < levels.anomaly_health) return "unusual";
  if (health <= levels.clear_health) return "borderline";
  return "healthy";
}

// ---- ML causes in plain words ------------------------------------------------------------
// |z| = how many training standard deviations a window feature is from its normal mean.
// Bands (same table as backend/app/ml/scorer.py and DATA_CONTRACT.md section 9):
//   |z| < 2 normal · 2-3 slight · 3-6 clear · >= 6 far

export type ZBand = "normal" | "slight" | "clear" | "far";

export function zBand(z: number): ZBand {
  const a = Math.abs(z);
  return a >= 6 ? "far" : a >= 3 ? "clear" : a >= 2 ? "slight" : "normal";
}

const PLAIN: Record<"level" | "std" | "slope", Record<"up" | "down", Record<Exclude<ZBand, "normal">, string>>> = {
  level: {
    up: { slight: "slightly high", clear: "above normal", far: "far above normal" },
    down: { slight: "slightly low", clear: "below normal", far: "far below normal" },
  },
  std: {
    up: { slight: "slightly unstable", clear: "unstable", far: "very unstable" },
    down: { slight: "slightly steady", clear: "unusually steady", far: "unusually steady" },
  },
  slope: {
    up: { slight: "rising slightly", clear: "rising", far: "rising fast" },
    down: { slight: "falling slightly", clear: "falling", far: "falling fast" },
  },
};

/** "far above normal", "unstable", "rising", "normal", ... for a feature (e.g.
 *  "vib_count__std") and its z. */
export function causeWords(feature: string, z: number): string {
  const band = zBand(z);
  if (band === "normal") return "normal";
  const stat = feature.split("__")[1] ?? "mean";
  const kind = stat === "std" || stat === "slope" ? stat : "level";
  return PLAIN[kind][z >= 0 ? "up" : "down"][band];
}

/** "Sound level (peak deviation)" -> "Sound level". */
export function shortName(displayName: string): string {
  return displayName.replace(/\s*\(.*?\)/g, "").trim() || displayName;
}

/** "Vibration: far above normal". The z value goes in the tooltip only (causeTooltip). */
export function causeText(cause: MlCause, displayName?: string): string {
  const name = shortName(displayName ?? cause.text.split(":")[0] ?? cause.sensor);
  return `${name}: ${causeWords(cause.feature, cause.z)}`;
}

/** The causes worth listing, at most 2 with |z| >= 2. Empty while ML is calm (not ANOMALY and
 *  health above the clear level), so a normal screen says "Nothing unusual" instead of
 *  "slightly high" noise. */
export function visibleCauses(ml: MlBlock | null | undefined, levels: HealthLevels = DEFAULT_HEALTH_LEVELS): MlCause[] {
  if (!ml || ml.health == null) return [];
  if (ml.status !== "ANOMALY" && ml.health > levels.clear_health) return [];
  return ml.causes.filter((c) => Math.abs(c.z) >= 2).slice(0, 2);
}

/** Above this |z| the exact number means little (and the backend caps it at 99). */
export const Z_TOOLTIP_MAX = 10;

/** Tooltip: "z = 4.1: 4.1 standard deviations above the normal mean (window feature ...)".
 *  Never shows a capped value like z = 99. */
export function causeTooltip(cause: MlCause): string {
  const a = Math.abs(cause.z);
  const side = cause.z >= 0 ? "above" : "below";
  const what = a >= Z_TOOLTIP_MAX
    ? `more than ${Z_TOOLTIP_MAX} standard deviations ${side} the normal mean`
    : `z = ${cause.z.toFixed(1)}: ${a.toFixed(1)} standard deviations ${side} the normal mean`;
  return `${what} (window feature ${cause.feature})`;
}

// ---- forecast ----------------------------------------------------------------------------

function etaPart(level: "warning" | "critical", eta: string | null): string | null {
  if (eta == null) return null;
  return eta === "reached" ? `${level} reached` : `${level} in ${eta}`;
}

/** "Temperature: warning in ~1 min, critical in ~3 min", "Temperature: stable",
 *  "Temperature: no data", ... Once critical is reached, the warn part is no longer news. */
export function forecastText(name: string, f: ForecastEntry | null | undefined): string {
  if (f?.status === "no_data") return `${name}: no data`;
  if (!f || f.status === "insufficient_data") return `${name}: collecting data`;
  if (f.to_critical === "reached") return `${name}: critical reached`;
  const parts = [etaPart("warning", f.to_warn), etaPart("critical", f.to_critical)]
    .filter((p): p is string => p != null);
  return `${name}: ${parts.length ? parts.join(", ") : "stable"}`;
}

/** Tone of a forecast: how soon a limit will be reached. */
export function forecastTone(f: ForecastEntry | null | undefined): Tone {
  if (!f) return "neutral";
  if (f.to_critical === "reached" || f.seconds_to_critical != null) return "critical";
  if (f.to_warn === "reached" || f.seconds_to_warn != null) return "warning";
  return f.status === "insufficient_data" || f.status === "no_data" ? "neutral" : "normal";
}

export type Confidence = "low" | "medium" | "high";

/** Fit quality of the forecast line in words. R² bands: < 0.6 low (the backend does not
 *  trust a trend below forecast_min_r2 = 0.6), 0.6-0.85 medium, >= 0.85 high. */
export function confidence(r2: number | null | undefined): Confidence | null {
  if (r2 == null || !Number.isFinite(r2)) return null;
  return r2 >= 0.85 ? "high" : r2 >= 0.6 ? "medium" : "low";
}

/** Second line of a forecast: "rising · confidence: high", "no clear trend", ... */
export function forecastDetail(f: ForecastEntry | null | undefined): string {
  if (!f || f.status === "insufficient_data") return "not enough data yet";
  if (f.status === "no_data") return "sensor has no current reading";
  if (f.trend === "rising" || f.trend === "falling") return `${f.trend} · confidence: ${confidence(f.r2) ?? "low"}`;
  return "no clear trend";
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

/** Notice for link "no_data". Lines arriving but rejected (wrong sketch or baud rate) is a
 *  different problem from a silent port (cable, board), so it gets a different hint. */
export function noDataNotice(s: Pick<Status, "silent_s" | "rejecting" | "rejected_recent">): string {
  if (s.rejecting) {
    const n = s.rejected_recent;
    return `The Arduino is sending data, but not in the expected format (${n} line${n === 1 ? "" : "s"} rejected). ` +
      "Is the correct sketch uploaded?";
  }
  return `The data source is silent (no rows for ${Math.round(s.silent_s)} s). Check the USB cable and the Arduino.`;
}

/** Card value for a sensor reading: "> 400" when it is at the sensor's out-of-range value
 *  (nothing in range), else formatValue(). */
export function sensorValueText(sensor: Pick<Sensor, "out_of_range_value">, value: number): { text: string; clear: boolean } {
  const oor = sensor.out_of_range_value;
  if (oor != null && value >= oor) return { text: `> ${formatValue(oor)}`, clear: true };
  return { text: formatValue(value), clear: false };
}

/** "23 Oct 2026, 20:16" from an ISO timestamp; the input if it can't be parsed. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Footer version: "v0.6.0 · v0.6.0-0-gabc1234 · built 2026-10-24" (dev: "v0.6.0 · abc1234-dirty · dev"). */
export function versionText(v: VersionInfo | null | undefined): string | null {
  if (!v) return null;
  return [`v${v.version}`, v.git, v.build_date ? `built ${v.build_date}` : v.frozen ? null : "dev"]
    .filter(Boolean).join(" · ");
}
