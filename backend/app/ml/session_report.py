"""Per-step evaluation of one labelled real session (Phase 8.2, held-out session 02).

Input: the trace of ONE run of the session through the live pipeline (evaluation.run:
device-rule mirror, smoothed ML, forecast), the session's step log (time, label, step name)
and one or more label sets for the same rows (the cleaned labels and the labels as set
live). The pipeline does not read labels, so one run serves every label set.

Definitions (all counts are rows of 1 s; a row counts once its 10 s window is full):
  rules flag      the board's own dev_state is WARNING or CRITICAL (what drives the buzzer)
  ML flag         the smoothed ML status is ANOMALY (what the dashboard shows)
  fault kind      the fault step a fault row belongs to (a fault row inside a gap belongs
                  to the next fault step: step 7 started 8 s before its label switch)
  span            first to last fault row of a kind
  delay           seconds from the span start to the first flag at or after it, up to the
                  span end + margin (window + hold = 15 s)
  episode         a run of consecutive fault rows; caught if a flag falls inside it or up to
                  EPISODE_GRACE_S after it (ML needs 3 rows below 50 before it says ANOMALY)
  false alarm     a flag on a normal row; "excl. margin" leaves out normal rows up to 15 s
                  after a fault row of the same label set (after-effects by design)
ML can only see its own sensors (registry: enabled AND include_in_ml). Faults on other
sensors (leak, safety zone) are reported for the rules and marked "not an ML sensor" for
ML, not counted as ML misses.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

STAMP = "REAL DATA - held-out test session"
EPISODE_GRACE_S = 3.0

# Step names in the step log -> kind. Order matters (first match wins).
STEP_KINDS: tuple[tuple[str, str], ...] = (
    ("drying", "drying"), ("cool-down", "cooldown"), ("subtle vibration", "subtle_vibration"),
    ("subtle sound", "subtle_sound"), ("S4 retry", "subtle_sound"), ("strong vibration", "strong_vibration"),
    ("claps", "claps"), ("safety zone", "safety_zone"), ("water leak", "leak"), ("temperature", "temperature"),
    ("everyday activity", "everyday"), ("gap", "gap"), ("normal", "hands_off"), ("stop", "stop"),
)
FAULT_KINDS: dict[str, dict[str, Any]] = {   # kind -> name, the sensors the fault changes, subtle?
    "subtle_vibration": {"name": "Subtle vibration (light taps, below the limit)", "sensors": ["vib_count"], "subtle": True},
    "subtle_sound": {"name": "Subtle sound (music, humming, below the limit)", "sensors": ["sound_peak"], "subtle": True},
    "strong_vibration": {"name": "Strong vibration (firm knocks)", "sensors": ["vib_count"], "subtle": False},
    "claps": {"name": "Loud claps", "sensors": ["sound_peak"], "subtle": False},
    "safety_zone": {"name": "Safety zone (hand near the HC-SR04)", "sensors": ["distance_cm"], "subtle": False},
    "leak": {"name": "Water leak (+ arm in the safety zone)", "sensors": ["leak_raw", "distance_cm"], "subtle": False},
    "temperature": {"name": "Temperature (fingertip on the DHT11)", "sensors": ["temp_c"], "subtle": False},
}
NORMAL_GROUPS = {"hands_off": "Hands-off normal (steps 1, 10 and the gaps)", "everyday": "Everyday activity (step 2)"}


@dataclass
class Step:
    ts: str
    label: str
    name: str
    kind: str


def step_kind(name: str) -> str:
    return next((kind for key, kind in STEP_KINDS if key in name), "other")


def load_steps(path: Path) -> list[Step]:
    """The live step log: tab-separated time, label, step name."""
    steps = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            ts, label, name = line.split("\t")[:3]
            steps.append(Step(ts, label, name, step_kind(name)))
    return sorted(steps, key=lambda s: s.ts)


def load_labels(path: Path) -> dict[int, str]:
    """ms -> label of a stored recording (the device clock identifies a row)."""
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return {int(r["ms"]): r["label"] for r in csv.DictReader(line for line in fh if not line.startswith("#"))}


def assign_kinds(trace: Sequence[dict[str, Any]], steps: Sequence[Step]) -> list[str]:
    """The step kind of every trace row (by time)."""
    out, j = [], -1
    for t in trace:
        while j + 1 < len(steps) and steps[j + 1].ts <= t["ts"]:
            j += 1
        out.append(steps[j].kind if j >= 0 else "before")
    return out


def fault_kinds(kinds: Sequence[str], labels: Sequence[str]) -> list[str | None]:
    """Per row: the fault kind of a fault row (a fault row outside a fault step belongs to
    the next fault step), else None."""
    out: list[str | None] = [None] * len(kinds)
    nxt = None
    for i in range(len(kinds) - 1, -1, -1):
        if kinds[i] in FAULT_KINDS:
            nxt = kinds[i]
        if labels[i] == "fault":
            out[i] = kinds[i] if kinds[i] in FAULT_KINDS else nxt
    return out


def _sec(trace: Sequence[dict[str, Any]], i: int) -> float:
    return trace[i]["ms"] / 1000.0


def _runs(idx: Sequence[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for i in idx:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _first_flag(trace, det: str, start_s: float, end_s: float) -> float | None:
    for t in trace:
        s = t["ms"] / 1000.0
        if start_s <= s <= end_s and t["window_full"] and t["flags"][det]:
            return s
    return None


def evaluate_labels(trace: Sequence[dict[str, Any]], labels: Sequence[str], kinds: Sequence[str],
                    ml_sensors: Iterable[str], margin_s: float) -> dict[str, Any]:
    """Per fault kind and per normal group, for one label set."""
    ml_sensors = set(ml_sensors)
    fk = fault_kinds(kinds, labels)
    last_fault: float | None = None
    after: list[float | None] = []
    for i, t in enumerate(trace):
        if labels[i] == "fault":
            last_fault = _sec(trace, i)
        after.append(None if last_fault is None else _sec(trace, i) - last_fault)

    faults = []
    for kind, spec in FAULT_KINDS.items():
        idx = [i for i, k in enumerate(fk) if k == kind and trace[i]["window_full"]]
        ml_visible = any(s in ml_sensors for s in spec["sensors"])
        entry: dict[str, Any] = {"kind": kind, "name": spec["name"], "subtle": spec["subtle"],
                                 "sensors": spec["sensors"], "ml_sensor": ml_visible, "rows": len(idx)}
        if not idx:
            faults.append(entry)
            continue
        start, end = _sec(trace, idx[0]), _sec(trace, idx[-1])
        episodes = _runs(idx)
        for det in ("rules", "ml"):
            if det == "ml" and not ml_visible:
                entry["ml"] = None
                continue
            first = _first_flag(trace, det, start, end + margin_s)
            entry[det] = {
                "rows": sum(trace[i]["flags"][det] for i in idx),
                "episodes": sum(_first_flag(trace, det, _sec(trace, ep[0]), _sec(trace, ep[-1]) + EPISODE_GRACE_S)
                                is not None for ep in episodes),
                "delay_s": None if first is None else round(first - start, 1),
            }
        entry["episodes"] = len(episodes)
        entry["span_s"] = round(end - start + 1, 1)
        entry["start"] = trace[idx[0]]["ts"]
        if ml_visible:
            # Rows the rules did not flag: did ML flag them? (the key question for subtle faults)
            missed = [i for i in idx if not trace[i]["flags"]["rules"]]
            entry["rules_missed"] = len(missed)
            entry["ml_on_rules_missed"] = sum(trace[i]["flags"]["ml"] for i in missed)
            hs = [trace[i]["health"] for i in idx if trace[i]["health"] is not None]
            entry["health_min"] = min(hs) if hs else None
            entry["health_median"] = median(hs) if hs else None
            entry["instant_below_50"] = sum(trace[i]["health"] is not None and trace[i]["health"] < 50 for i in idx)
        d_r = entry["rules"]["delay_s"]
        d_m = entry["ml"]["delay_s"] if entry.get("ml") else None
        entry["first"] = (None if d_r is None and d_m is None else "rules" if d_m is None
                          else "ml" if d_r is None else "same" if d_r == d_m else "rules" if d_r < d_m else "ml")
        faults.append(entry)

    false_alarms = {}
    for group in NORMAL_GROUPS:
        idx = [i for i, k in enumerate(kinds) if labels[i] == "normal" and trace[i]["window_full"]
               and (k == "everyday") == (group == "everyday")]
        outside = [i for i in idx if after[i] is None or after[i] > margin_s]
        g: dict[str, Any] = {"name": NORMAL_GROUPS[group], "rows": len(idx), "rows_excl_margin": len(outside)}
        for det in ("rules", "ml"):
            g[det] = sum(trace[i]["flags"].get(det, False) for i in idx)
            g[f"{det}_excl_margin"] = sum(trace[i]["flags"].get(det, False) for i in outside)
        hs = [trace[i]["health"] for i in outside if trace[i]["health"] is not None]
        g["health_median"] = median(hs) if hs else None
        g["health_below_50"] = sum(h < 50 for h in hs)
        false_alarms[group] = g
    vis = [f for f in faults if f["rows"] and f["ml_sensor"]]
    totals = {
        "fault_rows": sum(f["rows"] for f in faults),
        "rules_rows": sum(f["rules"]["rows"] for f in faults if f["rows"]),
        "ml_visible_fault_rows": sum(f["rows"] for f in vis),
        "rules_rows_ml_visible": sum(f["rules"]["rows"] for f in vis),
        "ml_rows": sum(f["ml"]["rows"] for f in vis),
        "episodes": sum(f["episodes"] for f in faults if f["rows"]),
        "rules_episodes": sum(f["rules"]["episodes"] for f in faults if f["rows"]),
        "ml_visible_episodes": sum(f["episodes"] for f in vis),
        "ml_episodes": sum(f["ml"]["episodes"] for f in vis),
    }
    return {"faults": faults, "false_alarms": false_alarms, "totals": totals}


def forecast_lead(trace: Sequence[dict[str, Any]], kinds: Sequence[str], sensor: str = "temp_c") -> dict[str, Any]:
    """Temperature step: first row whose forecast predicts the warning limit (ahead of time)
    vs the first row the board is in WARNING (or worse)."""
    idx = [i for i, k in enumerate(kinds) if k == "temperature"]
    if not idx:
        return {"available": False}
    fc_i = next((i for i in idx if (trace[i]["forecast"].get(sensor) or {}).get("to_warn_s") not in (None, 0.0)), None)
    rule_i = next((i for i in idx if trace[i]["dev_state"] in ("WARNING", "CRITICAL")), None)
    out: dict[str, Any] = {"available": True, "sensor": sensor, "step_start": trace[idx[0]]["ts"]}
    if fc_i is not None:
        out.update(forecast_first=trace[fc_i]["ts"], forecast_eta_s=trace[fc_i]["forecast"][sensor]["to_warn_s"],
                   forecast_value=trace[fc_i]["values"].get(sensor))
    if rule_i is not None:
        out.update(rules_warning=trace[rule_i]["ts"], rules_value=trace[rule_i]["values"].get(sensor))
    out["lead_s"] = (None if fc_i is None or rule_i is None
                     else round((trace[rule_i]["ms"] - trace[fc_i]["ms"]) / 1000.0, 1))
    crit = next((i for i in idx if (trace[i]["forecast"].get(sensor) or {}).get("to_critical_s") not in (None, 0.0)), None)
    out["forecast_predicted_critical"] = crit is not None
    # Forecast warnings outside the temperature step and its cool-down (forecast false alarms).
    others = [i for i, k in enumerate(kinds) if k not in ("temperature", "cooldown") and trace[i]["window_full"]]
    out["forecast_warn_rows_elsewhere"] = sum(
        (trace[i]["forecast"].get(sensor) or {}).get("to_warn_s") is not None for i in others)
    out["rows_elsewhere"] = len(others)
    return out


def chart(trace: Sequence[dict[str, Any]], kinds: Sequence[str], labels: Sequence[str], kind: str, sensor: str,
          pad_s: float = 20.0) -> dict[str, Any]:
    """Rows around one step, for the dashboard chart."""
    idx = [i for i, k in enumerate(kinds) if k == kind]
    if not idx:
        return {"kind": kind, "rows": []}
    lo, hi = _sec(trace, idx[0]) - pad_s, _sec(trace, idx[-1]) + pad_s
    t0 = _sec(trace, idx[0])
    rows = [{"t": round(_sec(trace, i) - t0, 1), "ts": t["ts"], "value": t["values"].get(sensor),
             "health": t["health"], "rules": t["flags"]["rules"], "ml": t["flags"].get("ml", False),
             "label": labels[i], "dev_state": t["dev_state"]}
            for i, t in enumerate(trace) if lo <= _sec(trace, i) <= hi]
    return {"kind": kind, "name": FAULT_KINDS[kind]["name"], "sensor": sensor, "rows": rows}


def subtle_verdict(sets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Did ML flag subtle-fault rows that the rules missed? Numbers per label set, plus a
    one-word answer: yes (both subtle kinds, at least half of the rows the rules missed),
    partly (some), no (none)."""
    detail, shares = {}, []
    for name, res in sets.items():
        detail[name] = {}
        for f in res["faults"]:
            if f["subtle"] and f["rows"] and f.get("ml"):
                detail[name][f["kind"]] = {"rows": f["rows"], "rules_rows": f["rules"]["rows"],
                                           "rules_missed": f["rules_missed"], "ml_on_rules_missed": f["ml_on_rules_missed"],
                                           "ml_episodes": f["ml"]["episodes"], "episodes": f["episodes"],
                                           "health_min": f["health_min"], "instant_below_50": f["instant_below_50"]}
                shares.append(f["ml_on_rules_missed"] / f["rules_missed"] if f["rules_missed"] else 0.0)
    answer = "yes" if shares and min(shares) >= 0.5 else "partly" if any(s > 0 for s in shares) else "no"
    return {"answer": answer, "detail": detail}


