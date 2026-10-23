"""Evaluate ML vs the threshold rules (and the forecast) on labelled recordings.

DATA RULE: evaluation numbers are only valid on REAL rows with induced faults.
select() drops synthetic rows unless allow_synthetic=True, and refuses to run when no
real fault rows are left. With allow_synthetic, every output line and the report are
stamped "SIMULATED DATA - NOT A RESULT".

Definitions (one "window" = the feature window ending at a row; rows where the ML
window is still warming up, and rows labelled "unknown", are not evaluated):
  detection rate    = flagged fault windows / fault windows
  false alarm rate  = flagged normal windows / normal windows, EXCLUDING normal windows
                      within a margin of (window_s + hold_seconds) after a fault period
                      ends (main figure). Reason: for that long after a fault the ML
                      window still contains fault values and the device rules are still
                      holding their state by design, so flags there are expected
                      after-effects of the fault, not false alarms.
  false alarm (raw) = the same without the margin, reported alongside for transparency
  episode           = a run of consecutive label=fault rows in one recording
  detection delay   = seconds (device clock) from an episode's first row to the first
                      flagged window inside it; episodes never flagged count as missed
Detectors:
  ml              model says ANOMALY
  rules           device dev_state is WARNING or CRITICAL
  rules_critical  device dev_state is CRITICAL
  forecast        trend forecast predicts (or sees) a CRITICAL limit within the cap
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..config import Settings
from ..registry import Registry
from .dataset import Dataset, Segment
from .features import FeatureWindow, ml_sensor_keys
from .forecast import forecast, predicts_critical
from .scorer import ANOMALY, Scorer

STAMP = "SIMULATED DATA - NOT A RESULT"
DETECTORS = ("ml", "rules", "rules_critical", "forecast")


class EvaluationRefused(Exception):
    pass


def select(dataset: Dataset, allow_synthetic: bool = False) -> tuple[Dataset, list[str]]:
    """Apply the data rule. Returns the rows to evaluate and notes explaining what was dropped."""
    notes: list[str] = []
    if allow_synthetic:
        segments = dataset.segments
        notes.append("--dev-synthetic: synthetic rows are INCLUDED. Results are for development checks only.")
    else:
        segments = []
        dropped = 0
        for seg in dataset.segments:
            rows = [r for r in seg.rows if r.source == "real"]
            dropped += len(seg.rows) - len(rows)
            if rows:
                segments.append(Segment(seg.file, rows))
        if dropped:
            notes.append(f"{dropped} synthetic rows ignored (evaluation uses source=real only).")
    selected = Dataset(dataset.files, segments, dataset.bad_rows)
    labels = selected.counts()["label"]
    if not labels.get("fault"):
        what = "rows" if allow_synthetic else "REAL rows"
        raise EvaluationRefused(
            f"No {what} labelled 'fault' in the input "
            f"(label counts: {labels or 'none'}; source counts in input: {dataset.counts()['source'] or 'none'}). "
            "Evaluation numbers are only valid on real recordings with induced faults: record the real "
            "machine, mark the fault period with POST /api/label {\"label\": \"fault\"}, then evaluate those files."
            + ("" if allow_synthetic else " (--dev-synthetic allows simulated data for development checks only.)"))
    return selected, notes


@dataclass
class Episode:
    file: str
    start_ms: int
    end_ms: int
    first_flag_ms: dict[str, int | None] = field(default_factory=dict)

    def delay(self, det: str) -> float | None:
        ms = self.first_flag_ms.get(det)
        return None if ms is None else (ms - self.start_ms) / 1000.0


def run(dataset: Dataset, registry: Registry, scorer: Scorer | None, settings: Settings) -> dict[str, Any]:
    ml_on = scorer is not None and scorer.ready
    dets = [d for d in DETECTORS if d != "ml" or ml_on]
    counts = {d: {"fault": 0, "fault_flagged": 0, "normal": 0, "normal_flagged": 0,
                  "normal_raw": 0, "normal_raw_flagged": 0} for d in dets}
    window_s = scorer.meta["window_s"] if ml_on else settings.ml_window_s
    margin_ms = (window_s + settings.hold_seconds) * 1000
    episodes: list[Episode] = []

    for seg in dataset.segments:
        fw = scorer.make_window() if ml_on else FeatureWindow(
            ml_sensor_keys(registry), settings.ml_window_s, settings.ml_max_missing_frac)
        hist: deque = deque()
        ep: Episode | None = None
        last_fault_ms: int | None = None
        for row in seg.rows:
            if row.label == "fault":
                last_fault_ms = row.ms
                if ep is None:
                    ep = Episode(seg.file, row.ms, row.ms, {d: None for d in dets})
                    episodes.append(ep)
                ep.end_ms = row.ms
            else:
                ep = None
            feats = fw.push_row(row)
            hist.append(row)
            while hist and hist[0].ms <= row.ms - settings.forecast_window_s * 1000:
                hist.popleft()
            if feats is None or row.label not in ("normal", "fault"):
                continue
            flags = {
                "rules": row.dev_state in ("WARNING", "CRITICAL"),
                "rules_critical": row.dev_state == "CRITICAL",
                "forecast": predicts_critical(forecast(list(hist), registry, window_s=settings.forecast_window_s,
                                                       min_r2=settings.forecast_min_r2, cap_s=settings.forecast_cap_s)),
            }
            if ml_on:
                flags["ml"] = scorer.score(feats)["ml_status"] == ANOMALY
            in_margin = (row.label == "normal" and last_fault_ms is not None
                         and row.ms - last_fault_ms <= margin_ms)
            for d in dets:
                if row.label == "fault":
                    counts[d]["fault"] += 1
                    counts[d]["fault_flagged"] += flags[d]
                    if flags[d] and ep is not None and ep.first_flag_ms[d] is None:
                        ep.first_flag_ms[d] = row.ms
                else:
                    counts[d]["normal_raw"] += 1
                    counts[d]["normal_raw_flagged"] += flags[d]
                    if not in_margin:
                        counts[d]["normal"] += 1
                        counts[d]["normal_flagged"] += flags[d]

    metrics = {}
    for d in dets:
        c = counts[d]
        delays = [e.delay(d) for e in episodes if e.delay(d) is not None]
        metrics[d] = {
            **c,
            "detection_rate": c["fault_flagged"] / c["fault"] if c["fault"] else None,
            "false_alarm_rate": c["normal_flagged"] / c["normal"] if c["normal"] else None,
            "false_alarm_rate_raw": c["normal_raw_flagged"] / c["normal_raw"] if c["normal_raw"] else None,
            "episodes": len(episodes),
            "episodes_detected": len(delays),
            "mean_delay_s": sum(delays) / len(delays) if delays else None,
        }
    return {"detectors": dets, "metrics": metrics, "episodes": episodes, "margin_s": margin_ms / 1000,
            "ml_status": scorer.status if scorer else "NO_MODEL",
            "ml_message": scorer.message if scorer else "no model loaded"}


# ---- reporting --------------------------------------------------------------------------

def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _sec(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} s"


def format_lines(result: dict[str, Any], *, simulated: bool) -> list[str]:
    """Console summary. Every line carries the stamp when simulated."""
    lines = []
    if result["ml_status"] != "READY":
        lines.append(f"ML not evaluated: {result['ml_status']} ({result['ml_message']})")
    lines.append(f"{'detector':16} {'detection':>10} {'false alarm':>12} {'(raw)':>8} {'episodes':>9} {'mean delay':>11}")
    for d in result["detectors"]:
        m = result["metrics"][d]
        lines.append(f"{d:16} {_pct(m['detection_rate']):>10} {_pct(m['false_alarm_rate']):>12} "
                     f"{_pct(m['false_alarm_rate_raw']):>8} "
                     f"{m['episodes_detected']:>4}/{m['episodes']:<4} {_sec(m['mean_delay_s']):>11}")
    lines.append(f"false alarm excludes {result['margin_s']:.0f} s after each fault period "
                 f"(window + hold time, expected after-effects); (raw) includes them")
    lead = forecast_lead(result)
    if lead is not None:
        lines.append(f"forecast predicted CRITICAL on average {lead:.1f} s before the rules reached CRITICAL "
                     f"(episodes where both happened)")
    return [f"[{STAMP}] {l}" for l in lines] if simulated else lines


def forecast_lead(result: dict[str, Any]) -> float | None:
    leads = [e.delay("rules_critical") - e.delay("forecast") for e in result["episodes"]
             if e.delay("rules_critical") is not None and e.delay("forecast") is not None]
    return sum(leads) / len(leads) if leads else None


def format_report(result: dict[str, Any], *, files: list[str], counts: dict[str, Any], notes: list[str],
                  model_info: dict[str, Any] | None, simulated: bool) -> str:
    banner = f"> **{STAMP}.** These numbers come from synthetic data and must not be presented as results.\n\n" \
        if simulated else ""
    title = "ML evaluation report" + (f" - {STAMP}" if simulated else "")
    out = [f"# {title}\n", banner,
           f"Date: {datetime.now().astimezone().isoformat(timespec='seconds')}\n\n",
           "## Input\n\n", *[f"- `{f}`\n" for f in files], "\n",
           f"Rows evaluated by source: {counts['source']}; by label: {counts['label']}\n\n"]
    out += [f"- {n}\n" for n in notes]
    if model_info:
        out.append(f"\nModel: status {model_info.get('status')}, created {model_info.get('created')}, "
                   f"sensors {model_info.get('sensors')}, window {model_info.get('window_s')} s, "
                   f"provisional: {model_info.get('provisional')}\n")
    out += ["\n## Metrics\n\n", banner,
            f"| Detector | Detection rate | False alarm rate (excl. {result['margin_s']:.0f} s margin) | "
            "False alarm rate (raw) | Episodes detected | Mean detection delay |\n",
            "|---|---|---|---|---|---|\n"]
    for d in result["detectors"]:
        m = result["metrics"][d]
        out.append(f"| {d} | {_pct(m['detection_rate'])} ({m['fault_flagged']}/{m['fault']}) | "
                   f"{_pct(m['false_alarm_rate'])} ({m['normal_flagged']}/{m['normal']}) | "
                   f"{_pct(m['false_alarm_rate_raw'])} ({m['normal_raw_flagged']}/{m['normal_raw']}) | "
                   f"{m['episodes_detected']}/{m['episodes']} | {_sec(m['mean_delay_s'])} |\n")
    out.append(f"\nThe main false alarm rate leaves out normal windows in the {result['margin_s']:.0f} s "
               "(feature window + device hold time) after each fault period: there the ML window still "
               "contains fault values and the rules are still holding their state by design. The raw rate "
               "counts them too.\n")
    if result["ml_status"] != "READY":
        out.append(f"\nML not evaluated: {result['ml_status']} ({result['ml_message']})\n")
    lead = forecast_lead(result)
    if lead is not None:
        out.append(f"\nForecast predicted CRITICAL on average **{lead:.1f} s** before the rules reached CRITICAL.\n")
    out += ["\n## Fault episodes (delay from episode start)\n\n",
            "| File | Start (s) | Length (s) | " + " | ".join(result["detectors"]) + " |\n",
            "|---|---|---|" + "---|" * len(result["detectors"]) + "\n"]
    for e in result["episodes"]:
        out.append(f"| {e.file} | {e.start_ms / 1000:.0f} | {(e.end_ms - e.start_ms) / 1000 + 1:.0f} | "
                   + " | ".join(_sec(e.delay(d)) if e.delay(d) is not None else "missed" for d in result["detectors"])
                   + " |\n")
    out += ["\n## Definitions\n\n", (__doc__ or "").split("Definitions", 1)[1].replace("\n  ", "\n- ").strip(), "\n"]
    if simulated:
        out.append(f"\n{banner}")
    return "".join(out)
