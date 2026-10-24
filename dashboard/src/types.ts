// Shapes of the backend's REST and WebSocket messages. They mirror backend/app exactly:
//   Sensor / Registry ........ registry.py  Sensor.to_dict() / Registry.to_dict()
//   RowDict .................. models.py    SensorRow.to_dict()
//   Analysis ................. analysis.py  Analyzer._combine()  (DATA_CONTRACT.md section 9)
//   CompactAnalysis .......... analysis.py  compact()  (/api/history, detail=compact)
//   Status ................... pipeline.py  Pipeline.status()
// If the backend changes one of these, change it here too.

export type DevState = "NORMAL" | "WARNING" | "CRITICAL";
export type Mode = "live" | "recorded" | "simulated";
export type DataSource = "real" | "synthetic";
export type Label = "normal" | "fault" | "unknown";
export type Direction = "above" | "below";
export type AlertSource = "rules" | "ml" | "both" | "none";
export type Link = "starting" | "ok" | "no_data" | "down" | "finished";
export type SourceType = "simulator" | "serial" | "replay";

/** ML status in the analysis block (ml.status). */
export type MlStatus = "OK" | "ANOMALY" | "WARMING_UP" | "ML_UNAVAILABLE" | "NO_MODEL" | "NEEDS_RETRAIN";
/** Model status (status.model.status): READY, or why ML is off. */
export type ModelStatus = "READY" | "NO_MODEL" | "NEEDS_RETRAIN";

// ---- registry (GET /api/sensors) -------------------------------------------------------

export interface Sensor {
  key: string;
  display_name: string;
  unit: string;
  hardware: string;
  pin: string;
  warn: number | null;
  critical: number | null;
  direction: Direction;
  hysteresis: number | null;
  tier: "core" | "optional";
  /** Effective flag (false if its group was disabled for a mismatch). */
  enabled: boolean;
  enabled_in_config: boolean;
  include_in_ml: boolean;
  in_ml: boolean;
  forecast: boolean;
  group: string | null;
  comment: string | null;
  limits_note: string | null;
}

export interface Registry {
  schema_version: number | null;
  csv_columns: string[];
  sensors: Sensor[];
  warnings: string[];
}

// ---- one row (contract section 5) ----------------------------------------------------------

/** A stored row: ts_iso, the device columns, then mode/source/label. Sensor values are
 *  keyed by registry key; an empty field is null, never 0. */
export interface RowDict {
  ts_iso: string;
  ms: number | null;
  dev_state: DevState | null;
  mode: Mode;
  source: DataSource;
  label: Label;
  [sensorKey: string]: number | string | null;
}

// ---- analysis block (contract section 9) ------------------------------------------------

export interface MlCause {
  sensor: string;
  feature: string;
  z: number;
  /** "high", "low", "unstable", "rising", ... */
  direction: string;
  /** |z| band: normal (< 2), slight (2-3), clear (3-6), far (>= 6). */
  band: "normal" | "slight" | "clear" | "far";
  /** Plain words, e.g. "Vibration: far above normal". */
  text: string;
}

export interface MlBlock {
  status: MlStatus;
  health: number | null;
  causes: MlCause[];
  provisional: boolean;
  warmup_remaining_s: number | null;
  settling_remaining_s: number | null;
  clear_remaining_s: number | null;
  instant: "OK" | "ANOMALY" | null;
  message: string | null;
  /** Only present when the window was scored. */
  range_excess?: number | null;
}

/** no_data: the newest row has no value for the sensor (e.g. the DHT11 failed). */
export type ForecastStatus = "insufficient_data" | "no_data" | "stable" | "approaching" | "reached";

export interface ForecastEntry {
  trend: "rising" | "falling" | "stable" | null;
  status: ForecastStatus;
  seconds_to_warn: number | null;
  seconds_to_critical: number | null;
  /** Human ETA: "reached", "< 1 min", "~3 min", "> 30 min", or null. */
  to_warn: string | null;
  to_critical: string | null;
  text: string | null;
  r2: number | null;
}

export interface AnalysisDevice {
  /** Backend mirror state. */
  state: DevState;
  /** dev_state the device itself sent. */
  reported: DevState | null;
  /** e.g. "Vibration 64 >= crit 60", or "recovering, was: ..." while counting down. */
  reason: string | null;
  /** Seconds until the state can step down one level; null when not clearing. */
  hold_remaining_s: number | null;
  agrees: boolean | null;
}

