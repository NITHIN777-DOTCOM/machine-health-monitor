import { buildSensorCards } from "../lib/cards";
import { stateView } from "../lib/format";
import type { Registry, RowDict } from "../types";
import { Icon } from "./Icon";

/** One card per enabled sensor; disabled ones in a compact "Not connected" line. A card
 *  stays neutral while its value is normal and gets a status bar only when it is not. */
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
              className="sensor-card"
              data-sensor={c.key}
              data-status={c.status}
              data-level={c.level ?? undefined}
              title={`${c.hardware}${c.limitsNote ? ` - limits: ${c.limitsNote}` : ""}`}
            >
              <div className="sensor-head">
                <span className="sensor-name">{c.name}</span>
                {view && (
                  <span className={`sensor-level ${c.level === "NORMAL" ? "muted" : `text-${view.tone}`}`}>
                    {c.level !== "NORMAL" && <Icon name={view.icon} />}
                    {view.label}
                  </span>
                )}
              </div>
              {c.status === "ok" ? (
                <div className="sensor-value">
                  {c.value}
                  <span className="sensor-unit">{c.unit}</span>
                </div>
              ) : c.status === "fault" ? (
                <div className="sensor-fault-text text-critical">
                  <Icon name="warning" size={20} />
                  No reading - sensor fault
                </div>
              ) : (
                <div className="sensor-value muted">-</div>
              )}
              <div className="sensor-limits">
                {c.limits}
                {c.limitsNote && <span title={c.limitsNote}> (provisional)</span>}
              </div>
            </article>
          );
        })}
      </div>
      {notConnected.length > 0 && (
        <p className="not-connected">
          <Icon name="plug" /> Not connected: {notConnected.map((s) => s.display_name).join(" · ")}
        </p>
      )}
    </section>
  );
}
