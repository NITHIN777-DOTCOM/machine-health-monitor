# Dashboard (Phase 5, served by the backend since Phase 6)

React + TypeScript (strict) single page that shows what the backend sees: the overall
status, the device rules, the ML opinion, every sensor, 5-minute trends and the forecast.
The look follows the ISA-101 "high-performance HMI" idea: **neutral and calm while
everything is normal, colour only for abnormal states**. Palette #222831 / #393E46 /
#00ADB5 / #EEEEEE (dark and light themes); status colours (normal, warning, critical,
ML anomaly) are separate tokens used only for status. Every state is shown as
**text + icon**, never by colour alone. `node scripts/contrast.mjs` checks every token pair
against WCAG AA in both themes.

It works fully offline: no CDN; the Inter font (`@fontsource/inter`), the icons
(`lucide-react`) and Recharts are bundled in.

## Run it (development)

You need Node.js 20+ (developed on Node 24) and the backend running.

```
:: terminal 1, from backend/ : the API on http://127.0.0.1:8000
set MHM_SOURCE=simulator                      (optional: simulator only, never opens a COM port)
venv\Scripts\python -m uvicorn app.main:app --reload

:: terminal 2, from dashboard/
npm install                                   (once)
npm run dev                                   -> open http://127.0.0.1:5173
```

Use `127.0.0.1`, not `localhost`: on the dev laptop WebSocket connections to `localhost`
hang on IPv6. The Vite dev server forwards `/api/...` and `/ws/stream` to the backend
(`vite.config.ts`). The app only uses **relative URLs**, so the same build works when FastAPI
serves it: after `npm run build`, http://127.0.0.1:8000/ shows the dashboard with no dev server
(that is how the portable exe works).

Scenarios, replay and recording are in the **Controls** panel (button in the top bar).
The same switch with curl:

```
curl -X POST http://127.0.0.1:8000/api/source -H "Content-Type: application/json" -d "{\"type\":\"simulator\",\"scenario\":\"sudden_fault\",\"speed\":3}"
```

Scenarios: `normal`, `sudden_fault`, `slow_drift`, `sensor_fault`, `recovery`, `drift_and_recover`.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload on http://127.0.0.1:5173 |
| `npm test` | Vitest unit tests (formatting, cause/confidence bands, sensor cards, trend buffer, chart grid, control logic) |
| `npm run typecheck` | TypeScript check only |
| `npm run build` | Type check + production build into `dist/` (gitignored) |
| `npm run screenshots:install` | Once: downloads Playwright's Chromium **into this project** (`node_modules`). `npm ci` (also run by `build.bat`) deletes it: run this again afterwards. |
| `npm run screenshots` | Takes the review screenshots into `docs/screenshots/phase5/` (backend with `MHM_SOURCE=simulator` + dev server must be running): the five scenarios, recording, controls and replay, at 1366x768 and 1920x1080, light and dark. `npm run screenshots -- recovery` for one step (`replay` needs `recording` in the same run). The recording it makes is deleted at the end. |
| `node scripts/contrast.mjs` | WCAG contrast check of the colour tokens |

## What is on the page

1. **Top bar**: title + course subtitle, a flat outlined mode badge **LIVE / RECORDED /
   SIMULATED** with a small dot (from the newest row's `mode`), connection indicator (the backend's `link` field: starting,
   ok, no_data, down, finished), theme toggle (default follows the OS; the choice is kept in
   `localStorage`).
