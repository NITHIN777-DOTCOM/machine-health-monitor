"""Print rows from the backend's WebSocket stream, one compact line per row.

Usage (backend running, venv active, from backend/):
    python scripts/ws_peek.py                 # 20 rows
    python scripts/ws_peek.py -n 100          # 100 rows
    python scripts/ws_peek.py --changes       # only rows where the state or hold timer changes
    python scripts/ws_peek.py --url ws://127.0.0.1:8000/ws/stream

Columns: t (device seconds), the core sensor values, dev_state (as sent by the
device / simulator), mirror (the backend's state machine), hold (seconds left before
the state can step down), label, reason.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import websockets

DEFAULT_URL = "ws://127.0.0.1:8000/ws/stream"
KEYS = ("temp_c", "humidity", "sound_peak", "vib_count")


def fmt(v) -> str:
    return "-" if v is None else f"{v:g}"


async def peek(url: str, n: int, changes_only: bool) -> None:
    async with websockets.connect(url, open_timeout=5) as ws:
        print(f"{'t':>6} {'temp':>5} {'hum':>5} {'sound':>5} {'vib':>4}  {'dev_state':9} {'mirror':9} {'hold':>4}  {'label':7} reason")
        shown, last = 0, None
        while shown < n:
            msg = json.loads(await ws.recv())
            if msg["type"] == "status":
                s = msg["status"]
                print(f"-- status: source={s['source']} scenario={s['scenario']} speed={s['speed']} "
                      f"connected={s['connected']} error={s['last_error']}")
                continue
            r, d = msg["row"], msg["device"]
            key = (r["dev_state"], d["state"], d["hold_remaining_s"])
            if changes_only and key == last:
                continue
            last = key
            t = "-" if r["ms"] is None else f"{r['ms'] / 1000:.0f}"
            vals = " ".join(f"{fmt(r[k]):>5}" for k in KEYS[:3]) + f" {fmt(r['vib_count']):>4}"
            print(f"{t:>6} {vals}  {r['dev_state'] or '-':9} {d['state']:9} {fmt(d['hold_remaining_s']):>4}  "
                  f"{r['label']:7} {d['reason'] or ''}")
            shown += 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=20, help="number of rows to print (default 20)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"WebSocket URL (default {DEFAULT_URL})")
    ap.add_argument("--changes", action="store_true", help="only print rows where dev_state / mirror / hold change")
    args = ap.parse_args()
    try:
        asyncio.run(peek(args.url, args.n, args.changes))
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"Cannot connect to {args.url}: {exc}. Is the backend running?", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
