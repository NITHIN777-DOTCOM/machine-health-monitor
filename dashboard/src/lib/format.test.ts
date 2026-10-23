import { describe, expect, it } from "vitest";
import type { AnalysisDevice, ForecastEntry, MlBlock } from "../types";
import {
  alertSourceLabel, bannerText, causeText, causeTooltip, causeWords, confidence, forecastDetail, forecastText,
  forecastTone, formatValue, healthLabel, healthTone, shortName, zBand,
  isRecovering, limitsText, linkView, mlView, modeView, sensorLevel, stateView, stripRecovering,
} from "./format";

const fc = (over: Partial<ForecastEntry>): ForecastEntry => ({
  trend: "stable", status: "stable", seconds_to_warn: null, seconds_to_critical: null,
  to_warn: null, to_critical: null, text: null, r2: 0.1, ...over,
});

const ml = (over: Partial<MlBlock>): MlBlock => ({
  status: "OK", health: 90, causes: [], provisional: true, warmup_remaining_s: null,
  settling_remaining_s: null, clear_remaining_s: null, instant: "OK", message: null, ...over,
});

describe("stateView", () => {
  it("gives every state a label, an icon and a tone (never colour alone)", () => {
    expect(stateView("NORMAL")).toEqual({ label: "Normal", icon: "ok", tone: "normal" });
    expect(stateView("WARNING")).toEqual({ label: "Warning", icon: "warning", tone: "warning" });
    expect(stateView("CRITICAL")).toEqual({ label: "Critical", icon: "critical", tone: "critical" });
    expect(stateView(null).label).toBe("No data");
  });

  it("labels the alert source chip", () => {
    expect(alertSourceLabel("rules")).toBe("Rules");
    expect(alertSourceLabel("ml")).toBe("ML");
    expect(alertSourceLabel("both")).toBe("Both");
    expect(alertSourceLabel("none")).toBeNull();
  });
});

describe("recovering rule", () => {
  const HOLD = 5;
  it("needs the countdown to have progressed by 2 s", () => {
    expect(isRecovering(null, HOLD)).toBe(false);
    expect(isRecovering(5, HOLD)).toBe(false);
    expect(isRecovering(4, HOLD)).toBe(false);    // one row in the clear: could be a dip
    expect(isRecovering(3, HOLD)).toBe(true);
    expect(isRecovering(1, HOLD)).toBe(true);
  });

  const dev = (over: Partial<AnalysisDevice>): AnalysisDevice => ({
    state: "WARNING", reported: "WARNING", reason: "recovering, was: Vibration 25 >= warn 20",
    hold_remaining_s: 3, agrees: true, ...over,
  });

  it("says 'back to normal' from WARNING once the countdown has progressed", () => {
    const t = bannerText("recovering, was: Vibration 25 >= warn 20 - WARNING", null, dev({}), "rules", HOLD);
    expect(t).toEqual({ headline: "Recovering - back to normal in 3 s", detail: "was: Vibration 25 ≥ warn 20", recovering: true });
  });

  it("says 'down to WARNING' from CRITICAL (one level at a time)", () => {
    const t = bannerText("x", null, dev({ state: "CRITICAL", reported: "CRITICAL", hold_remaining_s: 2 }), "rules", HOLD);
    expect(t.headline).toBe("Recovering - down to WARNING in 2 s");
  });

  it("keeps the active state and reason after a single dip", () => {
    const t = bannerText("recovering, was: Vibration 64 >= crit 60 - CRITICAL", null,
      dev({ state: "CRITICAL", reported: "CRITICAL", hold_remaining_s: 4 }), "rules", HOLD);
    expect(t).toEqual({ headline: "Vibration 64 ≥ crit 60 - CRITICAL", detail: null, recovering: false });
  });

  it("counts down from CRITICAL even while ML still flags the fault", () => {
    const t = bannerText("h", null, dev({ state: "CRITICAL", reported: "CRITICAL", hold_remaining_s: 3 }), "both", HOLD);
    expect(t.headline).toBe("Recovering - down to WARNING in 3 s");
  });

  it("does not promise 'back to normal' while an ML anomaly keeps the overall at WARNING", () => {
    const t = bannerText("h", null, dev({}), "both", HOLD);
    expect(t.headline).toBe("Recovering - rules clear in 3 s; ML anomaly still active");
  });

  it("follows the device's reported state over the mirror", () => {
    const t = bannerText("h", null, dev({ state: "WARNING", reported: "NORMAL" }), "rules", HOLD);
    expect(t.recovering).toBe(false);
  });

  it("strips the backend's recovering prefix", () => {
    expect(stripRecovering("recovering, was: Temperature 35.1 >= crit 35")).toBe("Temperature 35.1 ≥ crit 35");
    expect(stripRecovering(null)).toBe("");
    expect(stripRecovering("Distance 4 <= crit 5")).toBe("Distance 4 ≤ crit 5");
  });
});

