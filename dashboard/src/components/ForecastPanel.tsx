import { forecastDetail, forecastText, forecastTone, trendIcon } from "../lib/format";
import type { Analysis, Registry } from "../types";
import { Icon } from "./Icon";

/** Time-to-limit trend for the sensors the backend forecasts (registry forecast: true). */
export function ForecastPanel({ analysis, registry }: { analysis: Analysis | null; registry: Registry | null }) {
  const entries = Object.entries(analysis?.forecast ?? {});
  const name = (key: string) => registry?.sensors.find((s) => s.key === key)?.display_name ?? key;
  return (
    <section className="card" aria-labelledby="fc-title">
      <div className="card-head">
        <h2 id="fc-title">Forecast</h2>
        <span className="xs muted">trend of the last minute</span>
      </div>
      {entries.length === 0 ? (
        <p className="muted">No sensor has a forecast.</p>
      ) : (
        <ul className="forecast-list">
          {entries.map(([key, f]) => {
            const tone = forecastTone(f);
            return (
              <li key={key} className="forecast-item" data-status={f.status}>
                <Icon name={f.status === "no_data" ? "off" : trendIcon(f.trend)} size={16} className={`text-${tone}`} />
                <div>
                  <div className={`forecast-text ${tone === "warning" || tone === "critical" ? `text-${tone}` : ""}`}>
                    {forecastText(name(key), f)}
                  </div>
                  <div className="xs muted" title={f.r2 != null ? `Line fit R² = ${f.r2.toFixed(2)} (low < 0.6 ≤ medium < 0.85 ≤ high)` : undefined}>
                    {forecastDetail(f)}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="card-note">Advice only: the forecast never changes the status.</p>
    </section>
  );
}
