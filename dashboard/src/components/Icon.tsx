// One icon set (lucide-react, bundled: works offline), drawn at a few fixed sizes.
import {
  Activity, ArrowRight, CircleCheck, CircleOff, Clock, Database, FlaskConical, Info, Moon, OctagonAlert,
  Pause, Play, Radio, Repeat, Settings2, Sparkles, Square, Sun, TrendingDown, TrendingUp, TriangleAlert,
  Unplug, X, type LucideIcon,
} from "lucide-react";
import type { IconName } from "../lib/format";

const ICONS: Record<IconName, LucideIcon> = {
  ok: CircleCheck,
  warning: TriangleAlert,
  critical: OctagonAlert,
  info: Info,
  pulse: Activity,
  clock: Clock,
  off: CircleOff,
  spark: Sparkles,
  up: TrendingUp,
  down: TrendingDown,
  flat: ArrowRight,
  plug: Unplug,
  sun: Sun,
  moon: Moon,
  settings: Settings2,
  play: Play,
  pause: Pause,
  stop: Square,
  record: Radio,
  file: Database,
  sim: FlaskConical,
  loop: Repeat,
  close: X,
};

/** Sizes used across the dashboard: 16 inline, 20 headings and buttons, 32 banner. */
export type IconSize = 16 | 20 | 32;

export function Icon({ name, size = 16, className }: { name: IconName; size?: IconSize; className?: string }) {
  const Cmp = ICONS[name];
  return (
    <Cmp className={className ? `icon ${className}` : "icon"} size={size} strokeWidth={size >= 32 ? 1.75 : 2}
      aria-hidden="true" focusable="false" />
  );
}
