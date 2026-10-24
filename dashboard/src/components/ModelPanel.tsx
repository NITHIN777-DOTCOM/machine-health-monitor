// The Model panel: a right-hand drawer like Controls. What the ML model was trained on, and
// how it did on the held-out test session (rules vs ML, counts, the subtle-fault verdict,
// false alarms, the forecast lead, and one chart of the subtle vibration step).

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, XAxis, YAxis,
} from "recharts";
import { fetchEvaluation, fetchModel } from "../api";
import { formatDate } from "../lib/format";
import {
  chartPoints, faultRows, faultSpans, falseAlarmRows, featureSummary, forecastText, trainedOnText, verdict,
} from "../lib/model";
import type { Evaluation, EvaluationResponse, ModelDetails, Registry, Status } from "../types";
import { Icon } from "./Icon";

interface Props {
  status: Status | null;
  registry: Registry | null;
  onClose: () => void;
}

const SETS = [
  { key: "live", label: "Live labels", note: "Labels as switched by hand during the test. They do not depend on what the device did, so this is the fair comparison of rules vs ML." },
  { key: "cleaned", label: "Cleaned labels", note: "Tidied after the test using the device state: the rules have 0 false alarms and catch 0 subtle-fault rows here by construction." },
] as const;
const AXIS_TICK = { fontSize: 12, fill: "var(--muted)" };

function EvalChart({ ev, warn }: { ev: Evaluation; warn: number | null }) {
  const points = useMemo(() => chartPoints(ev.chart.rows), [ev.chart.rows]);
  const spans = useMemo(() => faultSpans(points), [points]);
  if (!points.length) return null;
  return (
    <figure className="chart eval-chart" data-testid="model-chart">
      <figcaption>
        {ev.chart.name} <span className="muted">(test session, seconds from the step start)</span>
      </figcaption>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} stroke="var(--border)" tick={AXIS_TICK}
              tickLine={false} />
            <YAxis yAxisId="v" stroke="var(--border)" tick={AXIS_TICK} tickLine={false} axisLine={false} width={36} />
            <YAxis yAxisId="h" orientation="right" domain={[0, 120]} ticks={[0, 50, 100]} stroke="var(--border)"
              tick={AXIS_TICK} tickLine={false} axisLine={false} width={30} />
            {spans.map(([a, b]) => (
              <ReferenceArea key={a} yAxisId="v" x1={a - 0.5} x2={b + 0.5} fill="var(--grid)" fillOpacity={0.9}
                ifOverflow="hidden" />
            ))}
            {warn != null && (
              <ReferenceLine yAxisId="v" y={warn} stroke="var(--limit-warn)" strokeDasharray="3 3"
                label={{ value: `warn ${warn}`, position: "insideTopLeft", fill: "var(--muted)", fontSize: 12 }} />
            )}
            <ReferenceLine yAxisId="h" y={50} stroke="var(--st-ml)" strokeDasharray="2 4" strokeOpacity={0.6} />
            <Line yAxisId="v" type="linear" dataKey="value" stroke="var(--accent)" strokeWidth={1.5} dot={false}
              isAnimationActive={false} />
            <Line yAxisId="h" type="linear" dataKey="health" stroke="var(--st-ml)" strokeWidth={1.5} dot={false}
              strokeDasharray="5 3" isAnimationActive={false} connectNulls={false} />
            <Scatter yAxisId="h" dataKey="mlMark" fill="var(--st-ml)" shape="circle" isAnimationActive={false} />
            <Scatter yAxisId="h" dataKey="rulesMark" fill="var(--st-warning)" shape="triangle" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ul className="legend xs muted">
        <li><span className="key key-line" /> vibration (counts/s, left)</li>
        <li><span className="key key-dash" /> ML health (0-100, right; 50 = anomaly)</li>
        <li><span className="key key-ml" /> ML flagged</li>
        <li><span className="key key-rules" /> rules flagged</li>
        <li><span className="key key-fault" /> fault rows</li>
      </ul>
    </figure>
  );
}

