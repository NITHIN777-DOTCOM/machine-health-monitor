import { causeText, healthLabel, healthTone, mlView } from "../lib/format";
import type { MlBlock } from "../types";
import { Icon } from "./Icon";

/** The ML opinion: advisory only (it can raise the overall status to WARNING, never CRITICAL). */
export function MlCard({ ml }: { ml: MlBlock | null }) {
  const view = mlView(ml);
  const health = ml?.health ?? null;
  const tone = healthTone(health);
  return (
    <section className="card" aria-labelledby="ml-title" data-ml-status={ml?.status ?? "NONE"}>
      <h2 id="ml-title">
        ML anomaly detection
        {ml?.provisional && (
          <span className="tag" title="The model was trained on simulated data only; it must be retrained on real recordings">
            provisional model (trained on simulated data)
          </span>
        )}
      </h2>
      <div className="ml-top">
        <div>
          <div className={`state-pill tone-${view.tone}`}>
            <Icon name={view.icon} size={28} />
            {view.label}
          </div>
          {view.detail && <p className="muted small">{view.detail}</p>}
        </div>
        <div className="health">
          <div className="health-label">Health</div>
          <div className={`health-value tone-text-${tone}`} data-testid="health">
            {health == null ? "-" : Math.round(health)}
            <span className="health-max">/100</span>
          </div>
          <div className="small muted">{healthLabel(health)}</div>
        </div>
      </div>
      <div
        className="health-bar"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={health ?? undefined}
        aria-label="ML health score"
      >
        <div className={`health-fill tone-${tone}`} style={{ width: `${health ?? 0}%` }} />
        <div className="health-mark" style={{ left: "50%" }} title="50 = anomaly threshold" />
      </div>
      <div className="causes">
        <span className="muted small">Biggest differences from normal:</span>
        {ml && ml.causes.length ? (
          <ul>
            {ml.causes.slice(0, 2).map((c) => (
              <li key={c.feature}>{causeText(c)}</li>
            ))}
          </ul>
        ) : (
          <span className="small"> none (no score)</span>
        )}
      </div>
    </section>
  );
}
