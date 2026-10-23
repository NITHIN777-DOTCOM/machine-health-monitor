// All dashboard data: registry, status, newest analysis and row, the 5-minute trend buffer,
// and the WebSocket link.
//
// - On every (re)connect: GET /api/sensors, /api/status, /api/history?seconds=300, then the
//   stream continues. Rows that arrive while history is loading are queued, not lost.
// - Reconnects with backoff (1, 2, 4, 8, 10 s); while cut off, the last data stays visible.
// - Messages are collected in refs and flushed to React state at most every FLUSH_MS, so
//   10x simulation (10 rows/s) does not re-render the charts 10 times a second.

import { useEffect, useRef, useState } from "react";
import { fetchHistory, fetchSensors, fetchStatus, streamUrl } from "../api";
import { appendPoints, historyToPoints, WINDOW_MS, type Point } from "../lib/buffer";
import type { Analysis, Registry, RowDict, Status, WsMessage } from "../types";

const FLUSH_MS = 250;
const BACKOFF_S = [1, 2, 4, 8, 10];

export type WsState = "connecting" | "open" | "closed";

export interface DashboardData {
  registry: Registry | null;
  status: Status | null;
  analysis: Analysis | null;
  row: RowDict | null;
  points: Point[];
  ws: WsState;
  /** Seconds until the next reconnect attempt while closed. */
  retryInS: number | null;
  /** True once the first load succeeded (before that there is nothing to grey out). */
  loaded: boolean;
  error: string | null;
}

const INITIAL: DashboardData = {
  registry: null, status: null, analysis: null, row: null, points: [],
  ws: "connecting", retryInS: null, loaded: false, error: null,
};

/** Identifies a source run; a change means the backend started a new one. */
function sourceKey(s: Status): string {
  return [s.source, s.scenario, s.file, s.speed].join("|");
}

export function useDashboard(): DashboardData {
  const [data, setData] = useState<DashboardData>(INITIAL);
  const next = useRef<DashboardData>(INITIAL);   // newest values, flushed to state by a timer
  const pending = useRef<Point[]>([]);
  const loadingHistory = useRef(false);
  const dirty = useRef(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let attempt = 0;
    let retryTimer: number | undefined;
    let countdown: number | undefined;
    let stopped = false;

    const update = (patch: Partial<DashboardData>) => {
      next.current = { ...next.current, ...patch };
      dirty.current = true;
    };

    const flush = window.setInterval(() => {
      if (!loadingHistory.current && pending.current.length) {
        const incoming = pending.current;
        pending.current = [];
        update({ points: appendPoints(next.current.points, incoming) });
      }
      if (dirty.current) {
        dirty.current = false;
        setData(next.current);
      }
    }, FLUSH_MS);

    const onStatus = (status: Status) => {
      const prev = next.current.status;
      if (prev && sourceKey(prev) !== sourceKey(status)) {
        pending.current = [];
        update({ points: [], row: null, analysis: null });   // new source: start the charts over
      }
      update({ status, ...(status.analysis && !next.current.analysis ? { analysis: status.analysis } : {}) });
    };

    const load = async () => {
      loadingHistory.current = true;
      try {
        const [registry, status, history] = await Promise.all([
          fetchSensors(), fetchStatus(), fetchHistory(WINDOW_MS / 1000),
        ]);
        const base = appendPoints([], historyToPoints(history.rows));
        const lastMs = base[base.length - 1]?.ms ?? -Infinity;
        // Rows that came over the socket while history loaded, minus those history already has.
        pending.current = pending.current.filter((p) => p.ms > lastMs);
        const lastHist = base[base.length - 1]?.row ?? null;
        update({
          registry, status, points: base, loaded: true, error: null,
          analysis: status.analysis ?? next.current.analysis,
          // History is newer than what we had before a reconnect, unless live rows already came in.
          row: pending.current.length ? next.current.row : lastHist ?? next.current.row,
        });
      } catch (err) {
        update({ error: err instanceof Error ? err.message : String(err) });
      } finally {
        loadingHistory.current = false;
      }
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      const delay = BACKOFF_S[Math.min(attempt, BACKOFF_S.length - 1)] ?? 10;
      attempt += 1;
      let left = delay;
      update({ ws: "closed", retryInS: left });
      window.clearInterval(countdown);
      countdown = window.setInterval(() => {
        left -= 1;
        update({ retryInS: Math.max(0, left) });
      }, 1000);
      retryTimer = window.setTimeout(connect, delay * 1000);
    };

    function connect() {
      window.clearInterval(countdown);
      if (stopped) return;
      update({ ws: "connecting", retryInS: null });
      const sock = new WebSocket(streamUrl());
      ws = sock;
      sock.onopen = () => {
        attempt = 0;
        update({ ws: "open" });
        void load();
      };
      sock.onmessage = (ev: MessageEvent<string>) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(ev.data) as WsMessage;
        } catch {
          return;
        }
        if (msg.type === "status") {
          onStatus(msg.status);
        } else if (msg.type === "row") {
          const { row, analysis } = msg;
          update({ row, analysis });
          if (typeof row.ms === "number") pending.current.push({ ms: row.ms, row, health: analysis.ml.health });
        }
      };
      sock.onerror = () => sock.close();
      sock.onclose = () => {
        if (ws === sock) {
          ws = null;
          scheduleReconnect();
        }
      };
    }

    connect();
    return () => {
      stopped = true;
      window.clearInterval(flush);
      window.clearInterval(countdown);
      window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  return data;
}
