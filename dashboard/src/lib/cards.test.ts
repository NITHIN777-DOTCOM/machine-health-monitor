import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Registry, RowDict, Sensor } from "../types";
import { appendPoints, historyToPoints, type Point } from "./buffer";
import { buildSensorCards, enabledSensors } from "./cards";

// The real registry file, shaped like GET /api/sensors (the API adds derived fields).
function loadRegistry(): Registry {
  const raw = JSON.parse(readFileSync(new URL("../../../backend/config/sensors.json", import.meta.url), "utf-8")) as {
    schema_version: number; csv_columns: string[]; sensors: Partial<Sensor>[];
  };
  return {
    schema_version: raw.schema_version,
    csv_columns: raw.csv_columns,
    warnings: [],
    sensors: raw.sensors.map((s) => ({
      group: null, comment: null, limits_note: null, out_of_range_value: null, ...s,
      enabled_in_config: s.enabled!, in_ml: !!(s.enabled && s.include_in_ml),
    }) as Sensor),
  };
}

const row = (values: Record<string, number | null>, dev_state: RowDict["dev_state"] = "NORMAL"): RowDict => ({
  ts_iso: "2026-10-23T18:40:05+05:30", ms: 12000, dev_state, mode: "simulated", source: "synthetic", label: "unknown", ...values,
});

describe("buildSensorCards", () => {
  const registry = loadRegistry();

  it("makes one card per enabled sensor and lists the disabled ones as not connected", () => {
    const { cards, notConnected } = buildSensorCards(registry, row({ temp_c: 29.5, humidity: 60, sound_peak: 4, vib_count: 0, leak_raw: 6, distance_cm: 158 }));
    expect(cards.map((c) => c.key)).toEqual(enabledSensors(registry).map((s) => s.key));
    expect(notConnected.map((s) => s.key)).toEqual(registry.sensors.filter((s) => !s.enabled).map((s) => s.key));
    expect(cards.every((c) => c.status === "ok")).toBe(true);
  });

  it("treats 0 as a real reading", () => {
    const { cards } = buildSensorCards(registry, row({ temp_c: 29.5, humidity: 60, sound_peak: 4, vib_count: 0 }));
    const vib = cards.find((c) => c.key === "vib_count")!;
    expect(vib).toMatchObject({ value: "0", status: "ok", level: "NORMAL" });
  });

  it("flags an enabled sensor with an empty field as a sensor fault", () => {
    const { cards } = buildSensorCards(registry, row({ temp_c: null, humidity: null, sound_peak: 5, vib_count: 0 }, "WARNING"));
    const temp = cards.find((c) => c.key === "temp_c")!;
    expect(temp).toMatchObject({ status: "fault", value: null, level: null });
    expect(cards.find((c) => c.key === "sound_peak")!.status).toBe("ok");
  });

  it("gives each card its own level and limits text", () => {
    const { cards } = buildSensorCards(registry, row({ temp_c: 33, humidity: 91, sound_peak: 4, vib_count: 64 }));
    const by = Object.fromEntries(cards.map((c) => [c.key, c]));
    expect(by.temp_c!.level).toBe("WARNING");
    expect(by.humidity!.level).toBe("CRITICAL");
    expect(by.vib_count!.level).toBe("CRITICAL");
    expect(by.temp_c!.limits).toBe("warn ≥ 32 · crit ≥ 35 °C");
  });

  it("shows the safety zone's no-echo reading as '> 400 cm (clear)', a level as below", () => {
    const base = { temp_c: 29.5, humidity: 60, sound_peak: 4, vib_count: 0, leak_raw: 6 };
    const clear = buildSensorCards(registry, row({ ...base, distance_cm: 400 })).cards.find((c) => c.key === "distance_cm")!;
    expect(clear).toMatchObject({ value: "> 400", unit: "cm (clear)", level: "NORMAL", status: "ok" });
    expect(clear.name).toBe("Safety zone (distance)");
    const near = buildSensorCards(registry, row({ ...base, distance_cm: 8.5 })).cards.find((c) => c.key === "distance_cm")!;
    expect(near).toMatchObject({ value: "8.5", unit: "cm", level: "CRITICAL", limits: "warn ≤ 20 · crit ≤ 10 cm" });
    const gone = buildSensorCards(registry, row({ ...base, distance_cm: null })).cards.find((c) => c.key === "distance_cm")!;
    expect(gone.status).toBe("fault");                 // empty = a genuine sensor fault
  });

  it("shows 'waiting' before the first row", () => {
    const { cards } = buildSensorCards(registry, null);
    expect(cards.every((c) => c.status === "waiting")).toBe(true);
  });

  it("picks up a newly enabled optional sensor with no code change", () => {
    const enabled: Registry = {
      ...registry,
      sensors: registry.sensors.map((s) => (s.group === "ina219" ? { ...s, enabled: true } : s)),
    };
    const { cards, notConnected } = buildSensorCards(enabled, row({ temp_c: 29, humidity: 60, sound_peak: 4, vib_count: 0, current_ma: 182.4, bus_v: 4.98 }));
    expect(cards.find((c) => c.key === "current_ma")).toMatchObject({ value: "182.4", status: "ok", limits: "no limits set" });
    expect(cards.find((c) => c.key === "bus_v")!.value).toBe("4.98");
    expect(notConnected.map((s) => s.key)).not.toContain("current_ma");
  });

  it("handles a missing registry", () => {
    expect(buildSensorCards(null, null)).toEqual({ cards: [], notConnected: [] });
  });
});

describe("trend buffer", () => {
  const pt = (ms: number): Point => ({ ms, row: row({}), health: null });

  it("keeps only the last 5 minutes of device time", () => {
    const pts = Array.from({ length: 400 }, (_, i) => pt(i * 1000));
    const buf = appendPoints([], pts);
    expect(buf[0]!.ms).toBe(100_000);
    expect(buf[buf.length - 1]!.ms).toBe(399_000);
  });

  it("starts over when the device clock goes backwards", () => {
    const buf = appendPoints([pt(5000), pt(6000)], [pt(1000), pt(2000)]);
    expect(buf.map((p) => p.ms)).toEqual([1000, 2000]);
  });

  it("does not modify the buffer it was given", () => {
    const old = [pt(1000)];
    appendPoints(old, [pt(2000)]);
    expect(old).toHaveLength(1);
  });

  it("reads history rows with their compact analysis", () => {
    const pts = historyToPoints([
      { ...row({ temp_c: 29 }), analysis: { overall: "NORMAL", alert_source: "none", ml_status: "OK", health: 88, forecast: {} } },
      { ...row({ temp_c: 29 }), ms: null },
    ]);
    expect(pts).toHaveLength(1);
    expect(pts[0]).toMatchObject({ ms: 12000, health: 88 });
    expect(pts[0]!.row).not.toHaveProperty("analysis");
  });
});
