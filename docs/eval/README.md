# Evaluation reports

`backend/scripts/evaluate.py` writes its reports here.

- **Valid results** come only from **real** recordings (`source=real`) that contain an
  induced fault marked with `label=fault`. The script refuses to run otherwise.
- Reports made with `--dev-synthetic` are named `*_SIMULATED.md`, stamped
  **"SIMULATED DATA - NOT A RESULT"** on every line, and kept out of git
  (`.gitignore`). They are development checks only and must never be presented as results.

```
cd backend
python scripts/evaluate.py ../data/recordings/session_*.csv          # real results
python scripts/evaluate.py --dev-synthetic "../data/synthetic/devfault_*.csv"   # dev check only
```

Each report lists the files used, row counts by source and label, the model's
provisional flag, and per detector (ML, rules, rules CRITICAL only, forecast): detection
rate, false alarm rate, episodes detected and mean detection delay, plus a per-episode
table.

**False alarm margin.** The main false alarm rate leaves out the normal windows in the
first window + hold seconds (10 + 5 = 15 s) after each fault period ends. For that long
the ML window still contains fault values and the device rules are still holding their
state by design, so a flag there is an after-effect of the real fault, not a false alarm.
The raw rate, which counts them, is reported next to it.
