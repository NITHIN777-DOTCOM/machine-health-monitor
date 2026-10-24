// Backend access. Every URL is relative, so the same build works under the Vite dev proxy
// and when FastAPI serves the dashboard itself (Phase 6).

import { apiErrorText, type SourceBody } from "./lib/controls";
import type {
  EvaluationResponse, HistoryResponse, Label, ModelDetails, Recording, Registry, Status,
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

/** POST with a JSON body. Throws an Error whose message is ready to show the user. */
async function postJson<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(apiErrorText(null, null));
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? null;
    } catch {
      // not JSON: keep the HTTP status only
    }
    throw new Error(apiErrorText(res.status, detail));
  }
  return (await res.json()) as T;
}

export const fetchSensors = () => getJson<Registry>("/api/sensors");
export const fetchStatus = () => getJson<Status>("/api/status");
export const fetchHistory = (seconds: number) => getJson<HistoryResponse>(`/api/history?seconds=${seconds}`);
export const fetchRecordings = () => getJson<{ recordings: Recording[] }>("/api/recordings").then((r) => r.recordings);

export const setSource = (body: SourceBody) => postJson<Status>("/api/source", body);
export const startRecording = () => postJson<unknown>("/api/record/start");
export const stopRecording = () => postJson<unknown>("/api/record/stop");
export const setLabel = (label: Label | null) => postJson<unknown>("/api/label", { label });
export const warmStart = (file: string) => postJson<{ message: string }>("/api/warmstart", { file });

/** ws://host/ws/stream (wss:// on https), relative to the page. */
export function streamUrl(loc: Pick<Location, "protocol" | "host"> = window.location): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws/stream`;
}

export const fetchModel = () => getJson<ModelDetails>("/api/model");
export const fetchEvaluation = () => getJson<EvaluationResponse>("/api/model/evaluation");
