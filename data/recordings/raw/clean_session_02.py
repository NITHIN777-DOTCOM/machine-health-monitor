"""Label clean-up for session 02 (held-out test). Usage: clean.py <raw.csv> <steps.log> <out.csv>
Prints a per-step table (raw label segments) and the final label counts."""
import csv, sys
from collections import Counter

raw, steps_path, out = sys.argv[1:4]
rows = list(csv.DictReader(open(raw, encoding="utf-8")))
fields = list(rows[0].keys())
steps = [l.rstrip("\n").split("\t") for l in open(steps_path) if l.strip()]
bounds = [(s[0][11:19], s[1], s[2]) for s in steps]   # (HH:MM:SS, label, name)

def t(r): return r["ts_iso"][11:19]
def f(r, c):
    v = r[c]; return None if v == "" else float(v)

def step_of(ts):
    name = None
    for b in bounds:
        if ts >= b[0]: name = b[2]
    return name

for r in rows:
    r["step"] = step_of(t(r)); r["raw_label"] = r["label"]

# ---- Rule A: normal rows that were disturbed -> unknown (incl. holds after a fault: dev_state != NORMAL)
def disturbed(r):
    v, s, l, d = f(r, "vib_count"), f(r, "sound_peak"), f(r, "leak_raw"), f(r, "distance_cm")
    walk_ok = r["step"].startswith("S2")             # walking near the table IS the step-2 activity
    return (r["dev_state"] != "NORMAL" or v is None or v >= 10 or s is None or s >= 10
            or l is None or l >= 20 or d is None or (d < 100 and not walk_ok) or (d < 25)
            or r["step"] == "gap before S5 hands-off 60 s")   # music still on after step 4's STOP
flag = [r["label"] == "normal" and disturbed(r) for r in rows]
for i, r in enumerate(rows):                          # pad 1 row either side
    if any(flag[max(0, i - 1):i + 2]) and r["label"] == "normal":
        r["label"] = "unknown"

# ---- Rule B: inside each fault step only the induced deviation stays fault.
# A label switch applies from the next row, so the first row of the following gap still says
# fault: every live-fault row starts as unknown and only the spans below set fault again.
for r in rows:
    if r["label"] == "fault":
        r["label"] = "unknown"

def span(sel, dev, start=None, end=None):
    """Rows of step `sel` (or time window), fault from first to last deviation, rest unknown."""
    idx = [i for i, r in enumerate(rows)
           if (start <= t(r) < end if start else r["step"] == sel)]
    hits = [i for i in idx if dev(rows[i])]
    for i in idx:
        rows[i]["label"] = "fault" if hits and hits[0] <= i <= hits[-1] else "unknown"
    return idx

base_T = 30.2
# S3 subtle vibration: taps 1-49 only; over-limit taps and their holds -> unknown
idx = span("S3 subtle vibration light taps 40 s", lambda r: f(r, "vib_count") > 0)
for i in idx:
    if f(rows[i], "vib_count") >= 50 or rows[i]["dev_state"] != "NORMAL":
        rows[i]["label"] = "unknown"
# S4 subtle sound: only audible rows (sound >= 6) are fault; the 268 spike + its hold -> unknown
for i, r in enumerate(rows):
    if r["step"] and r["step"].startswith("S4"):
        s = f(r, "sound_peak")
        r["label"] = "fault" if (6 <= s < 40 and r["dev_state"] == "NORMAL") else "unknown"
span("S5 strong vibration firm knocks 15 s", lambda r: f(r, "vib_count") >= 10)
span("S6 loud claps 10 s", lambda r: f(r, "sound_peak") >= 20)
# S7 started ~8 s before the label switch (hand already at 22 cm at 15:57:59)
span(None, lambda r: f(r, "distance_cm") is not None and f(r, "distance_cm") < 25, "15:57:55", "15:58:47")
# S8 leak; the arm also crossed the safety zone (part of the same action)
span("S8 water leak wet finger + drops 15 s",
     lambda r: f(r, "leak_raw") >= 20 or (f(r, "distance_cm") is not None and f(r, "distance_cm") < 25))
# S9 temperature: fault once >= baseline + 1 C (session 01 rule)
idx = span("S9 temperature fingertip on DHT11 up to 90 s", lambda r: f(r, "temp_c") >= base_T + 1)
# accidental bump at 16:03:58 (vib 146): temp never reached 35, so CRITICAL here = the bump
for i in idx:
    if f(rows[i], "vib_count") >= 10 or rows[i]["dev_state"] == "CRITICAL":
        rows[i]["label"] = "unknown"

with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader(); w.writerows(rows)

# ---- report
cols = ["temp_c", "humidity", "sound_peak", "vib_count", "leak_raw", "distance_cm"]
segs = []
for r in rows:
    key = (r["step"], r["raw_label"])
    if not segs or segs[-1][0] != key: segs.append((key, []))
    segs[-1][1].append(r)
print("| step | live label | start | rows | " + " | ".join(cols) + " | dev_state | final labels |")
for (name, lab), rs in segs:
    rng = []
    for c in cols:
        v = [f(r, c) for r in rs if f(r, c) is not None]
        e = sum(f(r, c) is None for r in rs)
        rng.append((f"{min(v):g}–{max(v):g}" if v else "-") + (f" ({e} empty)" if e else ""))
    print(f"| {name} | {lab} | {t(rs[0])} | {len(rs)} | " + " | ".join(rng)
          + f" | {dict(Counter(r['dev_state'] for r in rs))} | {dict(Counter(r['label'] for r in rs))} |")
ms = [int(r["ms"]) for r in rows]
print("rows", len(rows), "duration_s", (ms[-1] - ms[0]) / 1000, "ms gaps>1.5s",
      [(a, b) for a, b in zip(ms, ms[1:]) if b - a > 1500 or b < a][:5])
print("raw labels", dict(Counter(r["raw_label"] for r in rows)))
print("final labels", dict(Counter(r["label"] for r in rows)))
print("first/last ts", rows[0]["ts_iso"], rows[-1]["ts_iso"])
