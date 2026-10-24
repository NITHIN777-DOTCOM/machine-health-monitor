// Sensor cards built from the registry (GET /api/sensors) and the newest row. The registry
// is the only sensor list: enable an optional sensor in sensors.json and its card appears.
//
// Contract empty-field rule (DATA_CONTRACT.md section 3):
//   enabled: false + empty -> "Not connected" (compact row, no card)
//   enabled: true  + empty -> "No reading - sensor fault"

import type { DevState, Registry, RowDict, Sensor } from "../types";
import { limitsText, sensorLevel, sensorValueText } from "./format";

export type CardStatus = "ok" | "fault" | "waiting";

export interface SensorCard {
  key: string;
  name: string;
  unit: string;
  hardware: string;
  /** Formatted value, or null when there is none. */
  value: string | null;
  /** The sensor's own level vs. its limits; null without a value. */
  level: DevState | null;
  /** ok = has a value; fault = enabled but the field was empty; waiting = no row yet. */
  status: CardStatus;
  limits: string;
  limitsNote: string | null;
  core: boolean;
}

export interface SensorCards {
  cards: SensorCard[];
  notConnected: Sensor[];
}

/** A row's value for a sensor: a finite number, or null (empty field). */
export function sensorValue(row: RowDict | null | undefined, key: string): number | null {
  const v = row?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function buildSensorCards(registry: Registry | null | undefined, row: RowDict | null | undefined): SensorCards {
  const cards: SensorCard[] = [];
  const notConnected: Sensor[] = [];
  for (const s of registry?.sensors ?? []) {
    if (!s.enabled) {
      notConnected.push(s);
      continue;
    }
    const value = sensorValue(row, s.key);
    const shown = value == null ? null : sensorValueText(s, value);
    cards.push({
      key: s.key,
      name: s.display_name,
      unit: shown?.clear ? `${s.unit} (clear)`.trim() : s.unit,
      hardware: s.hardware,
      value: shown?.text ?? null,
      level: value == null ? null : sensorLevel(s, value),
      status: value != null ? "ok" : row ? "fault" : "waiting",
      limits: limitsText(s),
      limitsNote: s.limits_note,
      core: s.tier === "core",
    });
  }
  return { cards, notConnected };
}

/** Enabled sensors, in registry order (charts, cards). */
export function enabledSensors(registry: Registry | null | undefined): Sensor[] {
  return (registry?.sensors ?? []).filter((s) => s.enabled);
}
