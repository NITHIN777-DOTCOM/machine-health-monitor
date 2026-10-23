"""Print rows from the backend's WebSocket stream, one compact line per row.

Usage (backend running, venv active, from backend/):
    python scripts/ws_peek.py                 # 20 rows
    python scripts/ws_peek.py -n 100          # 100 rows
    python scripts/ws_peek.py --changes       # only rows where a state, ML status or hold timer changes
    python scripts/ws_peek.py --headlines     # add the human headline to every line
    python scripts/ws_peek.py --url ws://127.0.0.1:8000/ws/stream

Columns: t (device seconds), temp / sound / vibration values, dev (device dev_state),
overall (worse of rules and ML; ML alone can only make it WARNING), src (alert_source),
ml (ML status), hlth (ML health 0-100), hold (seconds before the device state can step
down), cause (top ML cause), temp fc (temperature forecast).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import websockets

DEFAULT_URL = "ws://127.0.0.1:8000/ws/stream"
SHORT_ML = {"WARMING_UP": "WARMING", "ML_UNAVAILABLE": "UNAVAIL", "NEEDS_RETRAIN": "RETRAIN", "NO_MODEL": "NO_MODEL"}


def fmt(v) -> str:
    return "-" if v is None else f"{v:g}"


def temp_forecast(analysis: dict) -> str:
    f = analysis["forecast"].get("temp_c")
    if not f or f["status"] in ("stable", "insufficient_data"):
        return "stable" if f and f["status"] == "stable" else "-"
    if f["to_critical"] == "reached":
        return "CRIT reached"
    parts = []
    if f["to_warn"] and f["to_warn"] != "reached":
        parts.append(f"W {f['to_warn']}")
    if f["to_critical"]:
        parts.append(f"C {f['to_critical']}")
    return " ".join(parts) or f["status"]


async def peek(url: str, n: int, changes_only: bool, headlines: bool) -> None:
    async with websockets.connect(url, open_timeout=5) as ws:
        print(f"{'t':>5} {'temp':>5} {'snd':>4} {'vib':>4}  {'dev':8} {'overall':8} {'src':5} "
              f"{'ml':8} {'hlth':>4} {'hold':>4}  {'cause':20} temp fc" + ("   | headline" if headlines else ""))
        shown, last = 0, None
        while shown < n:
            msg = json.loads(await ws.recv())
            if msg["type"] == "status":
                s = msg["status"]
                extra = f" warm_start={s['warm_start']['message']}" if s.get("warm_start") else ""
                print(f"-- status: source={s['source']} scenario={s['scenario']} speed={s['speed']} "
                      f"link={s['link']} error={s['last_error']}{extra}")
                continue
            r, a = msg["row"], msg["analysis"]
            ml, dev = a["ml"], a["device"]
            key = (r["dev_state"], a["overall"], a["alert_source"], ml["status"], dev["hold_remaining_s"])
            if changes_only and key == last:
                continue
            last = key
            t = "-" if r["ms"] is None else f"{r['ms'] / 1000:.0f}"
            cause = ml["causes"][0] if ml["causes"] else None
            cause_txt = f"{cause['text'][:14]} {cause['z']:+.0f}" if cause else ""
            status = SHORT_ML.get(ml["status"], ml["status"])
            if ml["status"] == "WARMING_UP" and ml["warmup_remaining_s"] is not None:
                status = f"WARM{ml['warmup_remaining_s']:.0f}s"
            line = (f"{t:>5} {fmt(r['temp_c']):>5} {fmt(r['sound_peak']):>4} {fmt(r['vib_count']):>4}  "
                    f"{r['dev_state'] or '-':8} {a['overall']:8} {a['alert_source']:5} {status:8} "
                    f"{fmt(None if ml['health'] is None else round(ml['health'])):>4} "
                    f"{fmt(dev['hold_remaining_s']):>4}  {cause_txt:20} {temp_forecast(a)}")
            if headlines:
                line += f"   | {a['headline']}"
            print(line)
            shown += 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=20, help="number of rows to print (default 20)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"WebSocket URL (default {DEFAULT_URL})")
    ap.add_argument("--changes", action="store_true", help="only print rows where a state, ML status or hold changes")
    ap.add_argument("--headlines", action="store_true", help="append the headline to each line")
    args = ap.parse_args()
    try:
        asyncio.run(peek(args.url, args.n, args.changes, args.headlines))
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"Cannot connect to {args.url}: {exc}. Is the backend running?", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
