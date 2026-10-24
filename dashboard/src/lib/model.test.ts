import { describe, expect, it } from "vitest";
import type { Evaluation, LabelSetResult, ModelInfo, Registry } from "../types";
import {
  chartPoints, faultRows, faultSpans, falseAlarmRows, featureSummary, forecastText, ML_MARK_Y, modelTag,
  trainedOnText, verdict,
} from "./model";

const model = (over: Partial<ModelInfo> = {}): ModelInfo => ({
  status: "READY", message: null, provisional: false, sensors: [], window_s: 10, created: null,
  status_line: "bench-trained on real data (session 01)",
  deployment_note: "trained on a bench setup; a real machine needs its own normal data and a retrain", ...over,
});

const set: LabelSetResult = {
  faults: [
    { kind: "subtle_vibration", name: "Subtle vibration (light taps, below the limit)", subtle: true, sensors: ["vib_count"], ml_sensor: true, rows: 71,
      episodes: 1, rules: { rows: 21, episodes: 1, delay_s: 17 }, ml: { rows: 39, episodes: 1, delay_s: 19 }, first: "rules" },
    { kind: "leak", name: "Water leak", subtle: false, sensors: ["leak_raw"], ml_sensor: false, rows: 40,
      episodes: 1, rules: { rows: 37, episodes: 1, delay_s: 0 }, ml: null, first: "rules" },
    { kind: "claps", name: "Claps", subtle: false, sensors: ["sound_peak"], ml_sensor: true, rows: 0 },
    { kind: "temperature", name: "Temperature", subtle: false, sensors: ["temp_c"], ml_sensor: true, rows: 100,
      episodes: 1, rules: { rows: 59, episodes: 1, delay_s: 41 }, ml: { rows: 0, episodes: 0, delay_s: null }, first: null },
  ],
  false_alarms: {
    hands_off: { name: "Hands-off", rows: 874, rows_excl_margin: 799, rules: 29, rules_excl_margin: 24, ml: 104, ml_excl_margin: 71 },
  },
  totals: {},
};

const ev = (over: Partial<Evaluation> = {}): Evaluation => ({
  available: true, matches_model: true, message: null, stamp: "REAL DATA - held-out test session", created: "", session: "s",
  rows: 10, margin_s: 15,
  model: { status: null, created: null, trained_on: { real_rows: 868, synthetic_rows: 0, sessions: [] }, sensors: [], feature_count: 16 },
  label_sets: { live: set }, subtle: { answer: "partly" }, subtle_text: "Partly: ML flagged 24 of the 50 rows.",
  forecast: { available: true, lead_s: 34, forecast_warn_rows_elsewhere: 114, rows_elsewhere: 1736 },
  chart: { kind: "subtle_vibration", name: "", sensor: "vib_count", rows: [] }, ...over,
});

describe("modelTag", () => {
  it("names a bench-trained model and keeps the deployment note in the tooltip", () => {
    const tag = modelTag(model());
    expect(tag?.text).toBe("bench-trained model");
    expect(tag?.title).toContain("bench-trained on real data (session 01)");
    expect(tag?.title).toContain("needs its own normal data");
  });
  it("still flags a provisional model and hides the tag without a model", () => {
    expect(modelTag(model({ provisional: true }))?.text).toBe("provisional model");
    expect(modelTag(model({ status: "NO_MODEL" }))).toBeNull();
    expect(modelTag(null)).toBeNull();
  });
});

describe("result tables", () => {
  it("shows counts, delays, rule-only sensors and who was first", () => {
    const rows = faultRows(set);
    expect(rows.map((r) => r.kind)).toEqual(["subtle_vibration", "leak", "temperature"]);   // no rows -> hidden
    expect(rows[0]).toMatchObject({ short: "Subtle vibration", rules: "21 of 71", ml: "39 of 71", rulesDelay: "after 17 s", first: "Rules" });
    expect(rows[1]).toMatchObject({ ml: "not an ML sensor", mlDelay: "", rulesDelay: "at once" });
    expect(rows[2]).toMatchObject({ ml: "0 of 100", mlDelay: "missed", first: "Neither" });
  });
  it("false alarms use the rows outside the after-fault margin", () => {
    expect(falseAlarmRows(set)).toEqual([{ name: "Hands-off", rows: 799, rules: "24 of 799 (3.0 %)", ml: "71 of 799 (8.9 %)" }]);
    expect(faultRows(undefined)).toEqual([]);
  });
});

describe("verdict and forecast", () => {
  it("splits the answer from the sentence", () => {
    expect(verdict(ev())).toEqual({ answer: "Partly", text: "ML flagged 24 of the 50 rows." });
  });
  it("describes the forecast lead and its false warnings", () => {
    expect(forecastText(ev())).toBe("Temperature step: the forecast predicted WARNING 34 s before the rules reached it. "
      + "It also predicted a warning on 114 of 1736 other rows (0.1 °C sensor steps).");
    expect(forecastText(ev({ forecast: { available: true, lead_s: -5 } }))).toContain("5 s after");
    expect(forecastText(ev({ forecast: { available: false } }))).toBeNull();
  });
});

describe("training summary", () => {
  const registry = { sensors: [{ key: "temp_c", display_name: "Temperature" }, { key: "sound_peak", display_name: "Sound level (peak deviation)" }] } as unknown as Registry;
  it("marks sensors used by their changes only", () => {
    expect(featureSummary(["temp_c__std", "temp_c__slope", "sound_peak__mean", "sound_peak__std"], registry))
      .toBe("Temperature (changes only), Sound level");
    expect(featureSummary(null, registry)).toBe("-");
  });
  it("says how many real and simulated rows", () => {
    const m = { trained_on: { real: 868, synthetic: 0 } } as Parameters<typeof trainedOnText>[0];
    expect(trainedOnText(m)).toBe("868 real normal rows, no simulated data");
    expect(trainedOnText({ trained_on: { real: 5, synthetic: 9 } } as Parameters<typeof trainedOnText>[0])).toBe("5 real normal rows + 9 simulated");
  });
});

describe("chart", () => {
  it("places markers and finds fault spans", () => {
    const pts = chartPoints([
      { t: -1, ts: "", value: 0, health: 100, rules: false, ml: false, label: "normal" },
      { t: 0, ts: "", value: 5, health: 40, rules: false, ml: true, label: "fault" },
      { t: 1, ts: "", value: 9, health: 30, rules: true, ml: true, label: "fault" },
      { t: 2, ts: "", value: 0, health: 90, rules: false, ml: false, label: "unknown" },
      { t: 3, ts: "", value: 3, health: 80, rules: false, ml: false, label: "fault" },
    ]);
    expect(pts[1]?.mlMark).toBe(ML_MARK_Y);
    expect(pts[1]?.rulesMark).toBeNull();
    expect(faultSpans(pts)).toEqual([[0, 1], [3, 3]]);
  });
});
