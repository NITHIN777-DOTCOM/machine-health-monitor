// The control panel: a right-hand drawer, so the main view stays uncluttered.
// Source (Live / Simulated / Recorded), scenarios + speed, Record / Stop + label, Replay,
// warm start. One request at a time: every button is disabled while one is in flight,
// and errors are shown inline at the top of the panel.

import { useCallback, useEffect, useReducer, useState } from "react";
import { fetchRecordings, setLabel, setSource, startRecording, stopRecording, warmStart } from "../api";
import { useNow } from "../hooks/useNow";
import {
  actionReducer, activeKind, availableScenarios, FAST_FORWARD, formatDuration, formatElapsed, IDLE,
  isActiveScenario, liveBody, liveOption, replayBody, replayProgress, scenarioBody, SPEEDS, type SourceKind,
} from "../lib/controls";
import { formatDate } from "../lib/format";
import type { Label, Recording, Status } from "../types";
import { Icon } from "./Icon";

interface Props {
  status: Status | null;
  onClose: () => void;
}

function SpeedPicker({ value, onChange, disabled, label }: {
  value: number; onChange: (s: number) => void; disabled: boolean; label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {SPEEDS.map((s) => (
        <button key={s} type="button" className="btn" aria-pressed={value === s} disabled={disabled}
          onClick={() => onChange(s)}>
          {s}x
        </button>
      ))}
    </div>
  );
}

