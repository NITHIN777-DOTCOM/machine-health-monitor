import { describe, expect, it } from "vitest";
import type { AnalysisDevice, ForecastEntry, MlBlock } from "../types";
import {
  alertSourceLabel, bannerText, causeText, forecastText, forecastTone, formatValue, healthTone,
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
    expect(stateView("NORMAL")).toEqual({ label: "NORMAL", icon: "ok", tone: "normal" });
    expect(stateView("WARNING")).toEqual({ label: "WARNING", icon: "warning", tone: "warning" });
    expect(stateView("CRITICAL")).toEqual({ label: "CRITICAL", icon: "critical", tone: "critical" });
    expect(stateView(null).label).toBe("NO DATA");
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
    const t = bannerText("recovering, was: Vibration 25 >= warn 20 - WARNING", dev({}), "rules", HOLD);
    expect(t).toEqual({ headline: "Recovering - back to normal in 3 s", detail: "was: Vibration 25 ≥ warn 20", recovering: true });
  });

  it("says 'down to WARNING' from CRITICAL (one level at a time)", () => {
    const t = bannerText("x", dev({ state: "CRITICAL", reported: "CRITICAL", hold_remaining_s: 2 }), "rules", HOLD);
    expect(t.headline).toBe("Recovering - down to WARNING in 2 s");
  });

  it("keeps the active state and reason after a single dip", () => {
    const t = bannerText("recovering, was: Vibration 64 >= crit 60 - CRITICAL",
      dev({ state: "CRITICAL", reported: "CRITICAL", hold_remaining_s: 4 }), "rules", HOLD);
    expect(t).toEqual({ headline: "Vibration 64 ≥ crit 60 - CRITICAL", detail: null, recovering: false });
  });

  it("counts down from CRITICAL even while ML still flags the fault", () => {
    const t = bannerText("h", dev({ state: "CRITICAL", reported: "CRITICAL", hold_remaining_s: 3 }), "both", HOLD);
    expect(t.headline).toBe("Recovering - down to WARNING in 3 s");
  });

  it("does not promise 'back to normal' while an ML anomaly keeps the overall at WARNING", () => {
    const t = bannerText("h", dev({}), "both", HOLD);
    expect(t.headline).toBe("Recovering - rules clear in 3 s; ML anomaly still active");
  });

  it("follows the device's reported state over the mirror", () => {
    const t = bannerText("h", dev({ state: "WARNING", reported: "NORMAL" }), "rules", HOLD);
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
    expect(forecastText("Temperature", f)).toBe("Temperature: WARNING in ~1 min, CRITICAL in ~3 min");
    expect(forecastTone(f)).toBe("critical");
  });

  it("shows a reached warn limit and the critical ETA", () => {
    const f = fc({ status: "reached", trend: "rising", to_warn: "reached", to_critical: "~3 min", seconds_to_warn: 0, seconds_to_critical: 170 });
    expect(forecastText("Temperature", f)).toBe("Temperature: WARNING reached, CRITICAL in ~3 min");
  });

  it("shows only CRITICAL once it is reached", () => {
    const f = fc({ status: "reached", to_warn: "reached", to_critical: "reached", seconds_to_warn: 0, seconds_to_critical: 0 });
    expect(forecastText("Temperature", f)).toBe("Temperature: CRITICAL reached");
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
    expect(mlView(ml({ status: "ANOMALY", health: 30 })).label).toBe("ANOMALY");
    expect(mlView(ml({ status: "ANOMALY", clear_remaining_s: 3 })).detail).toBe("clearing in 3 s");
    expect(mlView(ml({ status: "WARMING_UP", health: null, warmup_remaining_s: 6.2 }))).toMatchObject({ label: "WARMING UP", detail: "7 s left" });
    expect(mlView(ml({ settling_remaining_s: 4, health: null })).label).toBe("SETTLING");
    expect(mlView(ml({ status: "ML_UNAVAILABLE", message: "Temperature: too many missing values" }))).toMatchObject({ label: "ML UNAVAILABLE", detail: "Temperature: too many missing values" });
    expect(mlView(ml({ status: "NO_MODEL" })).label).toBe("NO MODEL");
    expect(mlView(ml({ status: "NEEDS_RETRAIN" })).label).toBe("NEEDS RETRAIN");
    expect(mlView(null).label).toBe("NO DATA");
  });

  it("bands health around the 50 threshold", () => {
    expect(healthTone(null)).toBe("neutral");
    expect(healthTone(20)).toBe("ml");
    expect(healthTone(55)).toBe("warning");
    expect(healthTone(90)).toBe("normal");
  });

  it("formats a cause with its z-score", () => {
    expect(causeText({ sensor: "vib_count", feature: "vib_count__mean", z: 4.13, direction: "high", text: "Vibration high" }))
      .toBe("Vibration high, z=4.1");
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
