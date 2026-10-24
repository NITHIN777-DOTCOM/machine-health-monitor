# Phase 8.2 report: real-data model, held-out evaluation, Model panel, release v0.8.0

Date: 2026-10-24. Written for the presenters: what was done, the numbers, and why each
choice was made. Short version:

- The ML model is now **trained on real bench data** (session 01, 868 normal rows, no
  simulated data). It is no longer "provisional", but it is a **bench** model: a real machine
  needs its own normal data and a retrain (DATA_CONTRACT §8).
- On the **held-out test session 02** (never used for any choice, run once) ML catches
  **part** of the subtle faults the threshold rules miss, and raises more false alarms than
  the rules. The rules stay the safety layer; ML stays advisory (it can never make CRITICAL).
- The dashboard has a new **Model** panel that shows these results.
- Release: [v0.8.0 - real-data model](https://github.com/NITHIN777-DOTCOM/machine-health-monitor/releases/tag/v0.8.0) (pre-release).

## 1. Data and roles

| Session | Role | Rows | Labels (cleaned) normal / fault / unknown | Live labels |
|---|---|---|---|---|
| `real_session_01_20261024.csv` (Phase 7.2 HIL) | **train** | 3408 | 868 / 686 / 1854 | 1059 / 1668 / 681 |
| `real_session_02_test_20261024.csv` (Phase 8.1) | **test** (held out) | 1993 | 921 / 246 / 826 | 1055 / 621 / 317 |

- **Raw originals kept** (8.2a): session 01's six original parts and session 02's raw file
  (labels as switched live) are in `data/recordings/raw/`, listed in `MANIFEST.json` (schema 2,
  sha256 per file) as `raw` variants of their session. They inherit the session's role, so a
  raw test file is just as forbidden for training as the cleaned one.
- **Roles enforced in code** (`backend/app/ml/roles.py`, tests `test_data_roles.py`):
  - `train.py` accepts only `train` sessions (strict: an unlisted real file is refused too);
    the dashboard's retrain job refuses `test` sessions.
  - `evaluate.py` refuses `train` files for final numbers. `--validation` accepts only
    `train` files and stamps the output VALIDATION.
  - Files are matched by name **and** by content hash, so a renamed copy is still recognised.
- **Training labels**: only `label=normal` rows. Session 01's cleaned normal labels still
  contain some table bumps (vibration 13-40) and the cool-down after its temperature fault.
  They were deliberately **not re-cleaned** (see §3).

## 2. Candidates and the selection rule

The rule was written into `backend/scripts/select_model.py` and **committed (1e42c3f) before
any candidate was trained**:

> FA = held-out normal rows (outside the 15 s after-fault margin) flagged ANOMALY by the
> smoothed ML; DET = session 01 fault rows flagged ANOMALY. 1) acceptable if FA <= 2 %.
> 2) both acceptable: higher DET wins, (a) real-only if DET differs by < 2 points. 3) one
> acceptable: that one. 4) neither: lower FA, then review the calibration.

- **Validation split:** the last 20 % (by time) of session 01's normal rows (174 rows from
  12:04:46) plus all of session 01's fault rows. Session 02 played no part.
- **Candidates** (IsolationForest, 200 trees, contamination 0.01, 10 s windows; ML sensors
  temp_c, humidity, sound_peak, vib_count):
  - **(a)** real normal rows only (694 rows);
  - **(b)** real + synthetic (`generate_synthetic.py --from-real`, 3600 rows).

| Run | Candidate | False alarms (FA) | Detection (DET) | Episodes | Median health (held-out normal) | Below 50 |
|---|---|---|---|---|---|---|
| First run, 24 features | (a) real only | 124 of 170 (72.9 %) | 570 of 685 (83.2 %) | 7 of 8 | 53.5 | 19.5 % |
| First run, 24 features | (b) real + synthetic | 156 of 170 (91.8 %) | 632 of 685 (92.3 %) | 7 of 8 | - | - |
| **Final, 16 features** | **(a) real only** | **42 of 170 (24.7 %)** | **392 of 685 (57.2 %)** | 7 of 8 | **100** | 17.8 % |
| Final, 16 features | (b) real + synthetic | 59 of 170 (34.7 %) | 262 of 685 (38.2 %) | 7 of 8 | 87.3 | 31.0 % |

