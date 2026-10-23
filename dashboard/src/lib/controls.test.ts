import { describe, expect, it } from "vitest";
import type { Status } from "../types";
import {
  actionReducer, activeKind, apiErrorText, availableScenarios, formatDuration, formatElapsed, IDLE,
  isActiveScenario, liveOption, replayBody, replayProgress, scenarioBody,
} from "./controls";

const status = (over: Partial<Status>): Status => ({
  source: "simulator", scenario: "normal", speed: 1, file: null, loop: null, progress: null,
  scenarios: ["drift_and_recover", "normal", "recovery", "sensor_fault", "slow_drift", "sudden_fault"],
  serial: { available: false, port: null, note: "Serial disabled (MHM_SOURCE=simulator)." },
  source_detail: {},
  ...over,
} as Status);

describe("source switcher", () => {
  it("maps the backend source to Live / Simulated / Recorded", () => {
    expect(activeKind(status({ source: "serial" }))).toBe("live");
    expect(activeKind(status({ source: "simulator" }))).toBe("simulated");
    expect(activeKind(status({ source: "replay" }))).toBe("recorded");
    expect(activeKind(null)).toBeNull();
  });

  it("disables Live with the backend's note when serial is unavailable", () => {
    expect(liveOption(status({}))).toEqual({ enabled: false, note: "Serial disabled (MHM_SOURCE=simulator)." });
    expect(liveOption(status({ serial: { available: true, port: "COM5", note: null } })))
      .toEqual({ enabled: true, note: "Arduino on COM5" });
    expect(liveOption(null).enabled).toBe(false);
  });

  it("builds the request bodies", () => {
    expect(scenarioBody("slow_drift", 10)).toEqual({ type: "simulator", scenario: "slow_drift", speed: 10 });
    expect(replayBody("a.csv", 5, true)).toEqual({ type: "replay", file: "a.csv", speed: 5, loop: true });
  });

  it("shows the demo scenarios the backend offers, in demo order", () => {
    expect(availableScenarios(status({})).map((s) => s.key))
      .toEqual(["normal", "sudden_fault", "slow_drift", "recovery", "sensor_fault"]);
    expect(availableScenarios(status({ scenarios: ["normal"] })).map((s) => s.label)).toEqual(["Normal"]);
    expect(isActiveScenario(status({ scenario: "recovery" }), "recovery")).toBe(true);
    expect(isActiveScenario(status({ source: "replay", scenario: null }), "recovery")).toBe(false);
  });
});

describe("request state", () => {
  it("disables everything while a request runs and keeps the error until the next one", () => {
    let s = actionReducer(IDLE, { type: "start", key: "source" });
    expect(s).toEqual({ busy: "source", error: null });
    s = actionReducer(s, { type: "fail", error: "Port busy" });
    expect(s).toEqual({ busy: null, error: "Port busy" });
    expect(actionReducer(s, { type: "start", key: "record" })).toEqual({ busy: "record", error: null });
    expect(actionReducer(s, { type: "dismiss" }).error).toBeNull();
    expect(actionReducer({ busy: "x", error: null }, { type: "ok" })).toEqual(IDLE);
  });

  it("turns API errors into something to act on", () => {
    expect(apiErrorText(500, "COM5 busy, close Serial Monitor")).toMatch(/^Port busy: close the Arduino IDE Serial Monitor/);
    expect(apiErrorText(500, "could not open port 'COM5': PermissionError(13, 'Access is denied.')")).toMatch(/^Port busy/);
    expect(apiErrorText(400, "serial is disabled by MHM_SOURCE=simulator (unset it and restart to use the Arduino)"))
      .toMatch(/^Serial is disabled/);
    expect(apiErrorText(404, "No recording named 'x.csv'")).toBe("No recording named 'x.csv'");
    expect(apiErrorText(422, [{ msg: "Input should be 'normal'" }])).toBe("Input should be 'normal'");
    expect(apiErrorText(500, null)).toBe("HTTP 500");
    expect(apiErrorText(null, null)).toMatch(/Backend not reachable/);
  });
});

describe("recording and replay", () => {
  const start = "2026-10-24T00:10:00+05:30";
  const t0 = new Date(start).getTime();

  it("shows elapsed recording time", () => {
    expect(formatElapsed(start, t0 + 7_000)).toBe("0:07");
    expect(formatElapsed(start, t0 + 754_000)).toBe("12:34");
    expect(formatElapsed(start, t0 + 3_723_000)).toBe("1:02:03");
    expect(formatElapsed(null, t0)).toBe("0:00");
  });

  it("formats recording durations", () => {
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(185)).toBe("3 min 05 s");
    expect(formatDuration(3720)).toBe("1 h 02 min");
    expect(formatDuration(null)).toBe("-");
  });

  it("shows replay progress only while replaying", () => {
    const r = status({ source: "replay", progress: 0.4, loop: false, source_detail: { rows_total: 300, passes: 0 } });
    expect(replayProgress(r)).toEqual({ pct: 40, text: "120 / 300 rows · 40%" });
    const looping = status({ source: "replay", progress: 0.1, loop: true, source_detail: { rows_total: 100, passes: 2 } });
    expect(replayProgress(looping).text).toBe("10 / 100 rows · 10% · pass 3");
    expect(replayProgress(status({}))).toEqual({ pct: null, text: null });
  });
});