export function ControlsPanel({ status, onClose }: Props) {
  const [action, dispatch] = useReducer(actionReducer, IDLE);
  const [tab, setTab] = useState<SourceKind>(() => activeKind(status) ?? "simulated");
  const [simSpeed, setSimSpeed] = useState<number>(status?.source === "simulator" ? status.speed ?? 1 : 1);
  // Start from what is running, so the panel matches a replay started elsewhere.
  const replaying = status?.source === "replay";
  const [replaySpeed, setReplaySpeed] = useState<number>(replaying ? status.speed ?? 1 : 5);
  const [loop, setLoop] = useState<boolean>(replaying ? !!status.loop : false);
  const [recordings, setRecordings] = useState<Recording[] | null>(null);
  const [file, setFile] = useState<string>(replaying ? status.file ?? "" : "");
  const [warmFile, setWarmFile] = useState<string>("");
  const [info, setInfo] = useState<string | null>(null);

  const active = activeKind(status);
  const live = liveOption(status);
  const rec = status?.recording;
  const now = useNow(!!rec?.on);
  const busy = action.busy != null;
  const progress = replayProgress(status);

  const loadRecordings = useCallback(async () => {
    try {
      const list = await fetchRecordings();
      setRecordings(list);
      setFile((f) => (f && list.some((r) => r.file === f) ? f : list[0]?.file ?? ""));
      setWarmFile((f) => (f && list.some((r) => r.file === f) ? f : list[0]?.file ?? ""));
    } catch (err) {
      dispatch({ type: "fail", error: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  useEffect(() => {
    void loadRecordings();
  }, [loadRecordings]);

  // Follow a replay that is running (started here, by a script or before the panel had
  // its first status), so speed, loop and the selected file show what is playing.
  const rSpeed = status?.source === "replay" ? status.speed : null;
  const rLoop = status?.source === "replay" ? status.loop : null;
  const rFile = status?.source === "replay" ? status.file : null;
  useEffect(() => {
    if (rFile == null) return;
    setTab("recorded");
    setFile(rFile);
    if (rSpeed != null) setReplaySpeed(rSpeed);
    setLoop(!!rLoop);
  }, [rFile, rSpeed, rLoop]);

  /** Run one request; the panel shows its error inline. */
  const run = async (key: string, fn: () => Promise<unknown>, done?: string) => {
    dispatch({ type: "start", key });
    setInfo(null);
    try {
      await fn();
      dispatch({ type: "ok" });
      if (done) setInfo(done);
    } catch (err) {
      dispatch({ type: "fail", error: err instanceof Error ? err.message : String(err) });
    }
  };

  const chooseTab = (k: SourceKind) => {
    setTab(k);
    if (k === "live" && active !== "live") void run("live", () => setSource(liveBody()));
    if (k === "simulated" && active !== "simulated") void run("sim", () => setSource(scenarioBody("normal", simSpeed)));
  };

  const changeSimSpeed = (s: number) => {
    setSimSpeed(s);
    // Applies at once: the running scenario restarts at the new speed.
    if (status?.source === "simulator" && status.speed !== s) {
      void run("sim", () => setSource(scenarioBody(status.scenario ?? "normal", s)));
    }
  };

  const toggleRecording = () =>
    rec?.on
      ? run("record", async () => { await stopRecording(); await loadRecordings(); }, "Recording saved")
      : run("record", startRecording);

  const chooseLabel = (label: Label | null) => run("label", () => setLabel(label));

  // The serial source reports a busy port in last_error (the switch itself succeeds).
  const sourceError = status?.source === "serial" && status.last_error ? status.last_error : null;

  return (
    <aside className="controls" aria-labelledby="controls-title" data-testid="controls">
      <div className="controls-head">
        <h2 id="controls-title"><Icon name="settings" size={20} /> Controls</h2>
        <button type="button" className="btn btn-icon" onClick={onClose} aria-label="Close controls" title="Close controls">
          <Icon name="close" />
        </button>
      </div>

      {(action.error || sourceError) && (
        <div className="inline-error" role="alert" data-testid="controls-error">
          <Icon name="warning" />
          <span>{action.error ?? sourceError}</span>
        </div>
      )}
      {info && !action.error && <p className="inline-info" role="status">{info}</p>}

      {/* ---- source --------------------------------------------------------------- */}
      <section className="ctl">
        <h3>Data source</h3>
        <div className="seg seg-full" role="group" aria-label="Data source">
          <button type="button" className="btn" aria-pressed={tab === "live"} disabled={busy || !live.enabled}
            onClick={() => chooseTab("live")} title={live.note ?? "Live data from the Arduino"}>
            Live (Arduino)
          </button>
          <button type="button" className="btn" aria-pressed={tab === "simulated"} disabled={busy}
            onClick={() => chooseTab("simulated")}>
            Simulated
          </button>
          <button type="button" className="btn" aria-pressed={tab === "recorded"} disabled={busy}
            onClick={() => chooseTab("recorded")}>
            Recorded
          </button>
        </div>
        <p className="ctl-note">
          {!live.enabled && live.note ? <>Live unavailable: {live.note}</> : live.note}
        </p>
      </section>

      {/* ---- scenarios -------------------------------------------------------------- */}
      {tab === "simulated" && (
        <section className="ctl" data-testid="ctl-scenarios">
          <h3>Scenario</h3>
          <div className="btn-grid">
            {availableScenarios(status).map((sc) => (
              <button key={sc.key} type="button" className="btn" disabled={busy}
                aria-pressed={isActiveScenario(status, sc.key)}
                onClick={() => run("sim", () => setSource(scenarioBody(sc.key, simSpeed)))}>
                {sc.label}
              </button>
            ))}
          </div>
          <div className="ctl-row">
            <span className="small muted">Speed</span>
            <SpeedPicker value={simSpeed} onChange={changeSimSpeed} disabled={busy} label="Simulation speed" />
          </div>
          <button type="button" className="btn btn-wide" disabled={busy}
            onClick={() => {
              setSimSpeed(FAST_FORWARD.speed);
              void run("sim", () => setSource(scenarioBody(FAST_FORWARD.scenario, FAST_FORWARD.speed)));
            }}>
            <Icon name="play" /> Fast-forward drift (slow drift at 10x)
          </button>
          <p className="ctl-note">A speed change restarts the running scenario.</p>
        </section>
      )}

      {/* ---- replay ----------------------------------------------------------------- */}
      {tab === "recorded" && (
        <section className="ctl" data-testid="ctl-replay">
          <h3>Replay a recording</h3>
          {recordings == null ? (
            <p className="ctl-note">Loading recordings...</p>
          ) : recordings.length === 0 ? (
            <p className="ctl-note">No recordings yet. Use Record below to make one.</p>
          ) : (
            <ul className="rec-list" role="listbox" aria-label="Recordings">
              {recordings.map((r) => (
                <li key={r.file}>
                  <button type="button" role="option" aria-selected={file === r.file}
                    className={`rec-item ${file === r.file ? "selected" : ""}`} onClick={() => setFile(r.file)}>
                    <span className="rec-name">{r.file}</span>
                    <span className="xs muted num">
                      {formatDuration(r.duration_s)} · {r.rows} rows · {formatDate(r.modified)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="ctl-row">
            <span className="small muted">Speed</span>
            <SpeedPicker value={replaySpeed} onChange={setReplaySpeed} disabled={busy} label="Replay speed" />
          </div>
          <label className="check">
            <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} disabled={busy} />
            Loop
          </label>
          <div className="ctl-row">
            <button type="button" className="btn btn-primary" disabled={busy || !file}
              onClick={() => run("replay", () => setSource(replayBody(file, replaySpeed, loop)))}>
              <Icon name="play" /> Play
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => void loadRecordings()}>
              Refresh list
            </button>
          </div>
          {progress.pct != null && (
            <div className="progress" data-testid="replay-progress">
              <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={progress.pct} aria-label="Replay progress">
                <div className="progress-fill" style={{ width: `${progress.pct}%` }} />
              </div>
              <span className="xs muted num">{status?.file}: {progress.text}</span>
            </div>
          )}
        </section>
      )}

      {/* ---- record ----------------------------------------------------------------- */}
      <section className="ctl" data-testid="ctl-record">
        <h3>Record</h3>
        <div className="ctl-row">
          <button type="button" className={`btn ${rec?.on ? "btn-stop" : ""}`} disabled={busy} onClick={() => void toggleRecording()}>
            <Icon name={rec?.on ? "stop" : "record"} /> {rec?.on ? "Stop recording" : "Start recording"}
          </button>
          {rec?.on && (
            <span className="rec">
              <span className="rec-dot" aria-hidden="true" />
              <span className="num">{formatElapsed(rec.started_at, now)} · {rec.rows} rows</span>
            </span>
          )}
        </div>
        {rec?.file && <p className="ctl-note">{rec.on ? "Writing to" : "Last file:"} {rec.file}</p>}
        <div className="ctl-row">
          <span className="small muted">Label</span>
          <div className="seg" role="group" aria-label="Label for live rows">
            <button type="button" className="btn" aria-pressed={rec?.label === "normal"} disabled={busy}
              onClick={() => void chooseLabel("normal")}>
              Normal
            </button>
            <button type="button" className="btn" aria-pressed={rec?.label === "fault"} disabled={busy}
              onClick={() => void chooseLabel("fault")}>
              Fault
            </button>
            <button type="button" className="btn" aria-pressed={!rec?.label} disabled={busy}
              onClick={() => void chooseLabel(null)}>
              None
            </button>
          </div>
        </div>
        <p className="ctl-note">
          Current label: <strong>{rec?.label ?? "none (unknown)"}</strong>. Mark induced faults live with
          Fault, then back to Normal. The label is stored on live (Arduino) rows; simulated and
          replayed rows keep their own label.
        </p>
      </section>

      {/* ---- warm start ---------------------------------------------------------------- */}
      <section className="ctl">
        <h3>Start from recording</h3>
        <p className="ctl-note">
          Pre-fills the ML window and the forecast from the end of a recording, so the current
          source skips "warming up".
        </p>
        <div className="ctl-row">
          <select className="select" value={warmFile} onChange={(e) => setWarmFile(e.target.value)}
            disabled={busy || !recordings?.length} aria-label="Recording to warm-start from">
            {(recordings ?? []).map((r) => <option key={r.file} value={r.file}>{r.file}</option>)}
            {!recordings?.length && <option value="">No recordings</option>}
          </select>
          <button type="button" className="btn" disabled={busy || !warmFile}
            onClick={() => run("warm", () => warmStart(warmFile), `Warm start queued from ${warmFile}`)}>
            Start from it
          </button>
        </div>
      </section>
    </aside>
  );
}
