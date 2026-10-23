import { forecastText, forecastTone, trendIcon } from "../lib/format";
import type { Analysis, Registry } from "../types";
import { Icon } from "./Icon";

/** Time-to-limit trend for the sensors the backend forecasts (registry forecast: true). */
export function ForecastPanel({ analysis, registry }: { analysis: Analysis | null; registry: Registry | null }) {
  const entries = Object.entries(analysis?.forecast ?? {});
  const name = (key: string) => registry?.sensors.find((s) => s.key === key)?.display_name ?? key;
  return (
    <section className="card" aria-labelledby="fc-title">
      <h2 id="fc-title">Forecast (trend of the last minute)</h2>
      {entries.length === 0 ? (
        <p className="muted">No sensor has a forecast.</p>
      ) : (
        <ul className="forecast-list">
          {entries.map(([key, f]) => {
            const tone = forecastTone(f);
            return (
              <li key={key} className={`forecast-item tone-border-${tone}`} data-status={f.status}>
                <Icon name={trendIcon(f.trend)} size={28} className={`tone-text-${tone}`} />
                <div>
                  <div className="forecast-text">{forecastText(name(key), f)}</div>
                  <div className="muted small">
                    trend: {f.trend ?? "not enough data yet"}
                    {f.r2 != null && ` · fit R² ${f.r2.toFixed(2)}`}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="muted small">Advice only: the forecast never changes the status.</p>
    </section>
  );
}