- Both runs: neither candidate met FA ≤ 2 %, so step 4 picked the lower FA → **(a), real
  only**.
- For reference on the same validation rows: the rules caught 595 of 685 fault rows, and
  ML flagged 51 of the 90 fault rows the rules missed.
- The full numbers are in `docs/eval/phase8_validation.json` and `docs/eval/phase8_b4_review.json`.

## 3. Calibration check (and the one change it caused)

- **Target:** median health ≥ 90 and ≤ 2 % of the held-out normal rows below 50.
- **First run: failed** (median 53.5).
- **Diagnosis, on validation rows only:** the held-out minutes were warmer (to 31.3 °C) and
  drier (to 71 %RH) than the training minutes. The temperature and humidity **level**
  features fell outside the training range, the range term pulled health to 50-60, and the
  smoothing latched ANOMALY.
- **Lowering the contamination to 0.005 changed nothing** (identical numbers).
- **Change made:** a new registry field `ml_stats`. Temperature and humidity now enter ML only
  by **how fast they change** (std, slope), not by their level: `sensors.json`
  `"ml_stats": ["std","slope"]`, 16 features instead of 24.
  - The temperature level stays with the rules and the forecast.
  - A model whose features don't match the registry's `ml_stats` reports NEEDS_RETRAIN.
  - Variant tried and rejected: humidity changes only (V3), with median 54.6.
- **Re-run of both candidates** with that feature set, **same rule** → (a) again.
- **Result:** median health **100 ✓**, but **17.8 % below 50 ✗** (target ≤ 2 %).
- **Why it still fails, and why it was left so:**
  - The remaining flags on held-out normal rows are the table bumps (vibration 13-40) left
    in session 01's normal labels, plus the cool-down after its temperature fault. On the
    quiet normal rows alone, ML flagged 8 of 116.
  - Calibrating these away would mean teaching the model that vibration 13-40 is normal,
    which would blind it to exactly the subtle vibration it is meant to catch. So they
    were not tuned away.
- **Final fit:** the chosen recipe refit on **all 868** normal rows of session 01, the 20 %
  holdout included (it holds the session's warmest, driest minutes, which the shipped model
  should know). The validation numbers describe the 80 % fit; §4 describes the shipped model.
- **Model meta** (`models/model_meta.json`):
  - `provisional: false`;
  - status "bench-trained on real data (session 01)";
  - `trained_on` 868 real + 0 synthetic rows;
  - the selection block (rule, choice, why);
  - deployment_note "trained on a bench setup; a real machine needs its own normal data and
    a retrain".

## 4. Evaluation on the held-out test session 02 (run once)

Full report: [`docs/eval/eval_real_session_02.md`](eval/eval_real_session_02.md), stamped
**REAL DATA - held-out test session**; the same numbers are in `.json`, served by
`GET /api/model/evaluation` and shown in the Model panel.

