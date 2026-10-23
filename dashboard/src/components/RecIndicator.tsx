import { useNow } from "../hooks/useNow";
import { formatElapsed } from "../lib/controls";
import type { RecordingStatus } from "../types";

/** "REC 1:23 · 83 rows" in the top bar while recording, visible with the panel closed. */
export function RecIndicator({ rec }: { rec: RecordingStatus | null | undefined }) {
  const now = useNow(!!rec?.on);
  if (!rec?.on) return null;
  return (
    <span className="rec" data-testid="rec-indicator" title={`Recording to ${rec.file ?? "file"}`}>
      <span className="rec-dot" aria-hidden="true" />
      REC <span className="num">{formatElapsed(rec.started_at, now)}</span>
      <span className="muted num">· {rec.rows} rows{rec.label ? ` · label ${rec.label}` : ""}</span>
    </span>
  );
}
