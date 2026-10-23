import { causeText, healthLabel, healthTone, mlView } from "../lib/format";
import type { MlBlock } from "../types";
import { Icon } from "./Icon";

/** The ML opinion: advisory only (it can raise the overall status to WARNING, never CRITICAL). */
export function MlCard({ ml }: { ml: MlBlock | null }) {
  const view = mlView(ml);
  const health = ml?.health ?? null;
  const tone = healthTone(health);
  // Calm when healthy: the bar and number only take a status colour below the clear level.
  const abnormal = tone === "warning" || tone === "ml";
  return (
    <section className="card" aria-labelledby="ml-title" data-ml-status={ml?.status ?? "NONE"}>
      <div className="card-head">
        <h2 id="ml-title">ML anomaly detection</h2>
        {ml?.provisional && (
          <span className="provisional" title="The model was trained on simulated data only; it must be retrained on real recordings">
            provisional model
          </span>
        )}
      </div>
      <div className="ml-top">
        <div>
          <div className={`state-line text-${view.tone === "normal" ? "normal" : view.tone}`}>
            <Icon name={view.icon} size={20} />
            {view.label}
          </div>
          {view.detail && <p className="small muted">{view.detail}</p>}
        </div>
        <div className="health">
          <div className={`health-value ${abnormal ? `text-${tone}` : ""}`} data-testid="health">
            {health == null ? "-" : Math.round(health)}
            <span className="health-max">/100</span>
          </div>
          <div className="xs muted">health · {healthLabel(health)}</div>
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
        <div className={`health-fill ${abnormal ? `fill-${tone}` : ""}`} style={{ width: `${health ?? 0}%` }} />
        <div className="health-mark" style={{ left: "50%" }} title="50 = anomaly threshold" />
      </div>
      <div className="causes small">
        <span className="muted">Biggest differences from normal</span>
        {ml && ml.causes.length ? (
          <ul>
            {ml.causes.slice(0, 2).map((c) => (
              <li key={c.feature}>{causeText(c)}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">None (no score yet)</p>
        )}
      </div>
    </section>
  );
}
