# Predictive Machine Health Monitor: project context

Embedded Systems course project (BCSE305L). **Teammates who didn't build it will present it**,
so docs and UI text must be clear to a newcomer.

## Architecture (two tiers)
- **Device tier** (must work with no laptop): Arduino Uno reads sensors, applies threshold
  rules → `dev_state`, drives buzzer (D8) and 16x2 I2C LCD (0x27). Sends one CSV line/s over
  USB serial at 115200.
- **Laptop tier** (offline, portable: one folder with `MachineHealthMonitor.exe` + `Start.bat`, PyInstaller onedir):
  FastAPI backend (serial/simulator/replay → device-rule mirror → ML + forecast → WebSocket)
  → React + TypeScript dashboard (`dashboard/`), served by FastAPI at `/` from `dashboard/dist`
  (in dev the Vite dev server on :5173 proxies to the API).

## Repo map
| Path | Contents |
|---|---|
| `docs/DATA_CONTRACT.md` | **Source of truth**: serial format, empty-field rule, dev_state state machine (§3, mermaid diagram + worked example), stored columns, registry, deployment note (§8), live analysis (§9) |
| `backend/config/sensors.json` | Sensor registry, the ONLY sensor list (schema_version 2) |
| `backend/config/settings.json` | Runtime settings (hold_seconds, ML window, forecast, smoothing, warmstart_file) |
| `backend/config/sim_profile.json` | Simulator baselines + scenarios |
| `backend/app/` | `main.py` (API + dashboard at `/`), `launcher.py` (exe entry), `paths.py` (frozen vs repo paths), `version.py`, `pipeline.py`, `analysis.py` (live ML/overall/headline), `device_rules.py`, `registry.py`, `models.py`, `recorder.py`, `state.py`, `sources/` (simulator, serial_source, replay), `ml/` (features, training, scorer, forecast, evaluation, dataset, jobs) |
| `backend/scripts/` | `ws_peek.py`, `generate_synthetic.py`, `make_demo_recording.py`, `train.py`, `evaluate.py`, `gen_firmware_config.py` (sensors.json + settings.json → `config_generated.h`), `firmware_parity.py` (board vs device_rules.py), `run_tests.bat` |
| `backend/tests/` | pytest suite (364 tests), `helpers.py`, `conftest.py` |
| `build.bat`, `packaging/` | Portable build: `MachineHealthMonitor.spec` (onedir), `build_release.py` (version.json, assemble + zip), `Start.bat`, `Start (simulator only).bat`, `QUICK_START.txt`. `backend/mhm_entry.py` = PyInstaller stub, `backend/requirements-build.txt` pins PyInstaller |
| `release/`, `build_test/`, `logs/`, `data/demo/` | Build output, portability-test copies, runtime logs, generated demo recording (all gitignored) |
| `dashboard/` | Vite + React 19 + TS (strict) + Recharts. `src/types.ts` mirrors the backend JSON; `src/lib/` pure helpers (Vitest); `scripts/screenshots.mjs` (Playwright, project-local Chromium). See `dashboard/README.md` |
| `docs/screenshots/phase5/` | Review screenshots (committed; `npm run screenshots`) |
| `docs/phase5_report.md` | Phase 5 report (redesign, health curve, controls, decisions) |
| `docs/phase8_report.md` | Phase 8.2 report (real-data model, selection rule, calibration, held-out evaluation, limit suggestions) |
| `firmware/` | `README.md` (pins, defines, LCD/buzzer, watchdog, parity, memory, libraries), `machine_monitor/` (v1.0.2: `.ino`, `config_generated.h` GENERATED, `state_machine.h`, `display.h`, `buzzer.h`), `tests/` (single-sensor sketches, `RESULTS.md`, `HIL_RESULTS.md` = Phase 7.2 bench test), `build/` (gitignored) |
| `data/recordings/` | Real recordings (committed), roles in `MANIFEST.json` (test: `test_recordings_manifest.py`), protocol + label rules in `README.md`: `real_session_01_20261024.csv` = **train** (Phase 7.2 HIL, 3408 rows, 868 normal / 686 fault / 1854 unknown), `real_session_02_test_20261024.csv` = **test, held out** (Phase 8.1, 1993 rows, 921 / 246 / 826, incl. subtle below-limit vibration + sound). `data/synthetic/` is gitignored, regenerate it |
| `models/` | `model.joblib` + `model_meta.json` (committed; bench-trained on session 01, `provisional: false`) |
| `docs/eval/` | Eval reports; `*_SIMULATED.md` are gitignored. `eval_real_session_02.md/.json` = held-out test result (JSON bundled in the exe, `GET /api/model/evaluation`, dashboard Model panel); `phase8_validation.json`, `phase8_b4_review.json` = model selection |

