// Pure helpers for the Model panel and the model tag (Phase 8.2): what the model was trained
// on, and its held-out test results (GET /api/model/evaluation). Counts are shown as
// "21 of 71" rather than percentages: the test sets are small.

import type {
  EvalChartRow, Evaluation, FalseAlarmGroup, FaultResult, LabelSetResult, ModelDetails, ModelInfo, Registry,
} from "../types";

/** The tag next to the ML card title, from the model's meta. */
export function modelTag(model: ModelInfo | null | undefined): { text: string; title: string } | null {
  if (!model || model.status !== "READY") return null;
  if (model.provisional) {
    return { text: "provisional model", title: "The model was trained on simulated data only; it must be retrained on real recordings" };
  }
  const title = [model.status_line, model.deployment_note].filter(Boolean).join(". ");
  return { text: "bench-trained model", title: title || "Trained on real recordings" };
}

export const countOf = (n: number, of: number) => `${n} of ${of}`;

function pct(n: number, of: number): string {
  return of ? `${((100 * n) / of).toFixed(1)} %` : "n/a";
}

function delayText(delay: number | null | undefined): string {
  if (delay == null) return "missed";
  return delay === 0 ? "at once" : `after ${delay} s`;
}

const FIRST: Record<string, string> = { rules: "Rules", ml: "ML", same: "Same time" };

export interface FaultRowView {
  kind: string;
  name: string;
  /** The name without its explanation: "Subtle vibration". */
  short: string;
  subtle: boolean;
  rules: string;
  rulesDelay: string;
  ml: string;
  mlDelay: string;
  /** Who raised the alarm first. */
  first: string;
}

/** One table row per fault type. */
export function faultRows(set: LabelSetResult | undefined): FaultRowView[] {
  return (set?.faults ?? []).filter((f) => f.rows > 0).map((f: FaultResult) => ({
    kind: f.kind,
    name: f.name,
    short: f.name.replace(/\s*\(.*\)\s*$/, ""),
    subtle: f.subtle,
    rules: f.rules ? countOf(f.rules.rows, f.rows) : "-",
    rulesDelay: delayText(f.rules?.delay_s),
    ml: f.ml_sensor && f.ml ? countOf(f.ml.rows, f.rows) : "not an ML sensor",
    mlDelay: f.ml_sensor && f.ml ? delayText(f.ml.delay_s) : "",
    first: f.first ? FIRST[f.first] ?? f.first : "Neither",
  }));
}

export interface FalseAlarmView {
  name: string;
  rules: string;
  ml: string;
  rows: number;
}

/** False alarms outside the after-fault margin (the main figure). */
export function falseAlarmRows(set: LabelSetResult | undefined): FalseAlarmView[] {
  return Object.values(set?.false_alarms ?? {}).map((g: FalseAlarmGroup) => ({
    name: g.name,
    rows: g.rows_excl_margin,
    rules: `${countOf(g.rules_excl_margin, g.rows_excl_margin)} (${pct(g.rules_excl_margin, g.rows_excl_margin)})`,
    ml: `${countOf(g.ml_excl_margin, g.rows_excl_margin)} (${pct(g.ml_excl_margin, g.rows_excl_margin)})`,
  }));
}

/** "Partly: ML flagged ..." -> { answer: "Partly", text: "ML flagged ..." }. */
export function verdict(ev: Evaluation): { answer: string; text: string } {
  const answer = ev.subtle.answer.charAt(0).toUpperCase() + ev.subtle.answer.slice(1);
  const text = ev.subtle_text.startsWith(`${answer}:`) ? ev.subtle_text.slice(answer.length + 1).trim() : ev.subtle_text;
  return { answer, text };
}

/** The temperature forecast in one sentence, or null. */
export function forecastText(ev: Evaluation): string | null {
  const f = ev.forecast;
  if (!f?.available || f.lead_s == null) return null;
  const when = f.lead_s > 0 ? `${f.lead_s} s before` : f.lead_s < 0 ? `${-f.lead_s} s after` : "at the same time as";
  const extra = f.forecast_warn_rows_elsewhere
    ? ` It also predicted a warning on ${countOf(f.forecast_warn_rows_elsewhere, f.rows_elsewhere ?? 0)} other rows (0.1 °C sensor steps).`
    : "";
  return `Temperature step: the forecast predicted WARNING ${when} the rules reached it.${extra}`;
}

/** "Temperature (changes only), Humidity (changes only), Sound level, Vibration". */
export function featureSummary(featureNames: string[] | null | undefined, registry: Registry | null): string {
  if (!featureNames?.length) return "-";
  const bySensor = new Map<string, string[]>();
  for (const f of featureNames) {
    const i = f.lastIndexOf("__");
    const key = f.slice(0, i);
    bySensor.set(key, [...(bySensor.get(key) ?? []), f.slice(i + 2)]);
  }
  return [...bySensor.entries()].map(([key, stats]) => {
    const name = registry?.sensors.find((s) => s.key === key)?.display_name ?? key;
    const short = name.replace(/\s*\(.*?\)/g, "");
    const changesOnly = stats.every((s) => s === "std" || s === "slope");
    return changesOnly ? `${short} (changes only)` : short;
  }).join(", ");
}

/** "868 real rows, 0 simulated" from GET /api/model. */
export function trainedOnText(m: ModelDetails | null): string {
  if (!m?.trained_on) return "-";
  const { real, synthetic } = m.trained_on;
  return `${real} real normal rows${synthetic ? ` + ${synthetic} simulated` : ", no simulated data"}`;
}

export interface ChartPoint {
  t: number;
  value: number | null;
  health: number | null;
  /** Marker heights on the health axis (null = no marker). */
  mlMark: number | null;
  rulesMark: number | null;
  fault: boolean;
}

export const ML_MARK_Y = 108;
export const RULES_MARK_Y = 116;

export function chartPoints(rows: EvalChartRow[]): ChartPoint[] {
  return rows.map((r) => ({
    t: r.t,
    value: r.value,
    health: r.health,
    mlMark: r.ml ? ML_MARK_Y : null,
    rulesMark: r.rules ? RULES_MARK_Y : null,
    fault: r.label === "fault",
  }));
}

/** [first, last] t of consecutive fault rows, for shading. */
export function faultSpans(points: ChartPoint[]): [number, number][] {
  const spans: [number, number][] = [];
  let start: number | null = null;
  points.forEach((p, i) => {
    if (p.fault && start == null) start = p.t;
    const next = points[i + 1];
    if (start != null && (!next || !next.fault)) {
      spans.push([start, p.t]);
      start = null;
    }
  });
  return spans;
}
