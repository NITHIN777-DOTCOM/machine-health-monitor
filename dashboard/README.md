# Dashboard (Phase 4)

React + TypeScript (strict) single page that shows what the backend sees: the overall
status, the device rules, the ML opinion, every sensor, 5-minute trends and the forecast.
It is built for a classroom projector: big text, high contrast, light and dark themes, and
every state is shown as **text + icon**, never by colour alone.

It works fully offline: no CDN, no web fonts (system fonts only), charts with Recharts
bundled in.

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
(`vite.config.ts`). The app only uses **relative URLs**, so the same build will work when
FastAPI serves it in Phase 6.

To try scenarios, switch the simulator with curl (there are no buttons for this until Phase 5):

```
curl -X POST http://127.0.0.1:8000/api/source -H "Content-Type: application/json" -d "{\"type\":\"simulator\",\"scenario\":\"sudden_fault\",\"speed\":3}"
```

Scenarios: `normal`, `sudden_fault`, `slow_drift`, `sensor_fault`, `recovery`, `drift_and_recover`.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload on http://127.0.0.1:5173 |
| `npm test` | Vitest unit tests (formatting helpers, sensor cards, trend buffer) |
| `npm run typecheck` | TypeScript check only |
| `npm run build` | Type check + production build into `dist/` (gitignored) |
| `npm run screenshots:install` | Once: downloads Playwright's Chromium **into this project** (`node_modules`) |
| `npm run screenshots` | Takes the review screenshots into `docs/screenshots/phase4/` (backend in simulator mode + dev server must be running). `npm run screenshots -- recovery` for one scenario. |

## What is on the page

1. **Top bar**: mode badge **LIVE / RECORDED / SIMULATED** (from the newest row's `mode`;
   simulated is also striped), connection indicator (the backend's `link` field: starting,
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
   **ML** (status, health 0-100 with a bar, top 2 causes with z-scores, "provisional model"
   tag), **Forecast** (for sensors with `forecast: true`: trend and "CRITICAL in ~3 min").
4. **Sensor cards**: one per enabled sensor, each with its own level against its limits.
   Disabled sensors are listed as "Not connected"; an enabled sensor with an empty field
   shows "No reading - sensor fault".
5. **Trends**: one chart per enabled sensor plus the ML health score, last 5 minutes of
   the **device clock** (`ms`), with dashed warn/critical lines.
6. **Footer**: source, serial port, rows received/rejected, model date.

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
| `src/styles.css` | All styles; theme colours are CSS variables at the top |
| `scripts/screenshots.mjs` | Playwright screenshot run |
