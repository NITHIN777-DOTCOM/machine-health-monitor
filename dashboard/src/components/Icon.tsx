// Small inline SVG icons (no icon font or CDN: the dashboard must work offline).
import type { IconName } from "../lib/format";

const PATHS: Record<IconName, React.ReactNode> = {
  ok: (<><circle cx="12" cy="12" r="10" /><path d="M7.5 12.5l3 3 6-6.5" /></>),
  warning: (<><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /><path d="M12 9v4.5M12 17.2v.1" /></>),
  critical: (<><path d="M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9z" /><path d="M15 9l-6 6M9 9l6 6" /></>),
  info: (<><circle cx="12" cy="12" r="10" /><path d="M12 11v6M12 7.2v.1" /></>),
  pulse: <path d="M2 12h4l3-8 4 16 3-8h6" />,
  clock: (<><circle cx="12" cy="12" r="10" /><path d="M12 6.5V12l3.5 2" /></>),
  off: (<><circle cx="12" cy="12" r="10" /><path d="M5 5l14 14" /></>),
  spark: <path d="M13 2L4 14h7l-1 8 9-12h-7z" />,
  up: <path d="M6 18L18 6M9 6h9v9" />,
  down: <path d="M6 6l12 12M18 9v9H9" />,
  flat: <path d="M4 12h16M14 6l6 6-6 6" />,
  plug: (<><path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 01-12 0zM12 17v5" /><path d="M3 3l18 18" /></>),
  sun: (<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>),
  moon: <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />,
  dot: <circle cx="12" cy="12" r="5" fill="currentColor" />,
};

export function Icon({ name, size = 24, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