describe("forecastText", () => {
  it("shows stable and collecting", () => {
    expect(forecastText("Temperature", fc({}))).toBe("Temperature: stable");
    expect(forecastText("Temperature", fc({ status: "insufficient_data", trend: null }))).toBe("Temperature: collecting data");
    expect(forecastText("Temperature", null)).toBe("Temperature: collecting data");
  });

  it("shows the ETAs of an approaching limit", () => {
    const f = fc({ status: "approaching", trend: "rising", to_warn: "~1 min", to_critical: "~3 min", seconds_to_warn: 70, seconds_to_critical: 190 });
    expect(forecastText("Temperature", f)).toBe("Temperature: warning in ~1 min, critical in ~3 min");
    expect(forecastTone(f)).toBe("critical");
  });

  it("shows a reached warn limit and the critical ETA", () => {
    const f = fc({ status: "reached", trend: "rising", to_warn: "reached", to_critical: "~3 min", seconds_to_warn: 0, seconds_to_critical: 170 });
    expect(forecastText("Temperature", f)).toBe("Temperature: warning reached, critical in ~3 min");
  });

  it("shows only CRITICAL once it is reached", () => {
    const f = fc({ status: "reached", to_warn: "reached", to_critical: "reached", seconds_to_warn: 0, seconds_to_critical: 0 });
    expect(forecastText("Temperature", f)).toBe("Temperature: critical reached");
  });

  it("tones warn-only and beyond-the-cap forecasts", () => {
    expect(forecastTone(fc({ status: "approaching", to_warn: "~2 min", seconds_to_warn: 120, to_critical: "> 30 min" }))).toBe("warning");
    expect(forecastTone(fc({ to_warn: "> 30 min" }))).toBe("normal");
    expect(forecastTone(fc({ status: "insufficient_data" }))).toBe("neutral");
  });
});

describe("mlView", () => {
  it("maps every ML status to a label", () => {
    expect(mlView(ml({})).label).toBe("OK");
    expect(mlView(ml({ status: "ANOMALY", health: 30 })).label).toBe("Anomaly");
    expect(mlView(ml({ status: "ANOMALY", clear_remaining_s: 3 })).detail).toBe("clearing in 3 s");
    expect(mlView(ml({ status: "WARMING_UP", health: null, warmup_remaining_s: 6.2 }))).toMatchObject({ label: "Warming up", detail: "7 s left" });
    expect(mlView(ml({ settling_remaining_s: 4, health: null })).label).toBe("Settling");
    expect(mlView(ml({ status: "ML_UNAVAILABLE", message: "Temperature: too many missing values" }))).toMatchObject({ label: "ML unavailable", detail: "Temperature: too many missing values" });
    expect(mlView(ml({ status: "NO_MODEL" })).label).toBe("No model");
    expect(mlView(ml({ status: "NEEDS_RETRAIN" })).label).toBe("Needs retrain");
    expect(mlView(null).label).toBe("No data");
  });

  it("bands health around the 50 threshold", () => {
    expect(healthTone(null)).toBe("neutral");
    expect(healthTone(20)).toBe("ml");
    expect(healthTone(55)).toBe("warning");
    expect(healthTone(90)).toBe("normal");
  });

  it("bands health around the backend's anomaly and clear levels", () => {
    const levels = { anomaly_health: 40, clear_health: 70 };
    expect(healthTone(45, levels)).toBe("warning");
    expect(healthTone(39, levels)).toBe("ml");
    expect(healthLabel(65, levels)).toBe("borderline");
    expect(healthLabel(75, levels)).toBe("healthy");
  });
});

describe("sensor levels and limits", () => {
  const above = { warn: 32, critical: 35, direction: "above" as const, unit: "°C" };
  const below = { warn: 10, critical: 5, direction: "below" as const, unit: "cm" };

  it("compares at-or-past the limit in the sensor's direction", () => {
    expect(sensorLevel(above, 31.9)).toBe("NORMAL");
    expect(sensorLevel(above, 32)).toBe("WARNING");
    expect(sensorLevel(above, 35)).toBe("CRITICAL");
    expect(sensorLevel(below, 12)).toBe("NORMAL");
    expect(sensorLevel(below, 10)).toBe("WARNING");
    expect(sensorLevel(below, 4)).toBe("CRITICAL");
    expect(sensorLevel({ warn: null, critical: null, direction: "above" }, 999)).toBe("NORMAL");
  });

  it("writes limits for people", () => {
    expect(limitsText(above)).toBe("warn ≥ 32 · crit ≥ 35 °C");
    expect(limitsText(below)).toBe("warn ≤ 10 · crit ≤ 5 cm");
    expect(limitsText({ warn: null, critical: null, direction: "above", unit: "mA" })).toBe("no limits set");
  });

  it("formats values without hiding real zeros", () => {
    expect(formatValue(0)).toBe("0");
    expect(formatValue(29.5)).toBe("29.5");
    expect(formatValue(4.98)).toBe("4.98");
    expect(formatValue(null)).toBe("-");
  });
});

