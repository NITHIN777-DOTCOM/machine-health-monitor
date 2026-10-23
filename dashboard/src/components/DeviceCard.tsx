import { stateView, stripRecovering } from "../lib/format";
import type { AnalysisDevice } from "../types";
import { Icon } from "./Icon";

interface Props {
  device: AnalysisDevice | null;
  holdSeconds: number;
}

/** The threshold rules (what the Arduino decides on its own, buzzer + LCD). */
export function DeviceCard({ device, holdSeconds }: Props) {
  const state = device ? device.reported ?? device.state : null;
  const view = stateView(state);
  const clearing = device?.hold_remaining_s != null;
  return (
    <section className="card" aria-labelledby="device-title">
      <h2 id="device-title">Device rules</h2>
      <div className={`state-pill tone-${view.tone}`}>
        <Icon name={view.icon} size={28} />
        {view.label}
      </div>
      <p className="reason">
        {device?.reason ? stripRecovering(device.reason) : state === "NORMAL" ? "All values inside their limits" : "-"}
      </p>
      {clearing && device && (
        // Shown quietly: a value dipping into the hysteresis band starts this too.
        <p className="muted small" data-testid="hold">
          <Icon name="clock" size={16} /> Values back inside limits; holding {holdSeconds - (device.hold_remaining_s ?? 0)} of {holdSeconds} s before stepping down
        </p>
      )}
      <p className="muted small mirror">
        {device?.agrees == null ? (
          <>No device report yet</>
        ) : device.agrees ? (
          <><Icon name="ok" size={16} /> Backend mirror agrees with the device</>
        ) : (
          <span className="tone-text-warning">
            <Icon name="warning" size={16} /> Mismatch: device says {device.reported}, backend mirror says {device.state}
          </span>
        )}
      </p>
    </section>
  );
}
