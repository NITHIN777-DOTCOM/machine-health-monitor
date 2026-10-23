// Small line charts of the last 5 minutes on the device ms clock, one per enabled sensor
// plus the ML health score. x = seconds before the newest row (0 = now).

import { memo, useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { WINDOW_MS, type Point } from "../lib/buffer";
import { sensorValue } from "../lib/cards";
import type { Sensor } from "../types";

const SPAN_S = WINDOW_MS / 1000;
const TICKS = [-300, -240, -180, -120, -60, 0];

const tickLabel = (t: number) => (t === 0 ? "now" : `${t / 60} min`);

interface Series {
  t: number;
  v: number | null;
}

interface ChartProps {
  title: string;
  unit: string;
  data: Series[];
  lines: { y: number; label: string; kind: "warn" | "critical" | "threshold" }[];
  domain?: [number, number];
  testId: string;
}

const TrendChart = memo(function TrendChart({ title, unit, data, lines, domain, testId }: ChartProps) {
  return (
    <figure className="chart" data-testid={testId}>
      <figcaption>
        {title} <span className="muted">({unit})</span>
      </figcaption>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 56, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
            <XAxis
              dataKey="t" type="number" domain={[-SPAN_S, 0]} ticks={TICKS} tickFormatter={tickLabel}
              stroke="var(--muted)" tick={{ fontSize: 13, fill: "var(--muted)" }} allowDataOverflow
            />
            <YAxis
              stroke="var(--muted)" tick={{ fontSize: 13, fill: "var(--muted)" }} width={44}
              domain={domain ?? ["auto", "auto"]} allowDecimals
            />
            {lines.map((l) => (
              <ReferenceLine
                key={l.kind}
                y={l.y}
                stroke={`var(--line-${l.kind})`}
                strokeDasharray={l.kind === "critical" ? "8 4" : "4 4"}
                strokeWidth={2}
                ifOverflow="extendDomain"
                label={{ value: l.label, position: "right", fill: `var(--line-${l.kind})`, fontSize: 13 }}
              />
            ))}
            <Line
              type="linear" dataKey="v" stroke="var(--series)" strokeWidth={2.5} dot={false}
              isAnimationActive={false} connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
});

export function TrendCharts({ sensors, points }: { sensors: Sensor[]; points: Point[] }) {
  const charts = useMemo(() => {
    const newest = points[points.length - 1]?.ms ?? 0;
    const t = (p: Point) => (p.ms - newest) / 1000;
    const perSensor = sensors.map((s) => {
      const lines: ChartProps["lines"] = [];
      if (s.warn != null) lines.push({ y: s.warn, label: "warn", kind: "warn" });
      if (s.critical != null) lines.push({ y: s.critical, label: "crit", kind: "critical" });
      return { s, lines, data: points.map((p) => ({ t: t(p), v: sensorValue(p.row, s.key) })) };
    });
    return { perSensor, health: points.map((p) => ({ t: t(p), v: p.health })) };
  }, [sensors, points]);

  return (
    <section className="card charts-card" aria-labelledby="trends-title">
      <h2 id="trends-title">Trends (last 5 minutes)</h2>
      <div className="chart-grid">
        {charts.perSensor.map(({ s, lines, data }) => (
          <TrendChart key={s.key} title={s.display_name} unit={s.unit} data={data} lines={lines} testId={`chart-${s.key}`} />
        ))}
        <TrendChart
          title="ML health score" unit="0-100" data={charts.health} domain={[0, 100]} testId="chart-health"
          lines={[{ y: 50, label: "anomaly", kind: "threshold" }]}
        />
      </div>
    </section>
  );
}