describe("top bar", () => {
  it("shows the row's mode, or the source's before any row", () => {
    expect(modeView("live", "serial")?.label).toBe("LIVE");
    expect(modeView(null, "replay")?.label).toBe("RECORDED");
    expect(modeView(undefined, "simulator")?.label).toBe("SIMULATED");
    expect(modeView(null, null)).toBeNull();
  });

  it("maps the link field and lets a closed socket win", () => {
    expect(linkView("open", "ok")).toMatchObject({ label: "Receiving data", stale: false });
    expect(linkView("open", "starting").stale).toBe(false);
    expect(linkView("open", "no_data").stale).toBe(true);
    expect(linkView("open", "down").label).toBe("Source down");
    expect(linkView("open", "finished").label).toBe("Replay finished");
    expect(linkView("closed", "ok")).toMatchObject({ label: "Backend offline", stale: true });
  });
});

describe("headline detail line", () => {
  it("passes the backend's detail line through, with readable operators", () => {
    const d = { state: "CRITICAL" as const, reported: "CRITICAL" as const, reason: "x", hold_remaining_s: null };
    const t = bannerText("Sound level and vibration above critical limits",
      "Sound level 143, crit limit 120 · Vibration 64, crit limit 60", d, "rules", 5);
    expect(t).toEqual({
      headline: "Sound level and vibration above critical limits",
      detail: "Sound level 143, crit limit 120 · Vibration 64, crit limit 60",
      recovering: false,
    });
    expect(bannerText("All systems normal", null, { ...d, state: "NORMAL", reported: "NORMAL" }, "none", 5).detail).toBeNull();
  });
});

describe("causes in plain words", () => {
  const cause = (feature: string, z: number) => ({
    sensor: feature.split("__")[0] ?? feature, feature, z, direction: "high", band: zBand(z), text: "x",
  });

  it("bands |z|: < 2 normal, 2-3 slight, 3-6 clear, >= 6 far", () => {
    expect([0, 1.99, 2, -2.9, 3, 5.99, 6, -99].map(zBand))
      .toEqual(["normal", "normal", "slight", "slight", "clear", "clear", "far", "far"]);
  });

  it("words depend on the statistic and the sign", () => {
    expect(causeWords("vib_count__mean", 64.5)).toBe("far above normal");
    expect(causeWords("sound_peak__max", 4)).toBe("above normal");
    expect(causeWords("temp_c__last", 2.3)).toBe("slightly high");
    expect(causeWords("temp_c__min", -3.2)).toBe("below normal");
    expect(causeWords("vib_count__std", 3.1)).toBe("unstable");
    expect(causeWords("humidity__std", -2.5)).toBe("slightly steady");
    expect(causeWords("temp_c__slope", 7)).toBe("rising fast");
    expect(causeWords("temp_c__slope", -2.2)).toBe("falling slightly");
    expect(causeWords("temp_c__mean", 1.2)).toBe("normal");
  });

  it("uses the short sensor name and never shows z in the text", () => {
    expect(causeText(cause("sound_peak__max", 99), "Sound level (peak deviation)")).toBe("Sound level: far above normal");
    expect(causeText(cause("vib_count__mean", 4.1), "Vibration")).toBe("Vibration: above normal");
    expect(shortName("Sound level (peak deviation)")).toBe("Sound level");
  });

  it("puts z in the tooltip, but never a capped value like 99", () => {
    expect(causeTooltip(cause("vib_count__mean", 4.13))).toBe(
      "z = 4.1: 4.1 standard deviations above the normal mean (window feature vib_count__mean)");
    const capped = causeTooltip(cause("sound_peak__max", 99));
    expect(capped).toContain("more than 10 standard deviations above");
    expect(capped).not.toContain("99");
    expect(causeTooltip(cause("temp_c__min", -12))).toContain("below the normal mean");
  });
});

describe("forecast confidence", () => {
  it("bands R²: < 0.6 low, 0.6-0.85 medium, >= 0.85 high", () => {
    expect(confidence(0.3)).toBe("low");
    expect(confidence(0.6)).toBe("medium");
    expect(confidence(0.849)).toBe("medium");
    expect(confidence(0.85)).toBe("high");
    expect(confidence(null)).toBeNull();
  });

  it("describes the trend without showing R²", () => {
    expect(forecastDetail(fc({ status: "approaching", trend: "rising", r2: 0.91 }))).toBe("rising · confidence: high");
    expect(forecastDetail(fc({ status: "approaching", trend: "falling", r2: 0.7 }))).toBe("falling · confidence: medium");
    expect(forecastDetail(fc({ r2: 0.08 }))).toBe("no clear trend");
    expect(forecastDetail(fc({ status: "no_data", trend: null, r2: null }))).toBe("sensor has no current reading");
  });

  it("says no data as soon as the sensor's newest value is missing", () => {
    const f = fc({ status: "no_data", trend: null, r2: null });
    expect(forecastText("Temperature", f)).toBe("Temperature: no data");
    expect(forecastTone(f)).toBe("neutral");
  });
});
