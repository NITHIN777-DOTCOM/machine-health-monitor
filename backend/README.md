# Backend: FastAPI

Reads sensor rows from one of three **sources**, records them to CSV, and streams them
to the dashboard over WebSocket. Row format: [`../docs/DATA_CONTRACT.md`](../docs/DATA_CONTRACT.md).
The sensor list always comes from [`config/sensors.json`](config/sensors.json); no code
hard-codes it.

| Source      | What it does | Rows are marked |
|-------------|--------------|-----------------|
| `serial`    | Reads the Arduino over USB. Finds the port by itself, reconnects if the cable is unplugged. | `mode=live`, `source=real` |
| `simulator` | Generates realistic rows (1 per second, or 5x/10x faster) with fault scenarios. | `mode=simulated`, `source=synthetic` |
| `replay`    | Plays back a CSV from `data/recordings/`. | `mode=recorded`, original `source`/`label` |

On startup the backend uses `serial` if it finds an Arduino, otherwise the simulator in
the `normal` scenario. The log says which one it picked and why.

## Setup (once)

Needs Python 3.10+ (developed on 3.11). From the `backend/` folder:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

(On macOS/Linux: `source venv/bin/activate`.)

## Run

From `backend/`, with the venv activated:

```
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000. Interactive docs to try every endpoint: http://127.0.0.1:8000/docs
- WebSocket: `ws://127.0.0.1:8000/ws/stream`

**Close the Arduino IDE Serial Monitor first.** Only one program can use the COM port.
If it's open, `/api/status` shows `last_error: "COM5 busy, close Serial Monitor ..."`;
close it and the backend connects by itself within 2 seconds.

> Tip: on Windows, use `127.0.0.1` rather than `localhost`. `localhost` can resolve to
> IPv6 first, which some WebSocket clients don't fall back from.

## Switching sources

Use the dashboard, or the `/docs` page, or curl:

```
# simulator; scenario = normal | sudden_fault | slow_drift | sensor_fault; speed = 1, 5, 10
curl -X POST http://127.0.0.1:8000/api/source -H "Content-Type: application/json" -d "{\"type\":\"simulator\",\"scenario\":\"slow_drift\",\"speed\":10}"

# the real Arduino
curl -X POST http://127.0.0.1:8000/api/source -H "Content-Type: application/json" -d "{\"type\":\"serial\"}"

# replay a recording (names from GET /api/recordings), 5x speed, looping
curl -X POST http://127.0.0.1:8000/api/source -H "Content-Type: application/json" -d "{\"type\":\"replay\",\"file\":\"session_20261023_191704.csv\",\"speed\":5,\"loop\":true}"
```

### Simulator scenarios

Defined in [`config/sim_profile.json`](config/sim_profile.json) (baselines are guesses
until we have real recordings):

| Scenario       | What happens | Label |
|----------------|--------------|-------|
| `normal`       | Healthy baseline values. | `normal` |
| `sudden_fault` | At a random time 20–60 s in, vibration (+60) and sound (+120) jump past their limits → WARNING/CRITICAL. | `fault` after the jump |
| `slow_drift`   | From 10 s, temperature rises by +6 °C over 4 minutes (~29.5 → ~35.5 °C), crossing 32 °C (WARNING) then 35 °C (CRITICAL); vibration slowly rises. | `fault` after it starts |
| `sensor_fault` | At a random time 20–60 s in, the DHT11 stops responding (temp and humidity go empty → WARNING). | `unknown` after it starts (a dead sensor is not a machine fault, so ML must not learn it) |
| `recovery`     | Normal for 20 s, vibration and sound jump past critical for 30 s, then return to normal. Shows CRITICAL → WARNING → NORMAL with the hold countdown. **Best demo of the state machine.** | `fault` during the fault window, `normal` before and after |
| `drift_and_recover` | From 10 s, temperature drifts +7 °C over 2 min (past 32 and 35), stays hot 1 min, cools back over 2 min. | `fault` from the drift start until cooled |

