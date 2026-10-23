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
| `sudden_fault` | At a random time 20–60 s in, vibration and sound jump up. | `fault` after the jump |
| `slow_drift`   | From 10 s, temperature climbs over 4 minutes past 35 °C (WARNING) and 40 °C (CRITICAL); vibration slowly rises. | `fault` after it starts |
| `sensor_fault` | At a random time 20–60 s in, the DHT11 stops responding (temp and humidity go empty → WARNING). | `fault` after it starts |

Disabled sensors (in `sensors.json`) are always empty, exactly like the real device.
`dev_state` is computed by `app/device_rules.py`, the same rules as the Arduino.

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
USB vendor ID, clones by "CH340" / "USB-SERIAL" in the name). If auto-detection fails,
set the port yourself before starting:

```
set MHM_PORT=COM5            (Windows cmd)
$env:MHM_PORT = "COM5"       (PowerShell)
export MHM_PORT=/dev/ttyACM0 (macOS/Linux)
```

or put `"serial_port": "COM5"` in [`config/settings.json`](config/settings.json). The
configured port is used only when auto-detection finds nothing.

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/status` | Source, scenario, speed, serial port, connected, last error, recording, rows received/rejected. |
| GET  | `/api/sensors` | The sensor registry (the dashboard builds itself from this). |
| GET  | `/api/history?seconds=N` | Rows from the last N seconds (up to 10 minutes kept in memory). |
| POST | `/api/source` | `{type, scenario?, speed?, file?, loop?}`: switch source without restarting. |
| POST | `/api/record/start`, `/api/record/stop` | Start/stop recording. |
| POST | `/api/label` | `{label}`: label for live rows. |
| GET  | `/api/recordings` | Recording files with size, row count and duration. |
| WS   | `/ws/stream` | Messages: `{"type":"row","mode":...,"row":{...}}` and `{"type":"status","status":{...}}`. |

## Code map

| File | Role |
|------|------|
| `app/main.py` | FastAPI app, endpoints, startup source choice. |
| `app/config.py` | Paths, `settings.json`, `MHM_PORT`. |
| `app/registry.py` | Loads `sensors.json`; enabled / ML sensors, limits, group rule. |
| `app/models.py` | `SensorRow`, `parse_line()`, CSV helpers. |
| `app/device_rules.py` | `dev_state` rules shared with the simulator (same as the firmware). |
| `app/sources/` | `simulator.py`, `serial_source.py`, `replay.py` (common interface in `base.py`). |
| `app/pipeline.py` | source → `process()` → broadcast + history + recorder. `process()` is the Phase 3 hook for rules + ML. |
| `app/recorder.py` | CSV recording and the recordings list. |
| `app/state.py` | Shared state, 10-minute ring buffer, WebSocket broadcaster. |
