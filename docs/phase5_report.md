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

## Part C: dashboard controls and screenshots

### What was added
A **Controls** button in the top bar opens a right-hand drawer (`components/ControlsPanel.tsx`);
the main view is unchanged while it is closed. Below 1100 px wide the drawer overlays the
page instead of squeezing it.

1. **Source switcher** Live (Arduino) / Simulated / Recorded (`POST /api/source`). Live is
   disabled with the backend's reason when `status.serial.available` is false; with
   `MHM_SOURCE=simulator` it says "Serial disabled (MHM_SOURCE=simulator). Unset it and
   restart to use the Arduino." Without the env var, "No Arduino found ..." (ports are
   checked at most every 5 s, never with `MHM_SOURCE=simulator`).
2. **Scenarios** Normal, Sudden fault, Slow drift, Recovery, Sensor fault (only those the
   backend lists), speed 1x / 5x / 10x, and **Fast-forward drift** (slow drift at 10x). The
   active scenario and speed are highlighted.
3. **Record / Stop** with elapsed time and row count in the panel and a blinking **REC
   0:09 · 42 rows** indicator in the top bar (visible with the panel closed; the blink
   stops with `prefers-reduced-motion`). **Label** toggle Normal / Fault / None
   (`POST /api/label`) showing the current label.
4. **Replay**: recordings from `/api/recordings` (name, duration, rows, date), speed
   1x / 5x / 10x, loop, Play, progress bar ("44 / 90 rows · 49%", "pass 3" when looping).