Scenario timing is set per scenario in `sim_profile.json`: `start_s` (random range),
`ramp_s` (rise time), `duration_s` (time from start until recovery begins; omit to keep
the fault forever) and `recover_s` (fall time).

Disabled sensors (in `sensors.json`) are always empty, exactly like the real device.
All simulated values are clamped to each sensor's physical range (`physical_min` /
`physical_max`; the DHT11 is 0–50 °C and 20–90 %RH).
`dev_state` is computed by `app/device_rules.py`, the same rules as the Arduino:
escalation is immediate, and de-escalation needs the value clear of the limit by the
sensor's `hysteresis` for `hold_seconds` (settings.json, default 5) rows in a row.

## Recording and labelling

```
curl -X POST http://127.0.0.1:8000/api/record/start
curl -X POST http://127.0.0.1:8000/api/label -H "Content-Type: application/json" -d "{\"label\":\"fault\"}"
curl -X POST http://127.0.0.1:8000/api/record/stop
```

- Files go to `data/recordings/session_YYYYMMDD_HHMMSS.csv` (contract header, every row
  flushed to disk immediately).
- `/api/label` sets the label (`normal`, `fault`, `unknown`, or `null` to clear) for
  **live serial** rows. Use it while you induce a fault on the real machine. Simulator
  rows keep their scenario label and replayed rows keep their recorded label.

## Choosing the serial port: `MHM_PORT`

Normally you don't need this: the backend auto-detects the Arduino (genuine Uno by its
USB vendor ID, clones by "CH340" / "USB-SERIAL" in the name). The port is chosen in this
order:

1. **`MHM_PORT` environment variable**: if set, it **overrides** auto-detection.
2. **Auto-detection.**
3. **`"serial_port"` in [`config/settings.json`](config/settings.json)**: used only when
   `MHM_PORT` is not set and auto-detection finds nothing.

The log says which one was used (e.g. `Serial port: COM5 (MHM_PORT environment variable)`),
and `/api/status` shows it under `source_detail.port_found`. Set `MHM_PORT` before
starting the backend:

```
set MHM_PORT=COM5            (Windows cmd)
$env:MHM_PORT = "COM5"       (PowerShell)
export MHM_PORT=/dev/ttyACM0 (macOS/Linux)
```

Use it to force a specific board (e.g. two Arduinos plugged in). Unset it to go back to
auto-detection.

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/status` | Source, scenario, speed, serial port, connected, last error, recording, rows received/rejected, latest `analysis`, `model`, `warm_start`, `analysis_timing_ms`. |
| GET  | `/api/sensors` | The sensor registry (the dashboard builds itself from this). |
| GET  | `/api/history?seconds=N&detail=compact` | Rows from the last N seconds (up to 10 minutes kept in memory), each with its analysis: `compact` (overall, ML status, health, forecast seconds; for trend charts, default), `full` or `none`. |
| POST | `/api/source` | `{type, scenario?, speed?, file?, loop?, warmstart?}`: switch source without restarting; `warmstart` pre-fills the ML/forecast windows from a recording before the first row. |
| POST | `/api/warmstart` | `{file}`: warm-start the current source from a recording (applied at the next row). |
| GET  | `/api/model` | Model summary: status, sensors, trained_on (real vs synthetic rows), provisional, created, calibration. |
| POST | `/api/model/reload` | Reload `models/` from disk without restarting. |
| POST | `/api/model/train` | `{files: [...]}` (names in data/recordings): train in the background, then reload. Returns a job id (202). |
| GET  | `/api/model/train/{id}` | Training job progress: status (queued/running/done/failed), step, elapsed, result. |
| POST | `/api/record/start`, `/api/record/stop` | Start/stop recording. |
| POST | `/api/label` | `{label}`: label for live rows. |
| GET  | `/api/recordings` | Recording files with size, row count and duration. |
| WS   | `/ws/stream` | Messages: `{"type":"row","mode":...,"row":{...},"analysis":{...}}` and `{"type":"status","status":{...}}`. |

`connected` in `/api/status` is debounced: it stays `true` while a new source starts up
and while rows arrive, and only turns `false` after `link_grace_s` (3) seconds without
data or with a port error, so the dashboard doesn't flash "disconnected" on every source
switch. `link` gives the detail: `starting`, `ok`, `no_data`, `down` or `finished`, plus
`data_age_s`.

`analysis` (on every WebSocket row, in `/api/status` and in `/api/history?detail=full`):

```
overall        NORMAL | WARNING | CRITICAL   worse of rules and ML; ML alone can only give WARNING
alert_source   rules | ml | both | none
headline       e.g. "Vibration high - ML anomaly (health 34)", "Temperature rising - CRITICAL in ~2 min"
device         {state, reported, reason, hold_remaining_s, agrees}   device-rule mirror
ml             {status, health, causes[2]{sensor, direction, z, text}, provisional,
                warmup_remaining_s, settling_remaining_s, clear_remaining_s, instant, message}