def subtle_sentence(r: dict[str, Any]) -> str:
    """The subtle-fault verdict in one plain sentence (live labels first: the fairer set)."""
    v = r["subtle"]
    order = [k for k in ("live", "cleaned") if k in v["detail"]] + [k for k in v["detail"] if k not in ("live", "cleaned")]
    parts = []
    for k in order:
        bits = [f"{d['ml_on_rules_missed']} of the {d['rules_missed']} {kind.replace('_', '-')} rows the rules missed"
                for kind, d in v["detail"][k].items()]
        if bits:
            parts.append(f"{' and '.join(bits)} ({'live' if k == 'live' else 'cleaned'} labels)")
    if not parts:
        return "No subtle-fault rows to evaluate."
    return f"{v['answer'].capitalize()}: ML flagged " + "; ".join(parts) + "."


def build(trace: Sequence[dict[str, Any]], steps: Sequence[Step], label_sets: dict[str, Sequence[str]],
          ml_sensors: Iterable[str], margin_s: float, *, session: str, files: dict[str, str],
          model: dict[str, Any]) -> dict[str, Any]:
    kinds = assign_kinds(trace, steps)
    ml_sensors = list(ml_sensors)
    sets = {name: evaluate_labels(trace, labels, kinds, ml_sensors, margin_s) for name, labels in label_sets.items()}
    first_set = next(iter(label_sets))
    return {
        "stamp": STAMP,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": session,
        "files": files,
        "rows": len(trace),
        "margin_s": margin_s,
        "episode_grace_s": EPISODE_GRACE_S,
        "ml_sensors": ml_sensors,
        "model": model,
        "label_sets": sets,
        "subtle": subtle_verdict(sets),
        "forecast": forecast_lead(trace, kinds),
        "chart": chart(trace, kinds, label_sets[first_set], "subtle_vibration", "vib_count"),
    }