5. **Start from recording**: choose a file → `POST /api/warmstart`.
6. **Errors inline** at the top of the panel, in plain words (e.g. "Port busy: close the
   Arduino IDE Serial Monitor (or any other program using the port)."); the serial source's
   `last_error` (busy port) is shown there too. One request at a time: every button is
   disabled while a request is in flight.

### Backend changes for Part C
- `ReplaySource.status()`: `rows_total`, `passes`, `progress` (0..1, current pass);
  `/api/status` has a top-level `progress`.
- `/api/recordings`: new `modified` (ISO time); `duration_s` now uses the **device clock**
  first (what a 1x replay takes; a 5x simulated recording was shown 5x too short before),
  then wall-clock `ts_iso`.
- The pipeline pushes a status message **once a second while recording or replaying**
  (before, status was only sent on events, so the row count and progress froze).
- (From Part B) `serial: {available, port, note}` in `/api/status`.

### Tests
- Vitest `src/lib/controls.test.ts` (9 tests): source mapping, Live enable/disable with
  the note, request bodies, scenario list/order, the in-flight reducer, API error wording
  (busy port, MHM_SOURCE, 404, 422, network), elapsed time, durations, replay progress.
- Backend: `test_replay_progress`, progress/rows_total/`modified` checks in the API
  round-trip test, `duration_s == 9.0` (device clock) in `test_list_recordings`.
- Not unit-tested (checked live instead): the once-a-second status push.

### Screenshots (`docs/screenshots/phase5/`, 40 files)
Each of `normal`, `sudden_fault`, `slow_drift`, `recovery`, `sensor_fault`, `recording`,
`controls`, `replay` at `1366x768_light`, `1366x768_dark`, `1920x1080_light`,
`1920x1080_dark`, plus `<state>_full_1366_light.png` (full page). Taken with
`npm run screenshots` (backend with `MHM_SOURCE=simulator`). The script makes one
recording for the replay shots and deletes it at the end; `data/recordings/` holds only
`.gitkeep`. `docs/screenshots/phase4/` was deleted.

### Results
- Backend pytest: **298 passed**. Vitest: **55 passed** (4 files). `tsc --noEmit` and
  `npm run build` clean. Contrast check: all pairs pass.

## Final summary

### Test and build results (final state)
| Check | Result |
|---|---|
| Backend `pytest` (`backend/`) | **298 passed**, 0 failed (287 at the start of Phase 5) |
| Dashboard Vitest (`npm test`) | **55 passed** in 4 files (34 at the start) |
| `npm run typecheck` | clean |
| `npm run build` | clean (one JS bundle ~570 kB, under the 800 kB warning limit set in Phase 4) |
| `node scripts/contrast.mjs` | all 42 token pairs pass WCAG AA (21 per theme) |

### Backend changes (all phases of this run)
- `app/ml/scorer.py`: new health curve (`if_health`, `range_health`, `min`), plain-language
  causes (`z_band`, `plain_words`, `short_name`; causes get `band` + new `text`).
- `app/ml/training.py`: writes the new `calibration.rule` and `range_excess {k, b, rule}`.
- `models/model_meta.json`: same two blocks updated; model **not retrained**, still provisional.
- `app/analysis.py`: short `headline` + new `headline_detail`.
- `app/ml/forecast.py`: `no_data` status when the newest value is missing.
- `app/pipeline.py`: `ml_thresholds`, `serial {available, port, note}`, `progress` in
  `/api/status`; `ml_thresholds` in `/api/model`; status push every second while
  recording or replaying.
- `app/sources/replay.py`: `rows_total`, `passes`, `progress`.
- `app/recorder.py`: `modified` per recording; duration from the device clock first.
- Docs kept in sync: `docs/DATA_CONTRACT.md` §9, `CLAUDE.md`, `dashboard/README.md`.

### Decisions I made on my own
1. **Dark card surface `#2d333b`** (a darker step of `#393E46`) so `#00ADB5` lines and muted
   text pass contrast; `#393E46` is used for inset/hover surfaces.
2. **Light-theme teal** `#00838a` (lines) and `#00747a` (text, primary button), derived from
   `#00ADB5`, because `#00ADB5` is only 2.75:1 on white.
3. **ML anomaly colour** muted indigo (`#5b63b0` light / `#9aa3e3` dark); a banner raised by
   ML alone uses it instead of amber, so it reads differently from a rule warning.
4. **Normal is neutral**: "Normal" text in the normal text colour with only a small green
   icon; sensor cards get a coloured bar only when abnormal. The health bar fill is grey
   while healthy and takes amber/indigo only at or below the clear level.
5. **Font: Inter** (not IBM Plex), weights 400/500/600 only.
6. State labels in sentence case ("Critical", "Warming up"); the mode badge stays
   LIVE / RECORDED / SIMULATED as specified.
7. **Health curve constants** k = 16.7, b = 0.28 chosen so vibration 13 lands at ~35, the
   warn limit (vibration 20) at ~25 and vibration ≥ 120 at 0; parts combined with `min`.
   Not retrained (unchanged model and calibration). Accepted side effect: ML flags a slow
   temperature rise later (~35 °C instead of ~32.6 °C); the rules still warn at 32 °C.
   `calibration.abnormal_score` is kept in the meta for reference; it now maps to 25, not 0.
8. **|z| bands** 2 / 3 / 6, implemented in both the backend (cause text, headline detail) and
   the dashboard (display, Vitest); the table is documented once in DATA_CONTRACT §9.
   Causes with |z| < 2 are hidden ("Nothing unusual").
9. **Confidence bands** R² 0.6 / 0.85 (0.6 = the backend's `forecast_min_r2`). A forecast with
   no trusted trend says "no clear trend" rather than "confidence: low".
10. **Headline wording** as in the DATA_CONTRACT table; the dashboard's Phase 4 "Recovering -
    ..." banner rule is unchanged.
11. **Chart grid**: last chart (health) stretches over empty cells instead of leaving a gap.
12. **Controls as a right-hand drawer**, side by side with the dashboard (overlay below 1100 px).
13. **Speed change restarts the running scenario** (the simulator has no live speed change);
    the panel says so.
14. The **Recorded** tab only shows the list; nothing switches until **Play**.
15. Added a **None** label option (`label: null`) next to Normal / Fault. The backend only
    applies the manual label to live (Arduino) rows; the panel says this rather than changing
    the backend's labelling rule.
16. **Start from recording** warm-starts the current source (`POST /api/warmstart`) rather than
    adding a "warm start on next switch" option.
17. **Serial availability** is reported by the backend (`status.serial`) so the dashboard
    never guesses; port listing is cached for 5 s and skipped entirely with `MHM_SOURCE=simulator`.
18. **Status push once a second** while recording/replaying (simplest way to keep the REC
    counter and progress live without changing the row message).
19. `duration_s` switched to the device clock first (consistent with replay timing).
20. The screenshot script makes and deletes its own recording for the replay shots.

### Skipped or failed
- Nothing skipped. No push failed.
- Not covered by an automated test: the once-a-second status push (verified live: the REC
  counter and replay progress advance in the screenshots).
- Known, accepted behaviour visible in screenshots: right after a fault starts, ML can show
  "OK" with a low health number for up to 2 rows (smoothing needs 3 rows below 50).
- Bash heredocs with nested quotes broke once (known shell issue from CLAUDE.md); I switched
  to patch scripts written to a scratch folder inside the repo (deleted at the end, never committed).

### Commits (all on `main`, pushed to `origin/main`)
| Part | Commit | Push |
|---|---|---|
| A | `cd0262f` Phase 5A: professional redesign | pushed |
| B | `cfdd1b6` Phase 5B: health curve, plain-language causes, forecast fixes | pushed |
| C | `adacbb0` Phase 5C: dashboard controls and screenshots | pushed |
| Report | "Phase 5: report" (this file; its hash is in `git log`) | see `git log origin/main` |
