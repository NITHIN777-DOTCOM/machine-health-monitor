"""Per-step session report (app/ml/session_report.py) and evaluate.py --steps, on crafted data."""
import json

import evaluate as evaluate_cli
from app.ml import roles, session_report as sr
from helpers import rows_from
from test_ml_evaluation import CORE, write_csv


def ts(s: int) -> str:
    return f"2026-10-24T15:{s // 60:02d}:{s % 60:02d}.000+05:30"


STEPS = [sr.Step(ts(0), "normal", "S1 normal hands-off", "hands_off"),
         sr.Step(ts(20), "fault", "S3 subtle vibration light taps", "subtle_vibration"),
         sr.Step(ts(40), "normal", "gap before S7 hands-off 60 s", "gap"),
         sr.Step(ts(60), "fault", "S7 safety zone hand", "safety_zone"),
         sr.Step(ts(70), "normal", "S10 final normal hands-off", "hands_off")]


def trace_row(i, label, rules=False, ml=False, health=100.0, warn_s=None, dev="NORMAL", vib=0):
    return {"file": "x.csv", "ms": i * 1000, "ts": ts(i), "label": label, "values": {"vib_count": vib, "temp_c": 30.0},
            "dev_state": "WARNING" if rules else dev, "mirror_state": "NORMAL", "ml_status": "ANOMALY" if ml else "OK",
            "health": health, "ml_instant": None, "forecast": {"temp_c": {"to_warn_s": warn_s, "to_critical_s": None}},
            "flags": {"rules": rules, "ml": ml, "rules_critical": False, "forecast": False},
            "window_full": i >= 2, "after_fault_s": None}


def crafted():
    """0-19 normal; 20-39 subtle vib fault (episodes 20-24 and 30-34, unknown between), ML flags
    22-24 (3 rows) and 38 (4 s after episode 2, beyond the 3 s grace -> not an episode hit); rules flag 31;
    40-59 normal gap: 58-59 fault (safety zone started early), rules 58-65; ML flags 45 (in margin)
    and 75 (outside); 60-64 safety zone fault; 70-89 normal."""
    tr, labels = [], []
    for i in range(90):
        lab = ("fault" if 20 <= i <= 24 or 30 <= i <= 34 or 58 <= i <= 64 else
               "unknown" if 25 <= i <= 29 or 35 <= i <= 39 or 65 <= i <= 69 else "normal")
        tr.append(trace_row(i, lab, rules=i == 31 or 58 <= i <= 65, ml=i in (22, 23, 24, 38, 45, 75),
                            health=40.0 if i in (21, 22, 23, 24) else 100.0))
        labels.append(lab)
    return tr, labels


def test_step_kinds_from_names():
    assert sr.step_kind("S4 retry: louder/closer (label already fault)") == "subtle_sound"
    assert sr.step_kind("S8 leak drying (until leak < 20)") == "drying"
    assert sr.step_kind("S8 water leak wet finger + drops 15 s") == "leak"
    assert sr.step_kind("S9 cool-down (until within 0.5 C of baseline 30.2)") == "cooldown"
    assert sr.step_kind("S2 normal everyday activity 2 min") == "everyday"
    assert sr.step_kind("gap before S5 hands-off 60 s") == "gap"
    assert sr.step_kind("S10 final normal hands-off 3 min") == "hands_off"


def test_a_fault_row_in_a_gap_belongs_to_the_next_fault_step():
    tr, labels = crafted()
    kinds = sr.assign_kinds(tr, STEPS)
    fk = sr.fault_kinds(kinds, labels)
    assert kinds[58] == "gap" and fk[58] == "safety_zone" and fk[20] == "subtle_vibration" and fk[0] is None


def test_counts_episodes_delays_and_first():
    tr, labels = crafted()
    res = sr.evaluate_labels(tr, labels, sr.assign_kinds(tr, STEPS), ["vib_count", "temp_c"], margin_s=15)
    f = {x["kind"]: x for x in res["faults"]}
    sv = f["subtle_vibration"]
    assert (sv["rows"], sv["episodes"]) == (10, 2)
    assert sv["rules"] == {"rows": 1, "episodes": 1, "delay_s": 11.0}
    assert sv["ml"] == {"rows": 3, "episodes": 1, "delay_s": 2.0}       # flag 38 is 4 s after episode 2
    assert sv["first"] == "ml" and sv["rules_missed"] == 9 and sv["ml_on_rules_missed"] == 3
    assert sv["health_min"] == 40.0 and sv["instant_below_50"] == 4
    sz = f["safety_zone"]
    assert sz["ml"] is None and sz["ml_sensor"] is False and sz["rows"] == 7
    assert sz["rules"]["delay_s"] == 0.0 and sz["first"] == "rules"
    assert f["leak"]["rows"] == 0
    t = res["totals"]
    assert (t["fault_rows"], t["ml_visible_fault_rows"], t["ml_rows"], t["rules_rows"]) == (17, 10, 3, 8)