forecast       {temp_c: {trend, status, seconds_to_warn, seconds_to_critical,
                to_warn, to_critical ("~2 min"), text, r2}, humidity: {...}}
warm_start     "warm-started from <file>" or null
```

ML status: `OK`, `ANOMALY`, `WARMING_UP` (window not full; `warmup_remaining_s`),
`ML_UNAVAILABLE` (an ML sensor is missing too much, e.g. DHT11 fault), `NO_MODEL`,
`NEEDS_RETRAIN` (the registry's ML sensors differ from the model's). It is smoothed:
ANOMALY after health < 50 for 3 rows, clears after health > 60 for 5 rows
(`ml_anomaly_*` / `ml_clear_*` in settings.json). Full rules:
[DATA_CONTRACT.md section 9](../docs/DATA_CONTRACT.md#9-live-analysis-backend).

Per-row cost of features + score + forecast: about 20 ms on average, about 36 ms at p95
on the dev laptop (`analysis_timing_ms` in `/api/status`).

## Watching the stream: `ws_peek.py`

With the backend running, print rows from the WebSocket in a compact table:

```
python scripts/ws_peek.py -n 30                       # 30 rows
python scripts/ws_peek.py --changes --headlines -n 40  # only changes, with the headline
```

Example (`recovery` scenario at 5x, headlines shortened):

```
    t  temp  snd  vib  dev      overall  src   ml       hlth hold  cause                temp fc   | headline
   20  28.6  146   73  CRITICAL CRITICAL rules OK          0    -  Sound level (p +99   -   | Sound level ... 146 >= crit 120; Vibration 73 >= crit 60 - CRITICAL
   22  28.5  150   70  CRITICAL CRITICAL both  ANOMALY     0    -  Sound level (p +99   -   | ... - CRITICAL; ML anomaly (health 0)
   50  28.5    4    1  CRITICAL CRITICAL both  ANOMALY     0    4  Sound level (p +99   stable   | recovering, was: ... - CRITICAL; ML anomaly (health 0)
   54  28.7    3    3  WARNING  WARNING  both  ANOMALY     0    5  Sound level (p +99   stable   | recovering, was: ... - WARNING; ML anomaly (health 0)
   59  28.8    4    2  NORMAL   WARNING  ml    ANOMALY   100    -  Vibration unst +2    stable   | Back to normal - ML anomaly clearing in 4 s (health 100)
   63  29.1    4    3  NORMAL   NORMAL   none  OK        100    -  Vibration unst +3    stable   | All normal (health 100)
```

## ML engine

| File | Role |
|---|---|
| `app/ml/features.py` | `FeatureWindow`: per ML sensor mean, std, min, max, slope (per second), last over the last `ml_window_s` (10) seconds of the **device clock**. Returns `None` ("warming up") until the window is full or if a sensor is missing in more than 30% of it. Used by training, evaluation **and** live scoring. |
| `app/ml/training.py` | IsolationForest on `label=normal` windows only, health calibration, `model_meta.json`. |
| `app/ml/scorer.py` | `Scorer.score(features)` returns `ml_status` (OK / ANOMALY / WARMING_UP / NO_MODEL / NEEDS_RETRAIN), `health` 0–100, top-2 `causes` ("Vibration high", z), `provisional`. A model trained on other sensors returns NEEDS_RETRAIN and never crashes. |
| `app/ml/forecast.py` | Linear trend over the last 60 s for sensors with `"forecast": true` (temperature, humidity): seconds to WARNING / CRITICAL (direction aware; R² ≥ 0.6), shown rounded ("< 1 min", "~2 min", "> 30 min"). Needs no model. |
| `app/ml/evaluation.py` | ML vs rules vs forecast metrics. Real rows only unless `--dev-synthetic`. False alarms exclude a margin of window + hold (15 s) after each fault; the raw rate is reported alongside. |
| `app/ml/jobs.py` | Background training jobs for `POST /api/model/train`. |
| `app/analysis.py` | Live per-row analysis: ML smoothing, overall status, alert source, headline, warm start. |

Data rules, enforced in code:
- Training uses only `label=normal` rows. Synthetic data may be used for training only;
  the model is then marked **provisional**.
- Evaluation numbers are only valid on **real** rows with induced faults. `evaluate.py`
  refuses synthetic or fault-free input; `--dev-synthetic` output is stamped
  **SIMULATED DATA - NOT A RESULT** on every line.
- ML sensors come from the registry (`enabled` AND `include_in_ml`); current and bus
  voltage are excluded.

```
python scripts/generate_synthetic.py                         # 60 min normal + dev fault set -> data/synthetic/
python scripts/generate_synthetic.py --from-real ../data/recordings/session_*.csv   # baselines from real data
python scripts/train.py "../data/synthetic/normal_*.csv"     # -> models/model.joblib + model_meta.json
python scripts/evaluate.py ../data/recordings/session_*.csv  # real recordings with label=fault periods
python scripts/evaluate.py --dev-synthetic "../data/synthetic/devfault_*.csv"   # development check only
```

Settings (`config/settings.json`): `ml_window_s`, `ml_max_missing_frac`,
`forecast_window_s`, `forecast_min_r2`, `forecast_cap_s`, `ml_anomaly_health`,
`ml_anomaly_rows`, `ml_clear_health`, `ml_clear_rows`, `warmstart_file` (a recording in
data/recordings to warm-start from on every startup; `null` = off).

## Tests

```
scripts\run_tests.bat                 (Windows, from anywhere)
python -m pytest                      (from backend/, venv active)
python -m pytest tests/test_device_rules.py -v
```

No hardware is needed: the serial tests use a fake port and mocked port lists, and the
simulator is stepped directly. `run_tests.bat` also prints coverage per module.
`test_device_rules.py` reads the worked example table from `docs/DATA_CONTRACT.md` and
checks it against the code, so the docs and the state machine can't drift apart.

## Code map

| File | Role |
|------|------|
| `app/main.py` | FastAPI app, endpoints, startup source choice. |
| `app/config.py` | Paths, `settings.json`, `MHM_PORT`. |
| `app/registry.py` | Loads `sensors.json`; enabled / ML sensors, limits, group rule. |
| `app/models.py` | `SensorRow`, `parse_line()`, CSV helpers. |
| `app/device_rules.py` | `DeviceStateMachine`: `dev_state` with immediate escalation, hysteresis + `hold_seconds` de-escalation (same as the firmware). Used by the simulator and mirrored in the pipeline. |
| `app/sources/` | `simulator.py`, `serial_source.py`, `replay.py` (common interface in `base.py`). |
| `app/pipeline.py` | source → `process()` → broadcast + history + recorder. `process()` is the Phase 3 hook for rules + ML. |
| `app/recorder.py` | CSV recording and the recordings list. |
| `app/state.py` | Shared state, 10-minute ring buffer, WebSocket broadcaster. |