2. **Status banner**: `analysis.overall`, the headline and a chip for `alert_source`
   (Rules / ML / Both). It says **"Recovering - back to normal in N s"** (or "down to
   WARNING" from CRITICAL, since the device steps down one level at a time) only once the
   hold countdown has really progressed (`hold_remaining_s <= hold_seconds - 2`). A single
   dip into the hysteresis band keeps showing the active state and reason. ML usually still
   flags the fault during the countdown (its 10 s window still contains it); since ML alone
   keeps the overall status at WARNING, WARNING -> NORMAL then reads "rules clear in N s;
   ML anomaly still active" instead of promising "back to normal".
3. **Device rules** (state, reason, quiet hold countdown, "mirror agrees" / "mismatch"),
   **ML** (status, health 0-100 with a bar and the anomaly level from `ml_thresholds`, up to
   2 causes in plain words such as "Vibration: far above normal" with z only in the tooltip, listed
   only while ML is ANOMALY or health is at/below the clear level (else "Nothing unusual"),
   "provisional model" note), **Forecast** (for sensors with `forecast: true`: "critical in
   ~3 min", "no data" when the sensor's newest value is missing, and "confidence: low /
   medium / high" from the fit R², which is in the tooltip).
4. **Sensor cards**: one per enabled sensor, each with its own level against its limits.
   Disabled sensors are listed as "Not connected"; an enabled sensor with an empty field
   shows "No reading - sensor fault".
5. **Trends**: one chart per enabled sensor plus the ML health score, last 5 minutes of
   the **device clock** (`ms`), with dashed warn/critical lines.
6. **Footer**: source, serial port, rows received/rejected, model date, app version
   (`status.version`: "v0.6.0 · git describe · built date", or "dev").
7. **Controls** (right-hand drawer, opened from the top bar; overlays the page below 1100 px):
   - **Data source**: Live (Arduino) / Simulated / Recorded (`POST /api/source`). Live is
     disabled, with the backend's reason, when `status.serial.available` is false
     (`MHM_SOURCE=simulator`, or no Arduino found).
   - **Scenario** (simulated): Normal, Sudden fault, Slow drift, Recovery, Sensor fault, a
     speed selector 1x / 5x / 10x (a change restarts the running scenario) and
     **Fast-forward drift** (slow drift at 10x).
   - **Replay** (recorded): the list from `GET /api/recordings` (name, duration on the device
     clock, rows, date), speed 1x / 5x / 10x, loop, Play, and a progress bar from
     `status.progress`.
   - **Record**: Start / Stop, elapsed time and row count (also shown as **REC** in the top
     bar while recording), and the label toggle Normal / Fault / None (`POST /api/label`)
     for marking induced faults live. The label is stored on live (Arduino) rows.
   - **Start from recording**: warm start from a chosen file (`POST /api/warmstart`).
   - One request at a time: all buttons are disabled while it runs, and errors appear inline
     at the top of the panel in plain words (e.g. "Port busy: close the Arduino IDE Serial
     Monitor ..."). Logic in `src/lib/controls.ts` (unit-tested).

## Rules the code follows

- **The sensor list comes only from `GET /api/sensors`.** No component names a sensor.
  Enable an optional sensor in `backend/config/sensors.json`, restart the backend, reload
  the page, and its card and chart appear.
- `src/types.ts` mirrors the backend's JSON exactly (row, analysis block, status). If the
  backend changes a shape, change it there.
- Data flow (`src/hooks/useDashboard.ts`): on every (re)connect it loads `/api/sensors`,
  `/api/status` and `/api/history?seconds=300`, then follows `/ws/stream`. It reconnects with
  backoff (1, 2, 4, 8, 10 s). While cut off, a red notice is shown and the last data stays
  on screen, greyed out. At most 5 minutes (device clock) of rows are kept, and updates are
  flushed to the screen 4 times a second, so 10x simulation stays smooth.
- A device clock that goes backwards (new source, Arduino reset) starts the charts over.

## Files

| Path | Contents |
|---|---|
| `src/types.ts` | Backend message types |
| `src/api.ts` | REST calls and the WebSocket URL (all relative) |
| `src/hooks/useDashboard.ts` | Load, stream, reconnect, throttle |
| `src/hooks/useTheme.ts` | Light/dark theme |
| `src/lib/format.ts` | State → label/icon/colour, ML text, forecast text, the "recovering" rule |
| `src/lib/cards.ts` | Sensor cards from the registry |
| `src/lib/buffer.ts` | 5-minute trend buffer |
| `src/components/` | One file per part of the page |
| `src/lib/format.ts` (Phase 5) | Also: cause words by |z| band, the z tooltip, forecast confidence (R² bands), health bands from `status.ml_thresholds` |
| `src/lib/controls.ts` | Control panel logic: active source, Live availability, request bodies, error text, elapsed time, replay progress |
| `src/components/ControlsPanel.tsx`, `RecIndicator.tsx` | The controls drawer and the top-bar REC indicator |
| `src/lib/grid.ts` | Chart grid: columns that fit, last chart stretched so no row has a gap |
| `src/styles.css` | All styles; colour, spacing and type tokens are CSS variables at the top |
| `scripts/contrast.mjs` | WCAG contrast check of the colour tokens (both themes) |
| `scripts/screenshots.mjs` | Playwright screenshot run |
