# Phase 5 report: professional redesign, fixes, dashboard controls

Unattended run on 23-24 Oct 2026. Backend always started with `MHM_SOURCE=simulator`
(no serial port was listed or opened). Sections are added as each part is committed.

## Part A: professional redesign

### What changed visually
- **ISA-101 approach:** the page is neutral grey/white (light) or charcoal (dark) while
  everything is normal. Colour appears only for abnormal states: a normal state shows
  neutral text with a small muted-green icon; sensor cards get a 4 px amber/red left bar
  only when that sensor is at warning/critical or has a fault.
- **Palette as tokens** (`dashboard/src/styles.css`, top of file): `--bg`, `--surface`,
  `--surface-2`, `--border`, `--text`, `--muted`, `--grid`, `--accent`, `--accent-text`,
  limit-line colours, and separate status tokens `--st-normal / --st-warning /
  --st-critical / --st-ml` (each with a `-text` variant for words on a surface).
  Spacing (`--s1..--s5`, 8 px grid) and the type scale (`--t-xs..--t-xxl` =
  12/14/16/20/28/40) are tokens too.
- **Status banner:** normal = calm surface, 6 px muted-green left bar, check icon. Warning =
  amber tint + 8 px amber bar + triangle icon. ML-only warning = the same treatment in the
  ML colour (muted indigo `#5b63b0` / `#9aa3e3`, not neon purple) so it reads differently
  from a rule limit. Critical = solid muted red (`#a8301f` light, `#9c3029` dark) with white
  text; the only filled banner.
- **Mode badge:** flat, 1 px outline, small dot (live = filled teal, recorded = teal ring,
  simulated = grey ring), always visible. The striped/gradient SIMULATED badge is gone.
- **Typography:** Inter bundled via `@fontsource/inter` (400/500/600; offline). Sentence-case
  headings, no letter-spaced ALL CAPS (only the LIVE/RECORDED/SIMULATED badge text stays
  upper case, as asked). State labels are sentence case ("Normal", "Warning", "Critical",
  "Anomaly", "Warming up"). Tabular numerals on every value.
- **Fewer pills/chips:** state pills, the "Source: Both" chip and the dashed provisional tag
  were replaced by plain text lines ("Critical · raised by Both", "provisional model").
- **Icons:** one set, `lucide-react`, at 16 / 20 / 32 px only (`components/Icon.tsx`). No
  emoji. The old hand-drawn SVG icons are gone.
- **Surfaces:** 1 px borders, 6 px radius, no glows, no gradients, no shadows.
- **Charts:** every chart uses the same style: 1.5 px teal line, faint horizontal gridlines
  only, muted grey dashed limit lines (warn short dash, crit long dash) labelled at the
  right edge ("warn 32", "crit 35").
- **Header:** "Machine Health Monitor" with "BCSE305L Embedded Systems" as subtitle; mode
  badge, connection (dot + text) and an icon-only theme toggle on the right.
- **Chart grid** (done here, listed under B7 too): `lib/grid.ts` picks as many columns as
  fit, balances the rows and stretches the last (health) chart over empty cells. 1920 px:
  4 sensor charts + health in one row; 1366 px: 3 + 2 with health spanning two columns.

### Contrast (WCAG AA) and the adjustments made
`node dashboard/scripts/contrast.mjs` checks 21 token pairs per theme (text 4.5:1, UI
marks 3:1); all pass. Adjustments to the given palette:

| Given colour | Problem | Adjustment |
|---|---|---|
| `#00ADB5` as light-theme accent | 2.75:1 on white, 2.37:1 on `#EEEEEE` | chart lines/focus `#00838a` (4.55:1 on white); teal text and primary buttons `#00747a` (4.79:1 on `#EEEEEE`) |
| `#00ADB5` as text on a dark surface | 3.92:1 on `#393E46` (fails text) | kept for lines (4.64:1 on the surface `#2d333b`); teal text uses `#3cc7ce` (6.22:1) |
| `#393E46` as the dark card surface | `#00ADB5` lines and muted text were too weak on it | cards use a darker step `#2d333b`; `#393E46` is kept for inset/hover surfaces (`--surface-2`) |
| `#EEEEEE` text on `#393E46` | 9.28:1, fine | unchanged |
| `#222831` text on `#EEEEEE` | 12.78:1, fine | unchanged |
| muted text | none given | `#5a616b` light (≥ 5.5:1), `#b3b9c1` dark (≥ 5.6:1) |

### Results
- `npm run typecheck`: clean. `npm run build`: clean.
- Vitest: 38 passed (34 before + 4 new `grid.test.ts`). Format tests updated for the
  sentence-case state labels (spec change, not a code bug).
- Backend pytest: 287 passed (unchanged in this part).
