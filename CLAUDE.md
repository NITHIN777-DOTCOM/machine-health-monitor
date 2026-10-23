# Predictive Machine Health Monitor: project context

Embedded Systems course project (BCSE305L). **Teammates who didn't build it will present it**,
so docs and UI text must be clear to a newcomer.

## Architecture (two tiers)
- **Device tier** (must work with no laptop): Arduino Uno reads sensors, applies threshold
  rules → `dev_state`, drives buzzer (D8) and 16x2 I2C LCD (0x27). Sends one CSV line/s over
  USB serial at 115200.
- **Laptop tier** (offline, portable later: one folder, start.bat, PyInstaller .exe):
  FastAPI backend (serial/simulator/replay → device-rule mirror → ML + forecast → WebSocket)
  → React + TypeScript dashboard (`dashboard/`, Vite dev server proxies to the API).

## Repo map
| Path | Contents |
|---|---|
| `docs/DATA_CONTRACT.md` | **Source of truth**: serial format, empty-field rule, dev_state state machine (§3, mermaid diagram + worked example), stored columns, registry, deployment note (§8), live analysis (§9) |
| `backend/config/sensors.json` | Sensor registry, the ONLY sensor list (schema_version 2) |
| `backend/config/settings.json` | Runtime settings (hold_seconds, ML window, forecast, smoothing, warmstart_file) |
| `backend/config/sim_profile.json` | Simulator baselines + scenarios |
| `backend/app/` | `main.py` (API), `pipeline.py`, `analysis.py` (live ML/overall/headline), `device_rules.py`, `registry.py`, `models.py`, `recorder.py`, `state.py`, `sources/` (simulator, serial_source, replay), `ml/` (features, training, scorer, forecast, evaluation, dataset, jobs) |
| `backend/scripts/` | `ws_peek.py`, `generate_synthetic.py`, `train.py`, `evaluate.py`, `run_tests.bat` |
| `backend/tests/` | pytest suite (287 tests), `helpers.py`, `conftest.py` |
| `dashboard/` | Vite + React 19 + TS (strict) + Recharts. `src/types.ts` mirrors the backend JSON; `src/lib/` pure helpers (Vitest); `scripts/screenshots.mjs` (Playwright, project-local Chromium). See `dashboard/README.md` |
| `docs/screenshots/phase4/` | Review screenshots (committed) |
| `firmware/` | `README.md` (pin map, libraries, upload), `machine_monitor/` (sketch not written yet) |
| `data/recordings/` | Real recordings (committed). `data/synthetic/` is gitignored, regenerate it |
| `models/` | `model.joblib` + `model_meta.json` (committed, PROVISIONAL) |
| `docs/eval/` | Eval reports; `*_SIMULATED.md` are gitignored |

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
`npm run build`, `npm run screenshots` (backend in simulator mode + dev server running).
- Switch source: `POST /api/source {"type":"simulator","scenario":"recovery","speed":5}`. Scenarios:
  normal, sudden_fault, slow_drift, sensor_fault, recovery, drift_and_recover. Also `serial`,
  `replay {file, speed, loop}`, optional `warmstart: <recording>`.
- **Use `127.0.0.1`, not `localhost`** (WebSocket clients hang on IPv6 `::1` on this machine).
- With the Uno plugged in, startup picks serial. **`MHM_SOURCE=simulator`** forces the simulator and never
  lists/opens a serial port (switching to serial returns 400). Use it whenever someone else is using COM5.
- Port order: `MHM_PORT` > auto-detect (VID 0x2341, then CH340/USB-SERIAL names) > settings.json.
- Only one program may open the COM port (close the IDE Serial Monitor). Dev board: genuine Uno on COM5.
- Bash heredocs with nested Python quotes break in this shell: write patch scripts to a file first.

## Data contract essentials
- Columns, fixed order: `ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state`.
  Header line starts with `#`; `#` lines are comments. Missing/disabled/failed sensor = **empty field**, never 0/-1.
- Stored rows: `ts_iso` + 10 device columns + `mode,source,label` (live/recorded/simulated, real/synthetic,
  normal/fault/unknown). Recorder stores raw contract rows only (never the analysis).
- Windows and replay timing use the **device ms clock**, not wall time.

## Key rules and decisions
- **sensors.json is the only sensor list.** Nothing may hard-code sensors. Adding/removing an
  optional sensor = firmware `USE_<SENSOR>` flag + registry `enabled`, no code change.
- Core sensors: DHT11 (temp_c, humidity on A0), sound (A2), SW-420 vibration (D2). Optional, currently
  `enabled: false`: leak (A1), HC-SR04 (D9/D10), INA219 (`group: ina219` → current_ma + bus_v toggle together;
  a mismatched group is disabled with a warning).
- ML sensors = `enabled AND include_in_ml`; current_ma/bus_v are excluded. `forecast: true` only for
  temp_c and humidity (sound/vibration are spiky).
- **Demo limits are provisional** (`limits_note`, retune in Phase 8): temp 32/35, humidity 80/90,
  sound 40/120, vibration 20/60, all direction "above". Optional sensors TBD.
- dev_state: escalation immediate; de-escalation needs value clear by `hysteresis`
  (temp 0.5, hum 3, sound 10, vib 5) for **hold_seconds = 5** consecutive rows, one level at a time.
  An enabled core sensor empty → at least WARNING. A test parses the worked example in DATA_CONTRACT.md.
- **ML is advisory:** an ANOMALY can raise overall to WARNING, **never CRITICAL**; only rules make CRITICAL.
  ML smoothing: ANOMALY after health < 50 for 3 rows, clears after > 60 for 5 rows.
  Statuses: OK, ANOMALY, WARMING_UP, ML_UNAVAILABLE, NO_MODEL, NEEDS_RETRAIN (sensor list changed; rules keep working).
- Health: IsolationForest score calibrated (100 at median normal, 50 at threshold, 0 below) minus a
  range-excess term (−50 per 3 std beyond the training min/max; IF alone saturates outside its range).
- **Data rules (enforced in code):** train on `label=normal` only; synthetic data for training only (→ model
  `provisional: true`); **no accuracy numbers without real recordings with induced, labelled faults**:
  evaluate.py refuses otherwise, and `--dev-synthetic` output is stamped "SIMULATED DATA - NOT A RESULT".
  Eval false alarms exclude a 15 s margin (window + hold) after each fault; the raw rate is reported too.
- **The current model is provisional** (synthetic only). **Deploying on a real machine needs that machine's
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
  `MHM_SOURCE`).
- Next: **5 extras** (Record/Stop, Replay, scenario and source buttons in the dashboard), 6 portability (start.bat, PyInstaller, offline), 7 firmware, 8 real data + retrain + retune limits,
  9 release + docs.

## Known open items
- Dashboard "recovering" rule (done in Phase 4, `dashboard/src/lib/format.ts`): the banner says "Recovering"
  only when `hold_remaining_s <= hold_seconds - 2` (and says "rules clear ...; ML anomaly still active" if ML
  still flags it); otherwise it strips the backend's "recovering, was:" prefix. The device card shows the hold countdown quietly.
- Phase 7 firmware must copy `backend/app/device_rules.py` exactly (hysteresis, 5 s hold, one level at a time,
  core-sensor fault → WARNING, LCD reason text), print the contract header, and use `USE_<SENSOR>` flags.
  Until then the backend mirror may disagree with the device (`analysis.device.agrees`).
- The sketch currently on the Uno is an I2C scanner at 9600 baud (no contract data yet).
- Optional sensors (leak, HC-SR04, INA219) are untested; their limits are TBD.
