// The in-memory trend buffer: at most WINDOW_MS of rows, on the device ms clock (the same
// clock the backend uses for windows and replay, so 10x simulation shows 5 device-minutes).

import type { CompactAnalysis, HistoryRow, RowDict } from "../types";

export const WINDOW_MS = 5 * 60 * 1000;

export interface Point {
  /** Device clock, ms. */
  ms: number;
  row: RowDict;
  /** ML health 0-100 for this row, or null. */
  health: number | null;
}

/** Append points, oldest first. A device clock that goes backwards (new source, device
 *  reset) starts a new buffer, as the backend's forecast history does. */
export function appendPoints(buf: Point[], incoming: Point[], windowMs = WINDOW_MS): Point[] {
  let out = buf.slice();
  for (const p of incoming) {
    const last = out[out.length - 1];
    if (last && p.ms <= last.ms) out = [p];
    else out.push(p);
  }
  const newest = out[out.length - 1];
  if (!newest) return out;
  const cutoff = newest.ms - windowMs;
  const first = out.findIndex((p) => p.ms > cutoff);
  return first > 0 ? out.slice(first) : out;
}

/** /api/history rows -> points (rows without ms cannot be placed on the clock). */
export function historyToPoints(rows: HistoryRow[]): Point[] {
  const out: Point[] = [];
  for (const h of rows) {
    const { analysis, ...rest } = h;
    const row = rest as unknown as RowDict;
    if (typeof row.ms !== "number") continue;
    out.push({ ms: row.ms, row, health: (analysis as CompactAnalysis | null | undefined)?.health ?? null });
  }
  return out;
}