export function ModelPanel({ status, registry, onClose }: Props) {
  const [details, setDetails] = useState<ModelDetails | null>(null);
  const [ev, setEv] = useState<EvaluationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setKey, setSetKey] = useState<"live" | "cleaned">("live");
  const created = status?.model.created;

  useEffect(() => {
    let alive = true;
    Promise.all([fetchModel(), fetchEvaluation()])
      .then(([m, e]) => {
        if (!alive) return;
        setDetails(m);
        setEv(e);
        setError(null);
      })
      .catch((err) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      alive = false;
    };
  }, [created]);

  const model = details ?? status?.model ?? null;
  const evaluation = ev && ev.available ? ev : null;
  const sets = evaluation ? SETS.filter((s) => s.key in evaluation.label_sets) : [];
  const active = evaluation?.label_sets[setKey] ? setKey : sets[0]?.key ?? "live";
  const result = evaluation?.label_sets[active];
  const v = evaluation ? verdict(evaluation) : null;
  const fc = evaluation ? forecastText(evaluation) : null;
  const vibWarn = registry?.sensors.find((s) => s.key === evaluation?.chart.sensor)?.warn ?? null;

  return (
    <aside className="controls drawer-wide" aria-labelledby="model-title" data-testid="model-panel">
      <div className="controls-head">
        <h2 id="model-title"><Icon name="spark" size={20} /> Model</h2>
        <button type="button" className="btn btn-icon" onClick={onClose} aria-label="Close model panel" title="Close model panel">
          <Icon name="close" />
        </button>
      </div>
      {error && (
        <div className="inline-error" role="alert"><Icon name="warning" /><span>{error}</span></div>
      )}

      <section className="ctl" aria-labelledby="model-trained">
        <h3 id="model-trained">What the model learned</h3>
        {model?.status !== "READY" ? (
          <p className="inline-info">{model?.message ?? `No model (${model?.status ?? "unknown"}): ML is off, the rules keep working.`}</p>
        ) : (
          <>
            <p className="model-status" data-testid="model-status">{model.status_line ?? (model.provisional ? "provisional model" : "trained model")}</p>
            <dl className="kv small">
              <dt>Trained on</dt><dd className="num">{trainedOnText(details)}</dd>
              <dt>Session</dt><dd>{details?.sessions?.join(", ") || "-"}</dd>
              <dt>Created</dt><dd className="num">{formatDate(model.created)}</dd>
              <dt>Sensors</dt><dd>{featureSummary(details?.feature_names, registry)}</dd>
              <dt>Method</dt><dd>Isolation Forest on {model.window_s ?? 10} s windows, normal data only</dd>
            </dl>
            {model.deployment_note && (
              <p className="inline-note small"><Icon name="info" /> <span>Deployment: {model.deployment_note}.</span></p>
            )}
          </>
        )}
      </section>

      <section className="ctl" aria-labelledby="model-test">
        <h3 id="model-test">Test on unseen data</h3>
        {!evaluation ? (
          <p className="inline-info" data-testid="no-evaluation">{ev && !ev.available ? ev.message : "Loading..."}</p>
        ) : (
          <>
            <p className="stamp xs" data-testid="eval-stamp">{evaluation.stamp}</p>
            <p className="ctl-note">
              Session 02 ({evaluation.rows} s, never used for training or tuning), run once through the live pipeline.
              Counts are rows of 1 s.
            </p>
            {!evaluation.matches_model && evaluation.message && (
              <p className="inline-note small text-warning"><Icon name="warning" /> <span>{evaluation.message}</span></p>
            )}
            <div className="seg seg-full" role="group" aria-label="Label set">
              {sets.map((s) => (
                <button key={s.key} type="button" className="btn" aria-pressed={active === s.key}
                  onClick={() => setSetKey(s.key)}>
                  {s.label}{s.key === "live" ? " (fairer)" : ""}
                </button>
              ))}
            </div>
            <p className="ctl-note">{SETS.find((s) => s.key === active)?.note}</p>
            <table className="eval-table small num" data-testid="eval-table">
              <thead>
                <tr><th scope="col">Fault</th><th scope="col">Rules</th><th scope="col">ML</th><th scope="col">First</th></tr>
              </thead>
              <tbody>
                {faultRows(result).map((r) => (
                  <tr key={r.kind} data-kind={r.kind}>
                    <th scope="row" title={r.name}>{r.short}{r.subtle && <span className="tag">subtle</span>}</th>
                    <td><span className="nowrap">{r.rules}</span><span className="xs muted">{r.rulesDelay}</span></td>
                    <td className={r.mlDelay ? undefined : "muted"}>
                      <span className={r.mlDelay ? "nowrap" : undefined}>{r.ml}</span>
                      {r.mlDelay && <span className="xs muted">{r.mlDelay}</span>}
                    </td>
                    <td>{r.first}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {v && (
              <p className="verdict small" data-testid="verdict">
                <strong>Did ML catch the subtle faults the rules missed? {v.answer}.</strong> {v.text}
              </p>
            )}
            <h3 className="sub">False alarms on normal rows</h3>
            <table className="eval-table small num" data-testid="fa-table">
              <thead><tr><th scope="col">Normal rows</th><th scope="col">Rules</th><th scope="col">ML</th></tr></thead>
              <tbody>
                {falseAlarmRows(result).map((g) => (
                  <tr key={g.name}><th scope="row">{g.name}</th><td>{g.rules}</td><td>{g.ml}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="ctl-note">Not counted: the {evaluation.margin_s} s after each fault (the alarm is still holding by design).</p>
            {fc && <p className="small">{fc}</p>}
            <EvalChart ev={evaluation} warn={vibWarn} />
            <p className="ctl-note">Full report: docs/eval/eval_real_session_02.md</p>
          </>
        )}
      </section>
    </aside>
  );
}
