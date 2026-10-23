// Chart grid layout: as many columns as fit, balanced over the rows, and the last chart
// stretched over any empty cells so no row ends with a gap. Pure (unit-tested).

export interface GridLayout {
  cols: number;
  /** How many columns the last chart spans (1 = normal). */
  lastSpan: number;
}

export function chartGrid(n: number, width: number, minWidth = 320, gap = 16): GridLayout {
  if (n <= 0) return { cols: 1, lastSpan: 1 };
  const fit = Math.max(1, Math.floor((width + gap) / (minWidth + gap)));
  const rows = Math.ceil(n / Math.min(fit, n));
  const cols = Math.ceil(n / rows);
  return { cols, lastSpan: cols * rows - n + 1 };
}