- **Method:** every row ran through the live pipeline (device-rule mirror, ML with the
  dashboard's smoothing, forecast).
  - **Rules** = the board's own `dev_state` is WARNING or CRITICAL.
  - **ML** = the smoothed ML status is ANOMALY.
- **Two label sets:**
  - **(a) cleaned labels:** the clean-up used the **device state**, so the rules have 0 false
    alarms and catch 0 subtle-fault rows **by construction**.
  - **(b) live labels:** as switched by hand. They do not depend on the device, so **(b) is
    the fairer comparison**. They are also looser: a fault label covers the quiet seconds
    around the action, and the gaps include accidental bumps.

### Rules vs ML per fault (flagged rows of fault rows; delay to the first flag)

| Fault | (a) Rules | (a) ML | (b) Rules | (b) ML | First (both sets) |
|---|---|---|---|---|---|
| Subtle vibration (light taps, below the limit) | 0 of 35 (4 of 4 ep. via adjacent over-limit taps) | **23 of 35**, after 5 s | 21 of 71, after 17 s | **39 of 71**, after 19 s | rules |
| Subtle sound (music, humming, below the limit) | 0 of 36 | **27 of 36**, after 11 s (16 of 17 ep.) | 10 of 301, after 207 s | **90 of 301**, after 148 s | ML |
| Strong vibration (firm knocks) | 29 of 29, at once | 27 of 29, after 2 s | 37 of 43, after 6 s | 35 of 43, after 8 s | rules |
| Loud claps | 11 of 11, at once | 9 of 11, after 2 s | 15 of 26, after 5 s | 19 of 26, after 7 s | rules |
| Safety zone (HC-SR04) | 28 of 29, after 1 s | not an ML sensor | 30 of 40, at once | not an ML sensor | rules |
| Water leak | 37 of 37, at once | not an ML sensor | 37 of 40, after 3 s | not an ML sensor | rules |
| Temperature (fingertip on the DHT11) | 53 of 69, after 16 s | **67 of 69, at once** | 59 of 100, after 41 s | **87 of 100, at once** | ML |

### Subtle-fault verdict: **PARTLY**

- With live labels, ML flagged **24 of the 50** subtle-vibration rows the rules missed and
  **82 of the 291** subtle-sound rows the rules missed.
- With cleaned labels, it flagged **23 of 35** and **27 of 36**.
- ML noticed every subtle episode except one, but it covers only part of each.
- The live subtle-sound label (301 rows) includes long stretches of quiet humming that
  neither rules nor ML could hear.

### False alarms on normal rows (excluding / including the 15 s after a fault)

| Label set | Normal rows | Rules | ML |
|---|---|---|---|
| (a) cleaned | Hands-off | 0 of 746 (0 %) | 37 of 746 (5.0 %) / 46 of 760 (6.1 %) |
| (a) cleaned | Everyday activity | 0 of 152 (0 %) | 16 of 152 (10.5 %) |
| (b) live | Hands-off | 24 of 799 (3.0 %) / 29 of 874 (3.3 %) | 71 of 799 (8.9 %) / 104 of 874 (11.9 %) |
| (b) live | Everyday activity | 10 of 172 (5.8 %) | 24 of 172 (14.0 %) |

Where the 37 cleaned hands-off ML false alarms came from (diagnosis after the run; nothing
was changed because of it):

- 15 rows: one 0.1 °C DHT11 step at 15:38:10 (training temperature std is ~0, so a single
  step looks unusual);
- 17 rows: windows that overlap nearby `unknown` disturbances;
- 5 rows: the temperature fault's onset at 16:02:31;
- 1 row: other.

### Forecast lead on the temperature step: **34 s**

- The forecast first predicted WARNING at 16:02:43, when the temperature was 30.2 °C (the
  rise began at 16:02:30).
- The board reached WARNING at 16:03:17, at 32.3 °C. It also predicted CRITICAL (35 °C),
  which was not reached.
- **Caveat:** it also predicted a warning on 114 of the 1736 rows outside the step. These
  were 0.1 °C DHT11 steps at 15:38:21, 15:49:32 and 15:57:05, which a 60 s linear fit
  extrapolates.
- The simulator's slow temperature wander has the same effect ("warning in ~9 min" in normal
  simulation). This is a known limit of the forecast, not changed in this phase.

### Leak and safety zone

`leak_raw` and `distance_cm` are rule-only sensors (not in ML), so they are excluded from
the ML columns and not counted as ML misses.

## 5. Limit suggestions (REPORT ONLY, nothing changed)

From session 01 only (the train session); session 02 was not used. The limits in
`sensors.json` are unchanged.

| Sensor | Now (warn / crit) | Session 01 normal | Suggestion |
|---|---|---|---|
| Sound peak | 40 / 120 | max 8, p99 5 | warn ~20: 39 fault rows sat between the normal max and 40 |
| Temperature | 32 / 35 | warmest normal 31.3 °C | warn ~33: only 0.7 °C margin now; would need the room checked first |
| Leak | 50 / 200 | ≤ 9 | warn ~30 (18 fault rows between) |
| Vibration | 50 / 100 | bumps up to 40 | keep (5 fault rows between) |
| Distance (below) | 20 / 10 | people at 37 cm | keep |
| Humidity | none | 71-80 %RH | keep "no limits" |

