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

## Part B: health curve, plain-language causes, forecast fixes

### B1 Health score degrades gradually (backend `app/ml/scorer.py`, `training.py`)
Old: `health = 50 + 50·r − 50·excess/3`, clamped (r = calibrated IF score). Two problems:
the IF part went to 0 just one "normal spread" below the threshold, and the range term cost
50 points per 3 std, so any vibration ≥ 8 /s scored 0.

New: `health = min(IF part, range part)`:
- IF part: unchanged above the threshold (100 at the median normal window, 50 at the
  threshold); below it a soft decay `50 / (1 − r)` (25 at one spread below, 12.5 at three).
- Range part: `100 − 16.7·ln(1 + excess / 0.28)`, clamped 0..100.

Old vs new score for example windows (other sensors normal, provisional model):

| Window | excess (std) | old | new |
|---|---|---|---|
| normal | 0 | 100 | 100 |
| temperature 31.5 °C | 1.4 | 71.5 | 70.2 |
| temperature 32.5 °C | 2.6 | 51.3 | 61.1 |
| temperature 35 °C | 6.0 | 0 | 48.0 |
| humidity 85 % | 3.4 | 31.3 | 57.1 |
| vibration 8 /s | 6.4 | 0 | 43.8 |
| **vibration 13 /s** (training range 0–6) | 13.8 | **0** | **34.6** |
| vibration 20 /s | 24.1 | 0 | 25.4 |
| vibration 30 /s | 38.8 | 0 | 17.5 |
| sound 25 | 22.1 | 0 | 26.9 |
| vibration 64 /s | 88.7 | 0 | 3.8 |
| vibration 120 /s / sound 140 | 160+ | 0 | 0 |

- The model was **not retrained**: the IsolationForest and its calibration (median /
  threshold) are unchanged, only the post-processing changed. `models/model_meta.json` got
  the new `calibration.rule` text and `range_excess: {k: 16.7, b: 0.28, rule}` (replacing
  `stds_per_50_health`). `training.py` writes the same block for future models. The model
  stays `provisional: true`.
- Side effect (accepted): ML now flags a slow temperature rise a little later (health
  crosses 50 at about 35 °C instead of about 32.6 °C). The rules still warn at 32 °C.
- Tests: `test_health_calibration_anchor_points` (spec change: 25 instead of 0 one spread
  below the threshold), `test_range_excess_lowers_health_gradually` (replaces the old
  linear test), new `test_health_is_the_worse_of_both_parts`, `test_vibration_13_is_a_mid_score`.

### B2 Causes in plain words
- Backend: each cause now has `band` and plain `text` ("Vibration: far above normal").
  Bands of |z|: < 2 normal, 2–3 slight, 3–6 clear, ≥ 6 far; words per statistic
  (level: slightly high / above normal / far above normal; std: slightly unstable /
  unstable / very unstable; slope: rising slightly / rising / rising fast; and the
  low/falling counterparts). Documented in DATA_CONTRACT §9.
- Dashboard: `causeWords()` / `causeText()` (same table) and `causeTooltip()`; z appears
  only in the tooltip, and |z| ≥ 10 is shown as "more than 10 standard deviations", so a
  capped 99 is never displayed. Causes with |z| < 2 are not listed ("Nothing unusual").

### B3 Short human headlines
`analysis.headline` is now short and `analysis.headline_detail` (new field) holds the exact
values on a smaller second line. Examples (all seen live or in tests):
"Sound level above critical limit" / "Sound level 185, crit limit 120 · ML anomaly (health 0)";
"Sensor fault: DHT11" / "DHT11: no reading"; "Unusual vibration pattern (health 0)" /
"Vibration: far above normal"; "Temperature may reach warning in ~2 min";
"All systems normal" / "Health 98". Headline tests in `test_pipeline_analysis.py` were
updated to the new wording (spec change).

### B4 Forecast confidence
"fit R² 0.63" is replaced by "rising · confidence: medium". Bands: R² < 0.6 low (below the
backend's `forecast_min_r2`, the trend is not trusted), 0.6–0.85 medium, ≥ 0.85 high. R² is in
the tooltip. A forecast with no trusted trend says "no clear trend".

### B5 Forecast "No data"
`forecast_sensor()` returns `status: "no_data"` (text "Temperature: no data") as soon as the
newest row has no value for the sensor, instead of "stable" from old readings. Tests:
`test_missing_newest_value_says_no_data`, `test_forecast_comes_back_when_values_return`, and
a check in `test_ml_unavailable_on_sensor_fault` that the first missing row already says
no_data.

### B6 ML thresholds from the API
`GET /api/status` and `GET /api/model` include `ml_thresholds` (`anomaly_health` 50,
`anomaly_rows` 3, `clear_health` 60, `clear_rows` 5, from settings.json). The dashboard uses
them for the health bands, the threshold mark on the health bar and the chart lines
("clear 60", "anomaly 50"); the old hard-coded 50/60 are only a fallback before the first
status arrives. Test: `test_ml_thresholds_in_status_and_model`.
Also added for Part C: `serial: {available, port, note}` in `/api/status` (tests
`test_serial_availability_is_reported`, `test_serial_unavailable_when_forced_to_simulator`).

### B7 Trend layout
Done in Part A (`lib/grid.ts`): the health chart is in the same grid as the sensor charts;
1920 px shows all five in one row, 1366 px shows 3 + 2 with the health chart spanning two
columns, so no row has empty space.

### B8 package-lock.json
`dashboard/package-lock.json` is committed (it already was; updated with the new
dependencies `lucide-react` and `@fontsource/inter` in the Part A commit).

### Results
- Backend pytest: **297 passed** (287 before; +10 new tests).
- Vitest: **46 passed**. `tsc --noEmit` and `npm run build` clean. Contrast check passes.
