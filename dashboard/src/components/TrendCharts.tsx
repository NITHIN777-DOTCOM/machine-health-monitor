// Small line charts of the last 5 minutes on the device ms clock, one per enabled sensor
// plus the ML health score, all in one grid and one style: a thin teal line, faint
// gridlines, muted dashed limit lines labelled at the right edge.
// x = seconds before the newest row (0 = now).

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { WINDOW_MS, type Point } from "../lib/buffer";
import { sensorValue } from "../lib/cards";
import { chartGrid } from "../lib/grid";
import type { Sensor } from "../types";

const SPAN_S = WINDOW_MS / 1000;
const TICKS = [-300, -240, -180, -120, -60, 0];
const AXIS_TICK = { fontSize: 12, fill: "var(--muted)" };

const tickLabel = (t: number) => (t === 0 ? "now" : `${t / 60} min`);

interface Series {
  t: number;
  v: number | null;
}

export interface LimitLine {
  y: number;
  label: string;
  kind: "warn" | "crit";
}

interface ChartProps {
  title: string;
  unit: string;
  data: Series[];
  lines: LimitLine[];
  domain?: [number, number];
  testId: string;
  span: number;
}

const TrendChart = memo(function TrendChart({ title, unit, data, lines, domain, testId, span }: ChartProps) {
  return (
    <figure className="chart" data-testid={testId} style={span > 1 ? { gridColumn: `span ${span}` } : undefined}>
      <figcaption>
        {title} <span className="muted">({unit})</span>
      </figcaption>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 76, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="t" type="number" domain={[-SPAN_S, 0]} ticks={TICKS} tickFormatter={tickLabel}
              stroke="var(--border)" tick={AXIS_TICK} tickLine={false} allowDataOverflow
            />
            <YAxis
              stroke="var(--border)" tick={AXIS_TICK} tickLine={false} axisLine={false} width={40}
              domain={domain ?? ["auto", "auto"]} allowDecimals
            />
            {lines.map((l) => (
              <ReferenceLine
                key={l.label}
                y={l.y}
                stroke={`var(--limit-${l.kind})`}
                strokeDasharray={l.kind === "crit" ? "6 3" : "3 3"}
                strokeWidth={1}
                ifOverflow="extendDomain"
                label={{ value: l.label, position: "right", fill: "var(--muted)", fontSize: 12 }}
              />
            ))}
            <Line
              type="linear" dataKey="v" stroke="var(--accent)" strokeWidth={1.5} dot={false}
              isAnimationActive={false} connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
});

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(1200);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 1200));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

interface Props {
  sensors: Sensor[];
  points: Point[];
  /** ML anomaly / clear health levels from the backend (GET /api/status ml_thresholds). */
  healthLines: LimitLine[];
}

export function TrendCharts({ sensors, points, healthLines }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const charts = useMemo(() => {
    const newest = points[points.length - 1]?.ms ?? 0;
    const t = (p: Point) => (p.ms - newest) / 1000;
    const perSensor = sensors.map((s) => {
      const lines: LimitLine[] = [];
      if (s.warn != null) lines.push({ y: s.warn, label: `warn ${s.warn}`, kind: "warn" });
      if (s.critical != null) lines.push({ y: s.critical, label: `crit ${s.critical}`, kind: "crit" });
      return { s, lines, data: points.map((p) => ({ t: t(p), v: sensorValue(p.row, s.key) })) };
    });
    return { perSensor, health: points.map((p) => ({ t: t(p), v: p.health })) };
  }, [sensors, points]);
  const layout = chartGrid(charts.perSensor.length + 1, width);

  return (
    <section className="card" aria-labelledby="trends-title">
      <div className="card-head">
        <h2 id="trends-title">Trends</h2>
        <span className="xs muted">last 5 minutes</span>
      </div>
      <div className="chart-grid" ref={ref} style={{ "--cols": layout.cols } as React.CSSProperties}>
        {charts.perSensor.map(({ s, lines, data }) => (
          <TrendChart key={s.key} title={s.display_name} unit={s.unit} data={data} lines={lines}
            testId={`chart-${s.key}`} span={1} />
        ))}
        <TrendChart
          title="ML health score" unit="0-100" data={charts.health} domain={[0, 100]} testId="chart-health"
          lines={healthLines} span={layout.lastSpan}
        />
      </div>
    </section>
  );
}