def test_false_alarms_with_and_without_margin():
    tr, labels = crafted()
    fa = sr.evaluate_labels(tr, labels, sr.assign_kinds(tr, STEPS), ["vib_count"], margin_s=15)["false_alarms"]
    h = fa["hands_off"]
    # normal rows 2-19, 40-57, 70-89 = 18 + 18 + 20 = 56; within 15 s after a fault: 40-49 and 70-79
    assert (h["rows"], h["rows_excl_margin"]) == (56, 36)
    assert (h["ml"], h["ml_excl_margin"]) == (2, 0)          # 45 and 75 are both inside a margin
    assert fa["everyday"]["rows"] == 0


def test_forecast_lead():
    tr = [trace_row(i, "fault", warn_s=(30.0 if i >= 3 else None), dev="WARNING" if i >= 8 else "NORMAL")
          for i in range(12)]
    steps = [sr.Step(ts(0), "fault", "S9 temperature fingertip", "temperature")]
    fc = sr.forecast_lead(tr, sr.assign_kinds(tr, steps))
    assert fc["lead_s"] == 5.0 and fc["forecast_eta_s"] == 30.0 and fc["forecast_predicted_critical"] is False


def test_subtle_verdict_answers():
    def sets(hit_v, hit_s):
        return {"live": {"faults": [
            {"kind": "subtle_vibration", "subtle": True, "rows": 10, "rules": {"rows": 0}, "rules_missed": 10,
             "ml_on_rules_missed": hit_v, "ml": {"episodes": 1}, "episodes": 1, "health_min": 30, "instant_below_50": 1},
            {"kind": "subtle_sound", "subtle": True, "rows": 10, "rules": {"rows": 0}, "rules_missed": 10,
             "ml_on_rules_missed": hit_s, "ml": {"episodes": 0}, "episodes": 1, "health_min": 80, "instant_below_50": 0}]}}
    assert sr.subtle_verdict(sets(6, 5))["answer"] == "yes"
    assert sr.subtle_verdict(sets(6, 0))["answer"] == "partly"
    assert sr.subtle_verdict(sets(0, 0))["answer"] == "no"
    r = {"subtle": sr.subtle_verdict(sets(6, 0))}
    assert sr.subtle_sentence(r).startswith("Partly: ML flagged 6 of the 10 subtle-vibration rows")


def test_cli_session_report_end_to_end(tmp_path, registry):
    rows = rows_from([dict(CORE) for _ in range(90)], source="real")
    tr, labels = crafted()
    for r, t, lab in zip(rows, tr, labels):
        r.ts_iso, r.label = t["ts"], lab
        r.dev_state = t["dev_state"]
    cleaned = write_csv(tmp_path / "sess.csv", registry, rows)
    for r in rows:
        r.label = "fault" if r.label == "unknown" else r.label
    live = write_csv(tmp_path / "sess_live.csv", registry, rows)
    steps = tmp_path / "steps.tsv"
    steps.write_text("".join(f"{s.ts}\t{s.label}\t{s.name}\n" for s in STEPS), encoding="utf-8")
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps({"sessions": [{"file": "sess.csv", "role": "test", "sha256": roles.content_hash(cleaned),
                                                  "raw": [{"file": "raw/sess_live.csv"}]}]}), encoding="utf-8")
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    code = evaluate_cli.main([str(cleaned), "--steps", str(steps), "--live-labels", str(live), "--manifest", str(manifest),
                              "--model-dir", str(tmp_path / "nomodel"), "--json", str(out_json), "--md", str(out_md)])
    assert code == 0
    rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert rep["stamp"] == sr.STAMP and set(rep["label_sets"]) == {"cleaned", "live"}
    sv = {f["kind"]: f for f in rep["label_sets"]["live"]["faults"]}["subtle_vibration"]
    assert sv["rows"] == 20 and sv["ml"] is None            # no model: ML columns empty, rules still counted
    md = out_md.read_text(encoding="utf-8")
    assert sr.STAMP in md and "0 by construction" in md and "(b) is the fairer comparison" in md
    # The live labels must come from the same session
    other = write_csv(tmp_path / "other.csv", registry, rows)
    assert evaluate_cli.main([str(cleaned), "--steps", str(steps), "--live-labels", str(other), "--manifest", str(manifest),
                              "--model-dir", str(tmp_path / "nomodel")]) == 2
