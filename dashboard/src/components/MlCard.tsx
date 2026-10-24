import { causeText, causeTooltip, healthLabel, healthTone, mlView, visibleCauses, type HealthLevels } from "../lib/format";
import { modelTag } from "../lib/model";
import type { MlBlock, ModelInfo, Registry } from "../types";
import { Icon } from "./Icon";

/** The ML opinion: advisory only (it can raise the overall status to WARNING, never CRITICAL). */
interface Props {
  ml: MlBlock | null;
  registry: Registry | null;
  levels: HealthLevels;
  /** status.model: what the model was trained on (the tag next to the title). */
  model: ModelInfo | null;
}

export function MlCard({ ml, registry, levels, model }: Props) {
  const tag = modelTag(model);
  const view = mlView(ml);
  const health = ml?.health ?? null;
  const tone = healthTone(health, levels);
  const name = (key: string) => registry?.sensors.find((s) => s.key === key)?.display_name;
  // Only when ML is worried, and only features that really differ (|z| >= 2).
  const causes = visibleCauses(ml, levels);
  // Calm when healthy: the bar and number only take a status colour below the clear level.
  const abnormal = tone === "warning" || tone === "ml";
  return (
    <section className="card" aria-labelledby="ml-title" data-ml-status={ml?.status ?? "NONE"}>
      <div className="card-head">
        <h2 id="ml-title">ML anomaly detection</h2>
        {tag && (
          <span className="provisional" title={tag.title} data-testid="model-tag">
            {tag.text}
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
          <div className="xs muted">{health == null ? "no score" : `health · ${healthLabel(health, levels)}`}</div>
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
        <div className="health-mark" style={{ left: `${levels.anomaly_health}%` }} title={`${levels.anomaly_health} = anomaly threshold`} />
      </div>
      <div className="causes small">
        <span className="muted">Biggest differences from normal</span>
        {causes.length ? (
          <ul>
            {causes.map((c) => (
              <li key={c.feature} title={causeTooltip(c)} data-band={c.band}>{causeText(c, name(c.sensor))}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">{health == null ? "None (no score yet)" : "Nothing unusual"}</p>
        )}
      </div>
    </section>
  );
}