Changing a limit means `gen_firmware_config.py` + reflashing + a new test session, so this
is left as a decision for the team.

## 6. Model panel (dashboard)

- A new **Model** button opens a drawer next to Controls (only one drawer is open at a time).
- **What the model learned:** the status line, real/simulated row counts, the session, the
  date, the sensors (temperature and humidity marked "changes only"), the method, and the
  deployment note.
- **Test on unseen data:**
  - the stamp;
  - a Live/Cleaned label toggle (live = "fairer");
  - the rules-vs-ML table with counts and delays;
  - the one-sentence verdict;
  - the false-alarm table;
  - the forecast sentence;
  - a chart of the subtle vibration step: vibration, warn limit, ML health, ML and rules
    markers, and the fault rows shaded.
- If the bundled evaluation belongs to a different model (`created` differs), the panel says
  so instead of claiming the numbers.
- The ML card's tag reads **"bench-trained model"** (tooltip: the status and the deployment
  note). A provisional model still shows "provisional model". The footer shows the status
  line.
- Screenshots: `docs/screenshots/phase8/` (1366x768 and 1920x1080, light and dark, the drawer
  in full, the cleaned-label view, the ML card tag); `npm run screenshots:model`.

## 7. Live check (Part E)

**Skipped at the user's request.** The model was checked on real data only through the
offline replay of session 02, not with the board live.

## 8. Release v0.8.0

- `build.bat`: all tests, PyInstaller onedir, zip.
- The exe bundles the model and the evaluation JSON.
- `firmware/machine_monitor/` (v1.0.2) is in the release folder.
- The portability test of the extracted zip is described in the release notes.
- [GitHub pre-release "v0.8.0 - real-data model"](https://github.com/NITHIN777-DOTCOM/machine-health-monitor/releases/tag/v0.8.0)

## 9. Decisions and changes, in one list

1. **Selection rule fixed before any result** (committed in 1e42c3f); not changed after the
   first run.
2. **Temperature and humidity in ML by change only** (`ml_stats`), decided on session 01
   validation rows only (B4 review, written into select_model.py's docstring). The rule was
   re-applied unchanged.
3. **Calibration not forced to target:** the bumps in session 01's normal labels were not
   re-cleaned or calibrated away (§3).
4. **Final model refit on all session 01 normal rows** after selection.
5. **Session 02 run once**; nothing was changed after seeing it. The diagnosis of its false
   alarms (§4) is for the record.
6. **Simulator retuned to look like the bench** (`sim_profile.json`): the real-data model
   flagged the old simulated "normal" almost 100 % ANOMALY. New baselines: temp 29.9 °C with
   no noise, humidity 78, sound 3.4, vibration ~0, leak 5.5, distance 154. Simulated normal
   now reads health ~100. The simulator is still never used for any number in this report.
7. **Limit suggestions are report only** (§5).
8. **Tests whose expectations changed because the spec changed:**
   - 24 → 16 features;
   - the shipped model is no longer provisional;
   - the "vibration 13 → health ~35" test now trains its own model on the old synthetic
     profile, because the real model sees vibration differently.
9. **Live check (E) skipped** at the user's request.

## 10. Uncertainties

- **Small test set:** one session, one person, one bench. The subtle steps are 35-71 rows
  (cleaned) / 71-301 rows (live). Treat the counts as indications, not rates.
- **ML false alarms are higher than the rules'** (5-14 % of normal rows vs 0-6 %). That is
  acceptable only because ML is advisory and can't make CRITICAL.
- **The training labels contain bumps**, so the model's idea of "normal" is a little noisy.
- **The DHT11's 0.1 °C steps** trigger both ML (temperature std) and the forecast.
- **The model knows this bench only.** Room temperature and humidity change by the day;
  another room or a real machine needs new normal data and a retrain.
- Exe auto-detection with the Uno plugged in is still not verified in a portability test.
