// Control panel logic: which source is active, what the Live button may do, request
// bodies, error text, elapsed time and replay progress. Pure functions (unit-tested);
// components/ControlsPanel.tsx only draws them.

import type { Status } from "../types";

export type SourceKind = "live" | "simulated" | "recorded";

export const SPEEDS = [1, 5, 10] as const;
export type Speed = (typeof SPEEDS)[number];

/** Scenario buttons, in demo order. Only those the backend lists are shown. */
export const SCENARIOS: { key: string; label: string }[] = [
  { key: "normal", label: "Normal" },
  { key: "sudden_fault", label: "Sudden fault" },
  { key: "slow_drift", label: "Slow drift" },
  { key: "recovery", label: "Recovery" },
  { key: "sensor_fault", label: "Sensor fault" },
];

/** The "Fast-forward drift" demo: slow drift at 10x, so the trend and the forecast show
 *  within a minute or two. */
export const FAST_FORWARD = { scenario: "slow_drift", speed: 10 } as const;

export function availableScenarios(status: Status | null): { key: string; label: string }[] {
  const listed = status?.scenarios ?? [];
  return SCENARIOS.filter((s) => listed.includes(s.key));
}

/** The running source as the user thinks of it. */
export function activeKind(status: Status | null): SourceKind | null {
  switch (status?.source) {
    case "serial": return "live";
    case "simulator": return "simulated";
    case "replay": return "recorded";
    default: return null;
  }
}

export interface LiveOption {
  enabled: boolean;
  /** Why Live is disabled, or which port it will use. */
  note: string | null;
}

/** Live (Arduino) is only offered when the backend says serial can work. */
export function liveOption(status: Status | null): LiveOption {
  if (!status) return { enabled: false, note: "Not connected to the backend" };
  const s = status.serial;
  if (!s) return { enabled: true, note: null };
  return s.available
    ? { enabled: true, note: s.port ? `Arduino on ${s.port}` : null }
    : { enabled: false, note: s.note ?? "Serial is not available" };
}

// ---- request bodies (POST /api/source) ----------------------------------------------------

export interface SourceBody {
  type: "simulator" | "serial" | "replay";
  scenario?: string;
  speed?: number;
  file?: string;
  loop?: boolean;
}

export const scenarioBody = (scenario: string, speed: number): SourceBody => ({ type: "simulator", scenario, speed });
export const replayBody = (file: string, speed: number, loop: boolean): SourceBody => ({ type: "replay", file, speed, loop });
export const liveBody = (): SourceBody => ({ type: "serial" });

export function isActiveScenario(status: Status | null, scenario: string): boolean {
  return status?.source === "simulator" && status.scenario === scenario;
}

// ---- errors --------------------------------------------------------------------------------

/** Readable text for a failed request: HTTP status + FastAPI's {"detail": ...}. */
export function apiErrorText(httpStatus: number | null, detail: unknown): string {
  if (httpStatus == null) return "Backend not reachable. Is it running on port 8000?";
  let text = "";
  if (typeof detail === "string") text = detail;
  else if (Array.isArray(detail)) {
    // 422 validation errors: [{loc, msg, ...}]
    text = detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d))).join("; ");
  } else if (detail != null) text = JSON.stringify(detail);
  return friendlyError(text || `HTTP ${httpStatus}`);
}

/** Known backend/OS wording -> what to do about it. */
export function friendlyError(text: string): string {
  if (/busy|access is denied|permissionerror|errno 1[36]/i.test(text)) {
    return "Port busy: close the Arduino IDE Serial Monitor (or any other program using the port).";
  }
  if (/MHM_SOURCE=simulator/.test(text)) {
    return "Serial is disabled: the app runs in simulator-only mode. Close it and start it with Start.bat to use the Arduino.";
  }
  return text;
}

// ---- in-flight state ------------------------------------------------------------------------

export interface ActionState {
  /** Key of the request in flight, or null. All buttons are disabled while one runs. */
  busy: string | null;
  error: string | null;
}

export type ActionEvent =
  | { type: "start"; key: string }
  | { type: "ok" }
  | { type: "fail"; error: string }
  | { type: "dismiss" };

export const IDLE: ActionState = { busy: null, error: null };

export function actionReducer(state: ActionState, ev: ActionEvent): ActionState {
  switch (ev.type) {
    case "start": return { busy: ev.key, error: null };
    case "ok": return { busy: null, error: null };
    case "fail": return { busy: null, error: ev.error };
    case "dismiss": return { ...state, error: null };
  }
}

// ---- time and progress ------------------------------------------------------------------------

/** "0:07", "12:34", "1:02:03" since an ISO start time. */
export function formatElapsed(startedIso: string | null | undefined, nowMs: number): string {
  if (!startedIso) return "0:00";
  const start = new Date(startedIso).getTime();
  if (Number.isNaN(start)) return "0:00";
  const total = Math.max(0, Math.floor((nowMs - start) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** Recording length for people: "45 s", "3 min 05 s", "1 h 02 min", "-" when unknown. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "-";
  const t = Math.round(seconds);
  if (t < 60) return `${t} s`;
  if (t < 3600) return `${Math.floor(t / 60)} min ${String(t % 60).padStart(2, "0")} s`;
  return `${Math.floor(t / 3600)} h ${String(Math.floor((t % 3600) / 60)).padStart(2, "0")} min`;
}

export interface ProgressView {
  /** 0..100, or null when not replaying. */
  pct: number | null;
  text: string | null;
}

/** Replay progress from status.progress and the source's row counts. */
export function replayProgress(status: Status | null): ProgressView {
  if (status?.source !== "replay" || status.progress == null) return { pct: null, text: null };
  const pct = Math.round(status.progress * 100);
  const total = status.source_detail["rows_total"];
  const passes = status.source_detail["passes"];
  const rows = typeof total === "number" ? `${Math.round(status.progress * total)} / ${total} rows` : null;
  const loop = status.loop && typeof passes === "number" && passes > 0 ? `pass ${passes + 1}` : null;
  return { pct, text: [rows, `${pct}%`, loop].filter(Boolean).join(" · ") };
}