export interface Analysis {
  overall: DevState;
  alert_source: AlertSource;
  /** Short human sentence, e.g. "Sound level and vibration above critical limits". */
  headline: string;
  /** Smaller second line with the exact values, or null. */
  headline_detail: string | null;
  device: AnalysisDevice;
  ml: MlBlock;
  forecast: Record<string, ForecastEntry>;
  warm_start: string | null;
}

/** Per-row summary in /api/history (detail=compact). */
export interface CompactAnalysis {
  overall: DevState;
  alert_source: AlertSource;
  ml_status: MlStatus;
  health: number | null;
  forecast: Record<string, { seconds_to_warn: number | null; seconds_to_critical: number | null }>;
}

// ---- status (GET /api/status, WebSocket "status" messages) -------------------------------

export interface Trigger {
  sensor: string;
  kind: "limit" | "fault";
  level: DevState;
  value: number | null;
  limit: number | null;
  direction: Direction;
  in_band: boolean;
  text: string;
}

export interface DeviceStatus {
  state: DevState;
  reason: string | null;
  reasons: Trigger[];
  clearing: boolean;
  hold_remaining_s: number | null;
  hold_seconds: number;
  last_change: string | null;
  device_reported: DevState | null;
  agrees: boolean | null;
}

export interface ModelInfo {
  status: ModelStatus;
  message: string | null;
  provisional: boolean;
  sensors: string[] | null;
  window_s: number | null;
  created: string | null;
}

export interface RecordingStatus {
  on: boolean;
  file: string | null;
  rows: number;
  started_at: string | null;
  label: Label | null;
}

export interface Status {
  source: SourceType | null;
  scenario: string | null;
  speed: number | null;
  file: string | null;
  loop: boolean | null;
  /** Replay only: share of the file played in the current pass, 0..1. */
  progress: number | null;
  serial_port: string | null;
  connected: boolean;
  link: Link;
  data_age_s: number | null;
  last_error: string | null;
  source_detail: Record<string, unknown>;
  device: DeviceStatus;
  analysis: Analysis | null;
  model: ModelInfo;
  warm_start: Record<string, unknown> | null;
  analysis_timing_ms: { rows: number; avg_ms: number | null; p95_ms: number | null; max_ms: number | null };
  recording: RecordingStatus;
  rows_received: number;
  rows_rejected: number;
  history_rows: number;
  startup_reason: string;
  registry_warnings: string[];
  scenarios: string[];
  ml_thresholds: MlThresholds;
  serial: SerialInfo;
  version: VersionInfo;
}

/** App version: git describe + build date of the portable build (null in development). */
export interface VersionInfo {
  app: string;
  name: string;
  version: string;
  git: string | null;
  build_date: string | null;
  frozen: boolean;
}

/** ML smoothing levels (settings.json): ANOMALY after health < anomaly_health for
 *  anomaly_rows rows; clears after health > clear_health for clear_rows rows. */
export interface MlThresholds {
  anomaly_health: number;
  anomaly_rows: number;
  clear_health: number;
  clear_rows: number;
}

/** Whether switching to the Arduino can work (false with MHM_SOURCE=simulator or no Uno). */
export interface SerialInfo {
  available: boolean;
  port: string | null;
  note: string | null;
}

// ---- endpoints ---------------------------------------------------------------------------

/** A history row: the RowDict fields plus its compact analysis. */
export interface HistoryRow {
  analysis?: CompactAnalysis | null;
  [column: string]: unknown;
}

/** One entry of GET /api/recordings. */
export interface Recording {
  file: string;
  /** "recordings" (data/recordings) or "demo" (data/demo, the simulated demo recording). */
  folder: string;
  size_bytes: number;
  rows: number;
  duration_s: number | null;
  /** File's last-modified time, ISO 8601. */
  modified: string;
  error: string | null;
}

export interface HistoryResponse {
  seconds: number;
  count: number;
  rows: HistoryRow[];
}

export type WsMessage =
  | { type: "row"; mode: Mode; row: RowDict; analysis: Analysis }
  | { type: "status"; status: Status };
