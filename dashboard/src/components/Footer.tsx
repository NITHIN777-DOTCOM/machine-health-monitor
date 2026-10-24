import { formatDate, versionText } from "../lib/format";
import type { Status } from "../types";

export function Footer({ status }: { status: Status | null }) {
  if (!status) return <footer className="footer">Not connected to the backend yet.</footer>;
  const source = [
    status.source ?? "no source",
    status.scenario && `scenario ${status.scenario}`,
    status.file && `file ${status.file}`,
    status.speed != null && status.speed !== 1 && `${status.speed}x speed`,
  ].filter(Boolean).join(", ");
  const model = status.model;
  return (
    <footer className="footer num">
      <span>Source: {source}</span>
      <span>Serial port: {status.serial_port ?? "none"}</span>
      <span>Rows received: {status.rows_received} · rejected: {status.rows_rejected}</span>
      <span>
        Model: {model.status === "READY" ? `created ${formatDate(model.created)}` : model.status}
        {model.provisional && " (provisional)"}
      </span>
      {status.version && <span>Version: {versionText(status.version)}</span>}
      {status.registry_warnings.length > 0 && (
        <span className="text-warning">Registry warnings: {status.registry_warnings.join("; ")}</span>
      )}
    </footer>
  );
}
