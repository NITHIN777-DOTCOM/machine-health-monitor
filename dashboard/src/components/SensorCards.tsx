import { buildSensorCards } from "../lib/cards";
import { stateView } from "../lib/format";
import type { Registry, RowDict } from "../types";
import { Icon } from "./Icon";

/** One card per enabled sensor; disabled ones in a compact "Not connected" row. */
export function SensorCards({ registry, row }: { registry: Registry | null; row: RowDict | null }) {
  const { cards, notConnected } = buildSensorCards(registry, row);
  return (
    <section aria-label="Sensors">
      <div className="sensor-grid">
        {cards.map((c) => {
          const view = c.status === "ok" ? stateView(c.level) : null;
          return (
            <article
              key={c.key}
              className={`sensor-card ${view ? `tone-border-${view.tone}` : "tone-border-critical sensor-fault"}`}
              data-sensor={c.key}
              data-status={c.status}
              title={`${c.hardware}${c.limitsNote ? ` - limits: ${c.limitsNote}` : ""}`}
            >
              <div className="sensor-name">{c.name}</div>
              {c.status === "ok" && view ? (
                <>
                  <div className="sensor-value">
                    {c.value}
                    <span className="sensor-unit">{c.unit}</span>
                  </div>
                  <div className={`sensor-level tone-text-${view.tone}`}>
                    <Icon name={view.icon} size={18} />
                    {view.label}
                  </div>
                </>
              ) : c.status === "fault" ? (
                <div className="sensor-fault-text tone-text-critical">
                  <Icon name="warning" size={22} />
                  No reading - sensor fault
                </div>
              ) : (
                <div className="sensor-value muted">-</div>
              )}
              <div className="sensor-limits muted">
                {c.limits}
                {c.limitsNote && <span className="provisional-mark" title={c.limitsNote}> (provisional)</span>}
              </div>
            </article>
          );
        })}
      </div>
      {notConnected.length > 0 && (
        <p className="not-connected muted">
          <Icon name="plug" size={18} /> Not connected: {notConnected.map((s) => s.display_name).join(" · ")}
        </p>
      )}
    </section>
  );
}
