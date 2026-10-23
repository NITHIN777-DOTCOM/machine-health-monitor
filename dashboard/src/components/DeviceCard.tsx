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
      <div className="card-head">
        <h2 id="device-title">Device rules</h2>
        <span className="xs muted">limits + sensor faults</span>
      </div>
      <div className={`state-line text-${view.tone}`}>
        <Icon name={view.icon} size={20} />
        {view.label}
      </div>
      <p className="reason small">
        {device?.reason ? stripRecovering(device.reason) : state === "NORMAL" ? "All values inside their limits" : "-"}
      </p>
      {clearing && device && (
        // Shown quietly: a value dipping into the hysteresis band starts this too.
        <p className="meta num" data-testid="hold">
          <Icon name="clock" /> Back inside limits; holding {holdSeconds - (device.hold_remaining_s ?? 0)} of {holdSeconds} s before stepping down
        </p>
      )}
      <p className="meta">
        {device?.agrees == null ? (
          <>No device report yet</>
        ) : device.agrees ? (
          <>Backend mirror agrees with the device</>
        ) : (
          <span className="text-warning row">
            <Icon name="warning" /> Mismatch: device says {device.reported}, backend mirror says {device.state}
          </span>
        )}
      </p>
    </section>
  );
}