# ---- markdown ------------------------------------------------------------------------

SET_NAMES = {"cleaned": "(a) cleaned labels", "live": "(b) live labels"}


def _pct(a: int, b: int) -> str:
    return "n/a" if not b else f"{100 * a / b:.1f} %"


def _cell(f: dict[str, Any], det: str) -> str:
    if not f["rows"]:
        return "no fault rows"
    d = f.get(det)
    if d is None:
        return "not an ML sensor"
    delay = "missed" if d["delay_s"] is None else f"after {d['delay_s']:g} s"
    return f"{d['rows']} of {f['rows']} rows; {d['episodes']} of {f['episodes']} ep.; {delay}"


def _fa(g: dict[str, Any], det: str) -> str:
    a, b = g[f"{det}_excl_margin"], g["rows_excl_margin"]
    return f"{a} of {b} ({_pct(a, b)}) / {g[det]} of {g['rows']} ({_pct(g[det], g['rows'])})"


def _clock(ts: str | None) -> str:
    return ts[11:19] if ts else "never"


def to_markdown(r: dict[str, Any]) -> str:
    sets = r["label_sets"]
    m = r["model"]
    t_on = m["trained_on"]
    out = [f"# Evaluation on the held-out test session: {STAMP}\n\n",
           f"> **{STAMP}.** Session 02 was recorded for testing only (role `test` in "
           "`data/recordings/MANIFEST.json`) and was never used for training, validation or any choice. "
           "It was run through the chosen model **once**.\n\n",
           f"Created {r['created']} by `backend/scripts/evaluate.py` (`app/ml/session_report.py`). "
           "The same numbers are in `eval_real_session_02.json`, shown in the dashboard's Model panel.\n\n",
           "## What was evaluated\n\n",
           f"- **Session:** `{r['files']['cleaned']}` (cleaned labels) and `{r['files']['live']}` "
           f"(the same rows with the labels as set live); steps from `{r['files']['steps']}`. "
           f"{r['rows']} rows, one per second.\n",
           f"- **Model:** {m.get('status')}; created {m.get('created')}; trained on {t_on['real_rows']} real + "
           f"{t_on['synthetic_rows']} synthetic normal rows ({', '.join(t_on['sessions'])}); ML sensors "
           f"{', '.join(m.get('sensors') or [])}, {m.get('feature_count')} features.\n",
           "- **How:** every row went through the live pipeline (`Pipeline.process`): the device-rule mirror, the ML "
           "score with the dashboard's smoothing (ANOMALY after 3 rows below 50, clears after 5 rows above 60) and the "
           "trend forecast. **Rules** = the board's own `dev_state` is WARNING or CRITICAL (this drives the buzzer). "
           "**ML** = the smoothed ML status is ANOMALY.\n\n",
           "## Two label sets\n\n",
           "- **(a) cleaned labels** (`real_session_02_test_*.csv`). The clean-up (`data/recordings/raw/clean_session_02.py`) "
           "**used the device state**: a `normal` row where the board was not NORMAL became `unknown`, and the subtle "
           "steps kept only rows where the board stayed NORMAL. So with the cleaned labels the rules' false-alarm rate "
           "on normal rows is **0 by construction**, and the rules catch **0 subtle-fault rows by construction**. "
           "These labels say what each row physically was, but they are not a fair referee between rules and ML.\n",
           "- **(b) live labels** (`raw/raw_session_*.csv`), as switched by hand during the session. They do not depend "
           "on what the device did, so **(b) is the fairer comparison of rules vs ML**. They are looser: a fault label "
           "also covers the quiet seconds before and after the action, and the normal gaps include accidental bumps.\n\n",
           "## Results per fault: rules vs ML\n\n",
           "Each cell: flagged rows of the fault rows; episodes caught (a flag inside the episode or up to "
           f"{r['episode_grace_s']:g} s after it); delay from the fault's first row to the first flag.\n\n",
           "| Fault | " + " | ".join(f"{SET_NAMES[k]}: rules | {SET_NAMES[k]}: ML" for k in sets) + " |\n",
           "|---|" + "---|---|" * len(sets) + "\n"]
    first = next(iter(sets.values()))["faults"]
    for i, f0 in enumerate(first):
        cells = []
        for k in sets:
            f = sets[k]["faults"][i]
            cells += [_cell(f, "rules"), _cell(f, "ml")]
        out.append(f"| {f0['name']} | " + " | ".join(cells) + " |\n")
    out.append("\nA rules cell with **0 rows but caught episodes** means the board alarmed on a row next to the "
               "episode (within the grace time) that is not a fault row of this label set, e.g. an over-limit tap "
               "that the clean-up labelled unknown.\n")
    out.append("\n**Which raised the alarm first:**\n\n")
    for k in sets:
        out.append(f"- {SET_NAMES[k]}: " + ", ".join(
            f"{f['kind'].replace('_', ' ')}: {f['first'] or 'neither'}" for f in sets[k]["faults"] if f["rows"]) + "\n")
    out.append("\n**Totals:**\n\n")
    for k in sets:
        t = sets[k]["totals"]
        out.append(f"- {SET_NAMES[k]}: rules flagged {t['rules_rows']} of {t['fault_rows']} fault rows "
                   f"({t['rules_episodes']} of {t['episodes']} episodes). On the faults ML can see: rules "
                   f"{t['rules_rows_ml_visible']}, ML {t['ml_rows']} of {t['ml_visible_fault_rows']} rows; ML caught "
                   f"{t['ml_episodes']} of {t['ml_visible_episodes']} episodes.\n")

    v = r["subtle"]
    out += ["\n## Did ML catch the subtle faults the rules missed?\n\n",
            f"**Answer: {v['answer'].upper()}.** {r.get('subtle_text', '').split(': ', 1)[-1]}\n\n",
            "| Label set | Subtle fault | Fault rows | Rules flagged | Rows the rules missed | ML flagged of those | "
            "ML episodes | Lowest health | Rows with health < 50 (before smoothing) |\n",
            "|---|---|---|---|---|---|---|---|---|\n"]
    for k, kinds_d in v["detail"].items():
        for kind, d in kinds_d.items():
            hm = "n/a" if d["health_min"] is None else f"{d['health_min']:.0f}"
            out.append(f"| {SET_NAMES[k]} | {kind.replace('_', ' ')} | {d['rows']} | {d['rules_rows']} | "
                       f"{d['rules_missed']} | {d['ml_on_rules_missed']} | {d['ml_episodes']} of {d['episodes']} | "
                       f"{hm} | {d['instant_below_50']} |\n")

    out += ["\n## False alarms on normal rows\n\n",
            f"Flagged normal rows **excluding** the {r['margin_s']:g} s after a fault (window + hold: after-effects by "
            "design) / **including** them.\n\n",
            "| Label set | Normal rows | Rules | ML | ML health median (excl. margin) |\n", "|---|---|---|---|---|\n"]
    for k in sets:
        for g in sets[k]["false_alarms"].values():
            hm = "n/a" if g["health_median"] is None else f"{g['health_median']:.0f}"
            out.append(f"| {SET_NAMES[k]} | {g['name']} | {_fa(g, 'rules')} | {_fa(g, 'ml')} | {hm} |\n")

    fc = r["forecast"]
    out.append("\n## Temperature step: did the forecast warn early?\n\n")
    if fc.get("available"):
        lead = fc.get("lead_s")
        pred = (f" (temperature {fc['forecast_value']:g} °C, WARNING predicted in {fc['forecast_eta_s']:g} s)"
                if fc.get("forecast_first") else "")
        reached = f" ({fc['rules_value']:g} °C)" if fc.get("rules_warning") else ""
        out.append(f"- The forecast first predicted the WARNING limit at {_clock(fc.get('forecast_first'))}{pred}; "
                   f"the board reached WARNING at {_clock(fc.get('rules_warning'))}{reached}.\n")
        out.append(f"- **Lead time: {'n/a' if lead is None else f'{lead:g} s'}**"
                   + (" (the forecast warned first)." if lead is not None and lead > 0 else ".") + "\n")
        out.append(f"- The forecast {'did' if fc['forecast_predicted_critical'] else 'did not'} predict the CRITICAL "
                   "limit (35 °C) within its horizon during the step; 35 °C was not reached.\n")
        out.append(f"- Forecast warnings outside the temperature step and its cool-down: "
                   f"{fc['forecast_warn_rows_elsewhere']} of {fc['rows_elsewhere']} rows.\n")
    out += ["\n## Faults ML cannot be expected to catch\n\n",
            f"ML uses only {', '.join(r['ml_sensors'])} (registry: enabled AND include_in_ml). The **leak** and "
            "**safety-zone** faults change only `leak_raw` and `distance_cm`, which are rule-only sensors, so the ML "
            "columns say \"not an ML sensor\" and they are not counted as ML misses. Temperature and humidity enter ML "
            "only by how fast they change (`ml_stats`: std, slope), so a slow, steady temperature rise is a job for the "
            "rules and the forecast.\n",
            "\n## Definitions\n\n",
            "All counts are rows of 1 s; a row counts once its 10 s ML window is full.\n\n",
            "- **Rules flag:** the board's own `dev_state` is WARNING or CRITICAL (what drives the buzzer).\n",
            "- **ML flag:** the smoothed ML status is ANOMALY (what the dashboard shows).\n",
            "- **Fault kind:** the fault step a fault row belongs to; a fault row inside a gap belongs to the next "
            "fault step (step 7 started 8 s before its label switch).\n",
            "- **Delay:** seconds from the first fault row of a kind to the first flag at or after it, up to the last "
            f"fault row + {r['margin_s']:g} s.\n",
            "- **Episode:** a run of consecutive fault rows; caught if a flag falls inside it or up to "
            f"{r['episode_grace_s']:g} s after it (ML needs 3 rows below 50 before it says ANOMALY).\n",
            f"- **False alarm:** a flag on a normal row; \"excluding\" leaves out normal rows up to {r['margin_s']:g} s "
            "after a fault row of the same label set (after-effects by design).\n",
            "\nInterpretation, the limit suggestions and every decision: `docs/phase8_report.md`.\n"]
    return "".join(out)