## Commands (Windows; from `backend/`, venv at `backend/venv`)
```
python -m venv venv && venv\Scripts\pip install -r requirements.txt   # once
venv\Scripts\python -m uvicorn app.main:app --reload                  # API on http://127.0.0.1:8000, /docs
scripts\run_tests.bat            # pytest + coverage (or: venv\Scripts\python -m pytest -q)
venv\Scripts\python scripts\ws_peek.py --changes --headlines -n 40
venv\Scripts\python scripts\generate_synthetic.py      # 60 min normal + dev fault set
venv\Scripts\python scripts\train.py "../data/synthetic/normal_*.csv"
venv\Scripts\python scripts\evaluate.py --dev-synthetic "../data/synthetic/devfault_*.csv"
```
Dashboard (from `dashboard/`): `npm install` once, `npm run dev` (http://127.0.0.1:5173), `npm test`,
`npm run build`, `npm run screenshots` (backend in simulator mode + dev server running; `npm ci`
deletes the local Chromium, re-run `npm run screenshots:install`).
Portable (from the repo root): `build.bat` → `release\MachineHealthMonitor\` + `release\MachineHealthMonitor-v<ver>-win64.zip`
(~4 min: npm ci/test/build, pytest, PyInstaller, assemble). Run the launcher from source:
`venv\Scripts\python -m app.launcher [--simulator] [--port N] [--no-browser]` (from `backend/`).
Version number: `VERSION` in `backend/app/version.py` (bump it per release).
- Switch source: `POST /api/source {"type":"simulator","scenario":"recovery","speed":5}`. Scenarios:
  normal, sudden_fault, slow_drift, sensor_fault, recovery, drift_and_recover. Also `serial`,
  `replay {file, speed, loop}`, optional `warmstart: <recording>`.
- **Use `127.0.0.1`, not `localhost`** (WebSocket clients hang on IPv6 `::1` on this machine).
- With the Uno plugged in, startup picks serial. **`MHM_SOURCE=simulator`** forces the simulator and never
  lists/opens a serial port (switching to serial returns 400). Use it whenever someone else is using COM5.
- Port order: `MHM_PORT` > auto-detect (VID 0x2341, then CH340/USB-SERIAL names) > settings.json.
- Only one program may open the COM port (close the IDE Serial Monitor). Dev board: genuine Uno on COM5.
- Bash heredocs with nested Python quotes break in this shell: write patch scripts to a file first.
- This shell sets `NoDefaultCurrentDirectoryInExePath=1`: run `.bat` files by absolute path
  (`cmd /c "C:/full/path/to/build.bat"`), a bare `build.bat` is "not recognized".

## Data contract essentials
- Columns, fixed order: `ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state`.
  Header line starts with `#`; `#` lines are comments. Missing/disabled/failed sensor = **empty field**, never 0/-1.
- Stored rows: `ts_iso` + 10 device columns + `mode,source,label` (live/recorded/simulated, real/synthetic,
  normal/fault/unknown). Recorder stores raw contract rows only (never the analysis).
- Windows and replay timing use the **device ms clock**, not wall time.

## Paths rule (Phase 6)
- **No absolute paths and no `__file__`-relative paths outside `backend/app/paths.py`.** Read-only bundled
  resources (dashboard dist, default config, shipped model, version.json) come from `paths.BUNDLE_DIR`
  (`sys._MEIPASS` frozen, repo in dev); writable files (config, models, data/recordings, data/demo, logs)
  from `paths.APP_DIR` (next to the exe frozen, repo in dev). New files must go through `paths.py`.
- Recordings are looked up in `settings.recording_dirs` (data/recordings, then data/demo).
- New runtime dependencies may need a `hiddenimports` entry in `packaging/MachineHealthMonitor.spec`;
  pandas is excluded from the exe (nothing in `app/` imports it). Re-run the portability test after changes.

## Key rules and decisions
- **sensors.json is the only sensor list.** Nothing may hard-code sensors. Adding/removing an
  optional sensor = firmware `USE_<SENSOR>` flag + registry `enabled`, no code change.
- Core sensors: DHT11 (temp_c, humidity on A0), sound (A2), SW-420 vibration (D2). Optional: leak (A1) and
  HC-SR04 (D9/D10) **enabled** (Phase 7.1); INA219 `enabled: false` (not fitted; `group: ina219` → current_ma +
  bus_v toggle together; a mismatched group is disabled with a warning).
- ML sensors = `enabled AND include_in_ml` = the 4 core values only (leak/distance are rule-only events,
  current_ma/bus_v excluded), so the shipped model still matches (test). Per-sensor `ml_stats` (Phase 8.2):
  temp_c and humidity enter ML by std + slope only (their level drifts with the room) → 16 features; a model
  whose features don't match → NEEDS_RETRAIN. `forecast: true` only for temp_c (humidity has no limits).
- **Demo limits are provisional** (`limits_note`; Phase 8.2 suggestions are report-only, `docs/phase8_report.md` §5): temp 32/35, sound 40/120,
  vibration 50/100 (h 10, bench-calibrated in 7.2), leak 50/200 (h 20), all "above"; **humidity has no
  rule limits** (Chennai room ~80 %RH, DHT11 tops out at 90; still shown and in ML); **distance_cm = safety zone, "below"
  20/10 (h 3)**. HC-SR04 no echo = **400** (nothing in range, clear; `out_of_range_value`, dashboard
  "> 400 cm (clear)"); empty distance = sensor fault.
- **Limits are single-source:** sensors.json/settings.json → `scripts/gen_firmware_config.py` →
  `firmware/machine_monitor/config_generated.h` (also `USE_<SENSOR>` from `firmware_flag`, LCD names from
  `lcd_name`). Re-run it after any limit/enabled change; `test_firmware_config.py` fails while it's stale.
- dev_state: escalation immediate; de-escalation needs value clear by `hysteresis`
  (temp 0.5, sound 10, vib 10, leak 20, dist 3) for **hold_seconds = 5** consecutive rows, one level at a
  time. An enabled core sensor empty → at least WARNING. Tests parse both worked examples in DATA_CONTRACT.md
  (temp above, distance below); `firmware_parity.py` checks the board against them (71/71 on 2026-10-24).
- **ML is advisory:** an ANOMALY can raise overall to WARNING, **never CRITICAL**; only rules make CRITICAL.
  ML smoothing: ANOMALY after health < 50 for 3 rows, clears after > 60 for 5 rows.
  Statuses: OK, ANOMALY, WARMING_UP, ML_UNAVAILABLE, NO_MODEL, NEEDS_RETRAIN (sensor list changed; rules keep working).
- Health (Phase 5): min(IF part, range part). IF part 100 at median normal, 50 at threshold, soft decay
  50/(1−r) below; range part 100 − 16.7·ln(1 + excess/0.28) (excess = std beyond training min/max). Vibration 13
  → ~35, extreme → 0. Causes are plain words by |z| band (<2 normal, 2–3 slight, 3–6 clear, ≥6 far).
  Headline is short + `headline_detail` with values. Forecast `no_data` when the newest value is missing.
  `ml_thresholds`, `serial` {available, note} and `version` are in /api/status. Per sensor an unusual level
  feature beats a larger std/slope z in the causes ("far above normal" over "very unstable"); the dashboard
  lists causes only while ML is ANOMALY or health ≤ clear level, else "Nothing unusual".
- **Data rules (enforced in code):** sessions with role `test` in `data/recordings/MANIFEST.json` are never used for
  training or tuning (`app/ml/roles.py`: train.py takes only `train` sessions, evaluate.py refuses `train` files except
  `--validation`; matched by name and sha256, raw variants inherit the role); train on `label=normal` only; synthetic data for training only (→ model
  `provisional: true`); **no accuracy numbers without real recordings with induced, labelled faults**:
  evaluate.py refuses otherwise, and `--dev-synthetic` output is stamped "SIMULATED DATA - NOT A RESULT".
  Eval false alarms exclude a 15 s margin (window + hold) after each fault; the raw rate is reported too.
- **The current model is bench-trained** (session 01 real normal rows, chosen by `scripts/select_model.py`'s pre-stated
  rule, tested once on session 02). **Deploying on a real machine needs that machine's
  own normal data, re-derived limits and a retrained model** (DATA_CONTRACT §8).
- Warm start: the first W live rows show ML "settling" (no health, no escalation) because the window
  mixes recorded and live data.

## Conventions
- Temp files only in the repo or the session scratchpad, **never Desktop or other folders**.
- Commit messages: `Phase X.Y: <summary>`; commit and **push after each phase**. End commits with the
  Co-Authored-By line from the session's attribution instructions.
- **Fix code, not tests.** Only change a test when its expectation was wrong or the spec changed, and say so.
- Delete test recordings after live checks (`data/recordings/` should hold real data only).
- Keep docs (DATA_CONTRACT, READMEs) in sync with code in the same commit.

## Phase status
- Done: 1 (scaffold, contract, registry) → 2.x (backend core, sources, recorder, hysteresis, tests)
  → 3.1 (ML engine offline) → 3.2 (live ML pipeline, warm start, model API) → 4 (lean dashboard,
  `MHM_SOURCE`) → 5 (ISA-101 redesign, gradual health curve, plain-language text, Controls drawer:
  source/scenario/speed, Record/Stop + label, Replay with progress, warm start) → 6 (portable onedir exe,
  launcher, FastAPI serves the dashboard, paths.py, build.bat, demo recording, GitHub release v0.6.0).
  → 7.1 (final firmware v1.0.0, generated config, parity test, leak + safety zone enabled, dashboard
  silent vs wrong-format notice) → 7.2 (hardware-in-the-loop test, first real recording, passive
  buzzer `tone()` + sound blanking = firmware v1.0.2, vibration 50/100, humidity without limits,
  mirror reset on device restart; `firmware/tests/HIL_RESULTS.md`) → 8.1 (held-out real test session 02,
  `data/recordings/MANIFEST.json` roles) → 8.2 (raw recordings + roles in code, `ml_stats`, bench-trained model,
  held-out evaluation, dashboard Model panel, sim profile like the bench, release v0.8.0; `docs/phase8_report.md`).
- Next: 9 final release + docs (limit retune is a team decision: suggestions in phase8_report §5).

## Known open items
- Dashboard "recovering" rule (done in Phase 4, `dashboard/src/lib/format.ts`): the banner says "Recovering"
  only when `hold_remaining_s <= hold_seconds - 2` (and says "rules clear ...; ML anomaly still active" if ML
  still flags it); otherwise it strips the backend's "recovering, was:" prefix. The device card shows the hold countdown quietly.
- `machine_monitor` v1.0.2 is on the Uno. HIL 2026-10-24: rows_rejected 0; `agrees` false only on 15 rows right
  after reconnects (mirror now resets when the device clock goes backwards).
- **The buzzer is passive** (`BUZZER_PASSIVE 1`, `tone()` 2.5 kHz, Timer2). Silent = pin INPUT (driving D8 LOW
  shifted analog readings ~20 counts). The mic hears it, so sound samples are blanked while it sounds + 50 ms.
- **Demo: tap the vibration sensor itself, not the table** (a knock is also loud and shakes the breadboard);
  reach from the side, not over the HC-SR04. Loose 5V/GND jumpers caused USB drops + LCD garbage on the bench.
- ML false alarms on bench normal rows are 5-14 % (rules 0-6 %), partly from DHT11 0.1 °C steps; the forecast also
  fires on those steps (114 of 1736 rows in session 02) and on the simulator's temperature wander.
- Phase 8.2 live check with the board (optional part E) was skipped.
- The exe is unsigned: SmartScreen "More info → Run anyway" on first start (documented in QUICK_START.txt).
- Portability test not yet done with the Arduino plugged in (exe auto-detection of the Uno unverified).
- INA219 untested (not fitted; the `USE_INA219 1` build compiles). `LEAK_POWER_PIN` option untested.
