// Backend access. Every URL is relative, so the same build works under the Vite dev proxy
// and when FastAPI serves the dashboard itself (Phase 6).

import type { HistoryResponse, Registry, Status } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const fetchSensors = () => getJson<Registry>("/api/sensors");
export const fetchStatus = () => getJson<Status>("/api/status");
export const fetchHistory = (seconds: number) => getJson<HistoryResponse>(`/api/history?seconds=${seconds}`);

/** ws://host/ws/stream (wss:// on https), relative to the page. */
export function streamUrl(loc: Pick<Location, "protocol" | "host"> = window.location): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws/stream`;
}
