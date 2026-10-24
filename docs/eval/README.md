# Evaluation reports

`backend/scripts/evaluate.py` writes its reports here.

- **Valid results** come only from **real** recordings (`source=real`) that contain an
  induced fault marked with `label=fault`. The script refuses to run otherwise.
- Reports made with `--dev-synthetic` are named `*_SIMULATED.md`, stamped
  **"SIMULATED DATA - NOT A RESULT"** on every line, and kept out of git
  (`.gitignore`). They are development checks only and must never be presented as results.

- **Data roles** (`data/recordings/MANIFEST.json`, enforced in code): final numbers only from
  `test` sessions or unlisted recordings; a `train` session is refused. `--validation`
  accepts only `train` sessions (stamped VALIDATION) and is for choices during development.
- Every row runs through the live pipeline (device-rule mirror, smoothed ML, forecast).

```
cd backend
python scripts/evaluate.py ../data/recordings/session_*.csv          # real results
python scripts/evaluate.py --dev-synthetic "../data/synthetic/devfault_*.csv"   # dev check only
python scripts/evaluate.py ../data/recordings/real_session_02_test_20261024.csv     --steps ../data/recordings/raw/session_02_steps.tsv     --live-labels ../data/recordings/raw/raw_session_20261024_153633.csv     --json ../docs/eval/eval_real_session_02.json --md ../docs/eval/eval_real_session_02.md
```

## Files here (Phase 8.2)

| File | What |
|---|---|
| `eval_real_session_02.md` / `.json` | **REAL DATA - held-out test session.** The shipped model on session 02, run once: per fault rules vs ML (counts, episodes, delays), both label sets, the subtle-fault verdict, false alarms, forecast lead. The JSON feeds the dashboard's Model panel (`GET /api/model/evaluation`) and is bundled in the exe. |
| `phase8_validation.json` | Model selection on session 01 only (`scripts/select_model.py`): candidates (a) real / (b) real + synthetic, the rule, the choice, the calibration check |
| `phase8_b4_review.json` | The first selection run (all 24 features) and the variants tried in the calibration review |

Re-running the session 02 evaluation with a different model is fine (it is evaluation, not
training), but the test session must never be used to choose anything: a new choice needs a
new held-out recording.

Each report lists the files used, row counts by source and label, the model's
provisional flag, and per detector (ML, rules, rules CRITICAL only, forecast): detection
rate, false alarm rate, episodes detected and mean detection delay, plus a per-episode
table.

**False alarm margin.** The main false alarm rate leaves out the normal windows in the
first window + hold seconds (10 + 5 = 15 s) after each fault period ends. For that long
the ML window still contains fault values and the device rules are still holding their
state by design, so a flag there is an after-effect of the real fault, not a false alarm.
The raw rate, which counts them, is reported next to it.
