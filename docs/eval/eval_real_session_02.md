# Evaluation on the held-out test session: REAL DATA - held-out test session

> **REAL DATA - held-out test session.** Session 02 was recorded for testing only (role `test` in `data/recordings/MANIFEST.json`) and was never used for training, validation or any choice. It was run through the chosen model **once**.

Created 2026-10-24T17:11:27+05:30 by `backend/scripts/evaluate.py` (`app/ml/session_report.py`). The same numbers are in `eval_real_session_02.json`, shown in the dashboard's Model panel.

## What was evaluated

- **Session:** `real_session_02_test_20261024.csv` (cleaned labels) and `raw/raw_session_20261024_153633.csv` (the same rows with the labels as set live); steps from `session_02_steps.tsv`. 1993 rows, one per second.
- **Model:** bench-trained on real data (session 01); created 2026-10-24T16:50:46+05:30; trained on 868 real + 0 synthetic normal rows (real_session_01_20261024.csv); ML sensors temp_c, humidity, sound_peak, vib_count, 16 features.
- **How:** every row went through the live pipeline (`Pipeline.process`): the device-rule mirror, the ML score with the dashboard's smoothing (ANOMALY after 3 rows below 50, clears after 5 rows above 60) and the trend forecast. **Rules** = the board's own `dev_state` is WARNING or CRITICAL (this drives the buzzer). **ML** = the smoothed ML status is ANOMALY.

## Two label sets

- **(a) cleaned labels** (`real_session_02_test_*.csv`). The clean-up (`data/recordings/raw/clean_session_02.py`) **used the device state**: a `normal` row where the board was not NORMAL became `unknown`, and the subtle steps kept only rows where the board stayed NORMAL. So with the cleaned labels the rules' false-alarm rate on normal rows is **0 by construction**, and the rules catch **0 subtle-fault rows by construction**. These labels say what each row physically was, but they are not a fair referee between rules and ML.
- **(b) live labels** (`raw/raw_session_*.csv`), as switched by hand during the session. They do not depend on what the device did, so **(b) is the fairer comparison of rules vs ML**. They are looser: a fault label also covers the quiet seconds before and after the action, and the normal gaps include accidental bumps.

## Results per fault: rules vs ML

Each cell: flagged rows of the fault rows; episodes caught (a flag inside the episode or up to 3 s after it); delay from the fault's first row to the first flag.

| Fault | (a) cleaned labels: rules | (a) cleaned labels: ML | (b) live labels: rules | (b) live labels: ML |
|---|---|---|---|---|
| Subtle vibration (light taps, below the limit) | 0 of 35 rows; 4 of 4 ep.; after 3 s | 23 of 35 rows; 4 of 4 ep.; after 5 s | 21 of 71 rows; 1 of 1 ep.; after 17 s | 39 of 71 rows; 1 of 1 ep.; after 19 s |
| Subtle sound (music, humming, below the limit) | 0 of 36 rows; 1 of 17 ep.; after 70 s | 27 of 36 rows; 16 of 17 ep.; after 11 s | 10 of 301 rows; 1 of 1 ep.; after 207 s | 90 of 301 rows; 1 of 1 ep.; after 148 s |
| Strong vibration (firm knocks) | 29 of 29 rows; 1 of 1 ep.; after 0 s | 27 of 29 rows; 1 of 1 ep.; after 2 s | 37 of 43 rows; 1 of 1 ep.; after 6 s | 35 of 43 rows; 1 of 1 ep.; after 8 s |
| Loud claps | 11 of 11 rows; 1 of 1 ep.; after 0 s | 9 of 11 rows; 1 of 1 ep.; after 2 s | 15 of 26 rows; 1 of 1 ep.; after 5 s | 19 of 26 rows; 1 of 1 ep.; after 7 s |
| Safety zone (hand near the HC-SR04) | 28 of 29 rows; 1 of 1 ep.; after 1 s | not an ML sensor | 30 of 40 rows; 1 of 1 ep.; after 0 s | not an ML sensor |
| Water leak (+ arm in the safety zone) | 37 of 37 rows; 1 of 1 ep.; after 0 s | not an ML sensor | 37 of 40 rows; 1 of 1 ep.; after 3 s | not an ML sensor |
| Temperature (fingertip on the DHT11) | 53 of 69 rows; 2 of 2 ep.; after 16 s | 67 of 69 rows; 2 of 2 ep.; after 0 s | 59 of 100 rows; 1 of 1 ep.; after 41 s | 87 of 100 rows; 1 of 1 ep.; after 0 s |

A rules cell with **0 rows but caught episodes** means the board alarmed on a row next to the episode (within the grace time) that is not a fault row of this label set, e.g. an over-limit tap that the clean-up labelled unknown.

**Which raised the alarm first:**

- (a) cleaned labels: subtle vibration: rules, subtle sound: ml, strong vibration: rules, claps: rules, safety zone: rules, leak: rules, temperature: ml
- (b) live labels: subtle vibration: rules, subtle sound: ml, strong vibration: rules, claps: rules, safety zone: rules, leak: rules, temperature: ml

**Totals:**

- (a) cleaned labels: rules flagged 158 of 246 fault rows (11 of 27 episodes). On the faults ML can see: rules 93, ML 153 of 180 rows; ML caught 24 of 25 episodes.
- (b) live labels: rules flagged 209 of 621 fault rows (7 of 7 episodes). On the faults ML can see: rules 142, ML 270 of 541 rows; ML caught 5 of 5 episodes.

## Did ML catch the subtle faults the rules missed?

**Answer: PARTLY.** ML flagged 24 of the 50 subtle-vibration rows the rules missed and 82 of the 291 subtle-sound rows the rules missed (live labels); 23 of the 35 subtle-vibration rows the rules missed and 27 of the 36 subtle-sound rows the rules missed (cleaned labels).

| Label set | Subtle fault | Fault rows | Rules flagged | Rows the rules missed | ML flagged of those | ML episodes | Lowest health | Rows with health < 50 (before smoothing) |
|---|---|---|---|---|---|---|---|---|
| (a) cleaned labels | subtle vibration | 35 | 0 | 35 | 23 | 4 of 4 | 0 | 10 |
| (a) cleaned labels | subtle sound | 36 | 0 | 36 | 27 | 16 of 17 | 27 | 25 |
| (b) live labels | subtle vibration | 71 | 21 | 50 | 24 | 1 of 1 | 0 | 28 |
| (b) live labels | subtle sound | 301 | 10 | 291 | 82 | 1 of 1 | 0 | 76 |

## False alarms on normal rows

Flagged normal rows **excluding** the 15 s after a fault (window + hold: after-effects by design) / **including** them.

| Label set | Normal rows | Rules | ML | ML health median (excl. margin) |
|---|---|---|---|---|
| (a) cleaned labels | Hands-off normal (steps 1, 10 and the gaps) | 0 of 746 (0.0 %) / 0 of 760 (0.0 %) | 37 of 746 (5.0 %) / 46 of 760 (6.1 %) | 100 |
| (a) cleaned labels | Everyday activity (step 2) | 0 of 152 (0.0 %) / 0 of 152 (0.0 %) | 16 of 152 (10.5 %) / 16 of 152 (10.5 %) | 100 |
| (b) live labels | Hands-off normal (steps 1, 10 and the gaps) | 24 of 799 (3.0 %) / 29 of 874 (3.3 %) | 71 of 799 (8.9 %) / 104 of 874 (11.9 %) | 100 |
| (b) live labels | Everyday activity (step 2) | 10 of 172 (5.8 %) / 10 of 172 (5.8 %) | 24 of 172 (14.0 %) / 24 of 172 (14.0 %) | 100 |

## Temperature step: did the forecast warn early?

- The forecast first predicted the WARNING limit at 16:02:43 (temperature 30.2 °C, WARNING predicted in 279.2 s); the board reached WARNING at 16:03:17 (32.3 °C).
- **Lead time: 34 s** (the forecast warned first).
- The forecast did predict the CRITICAL limit (35 °C) within its horizon during the step; 35 °C was not reached.
- Forecast warnings outside the temperature step and its cool-down: 114 of 1736 rows.

## Faults ML cannot be expected to catch

ML uses only temp_c, humidity, sound_peak, vib_count (registry: enabled AND include_in_ml). The **leak** and **safety-zone** faults change only `leak_raw` and `distance_cm`, which are rule-only sensors, so the ML columns say "not an ML sensor" and they are not counted as ML misses. Temperature and humidity enter ML only by how fast they change (`ml_stats`: std, slope), so a slow, steady temperature rise is a job for the rules and the forecast.

## Definitions

All counts are rows of 1 s; a row counts once its 10 s ML window is full.

- **Rules flag:** the board's own `dev_state` is WARNING or CRITICAL (what drives the buzzer).
- **ML flag:** the smoothed ML status is ANOMALY (what the dashboard shows).
- **Fault kind:** the fault step a fault row belongs to; a fault row inside a gap belongs to the next fault step (step 7 started 8 s before its label switch).
- **Delay:** seconds from the first fault row of a kind to the first flag at or after it, up to the last fault row + 15 s.
- **Episode:** a run of consecutive fault rows; caught if a flag falls inside it or up to 3 s after it (ML needs 3 rows below 50 before it says ANOMALY).
- **False alarm:** a flag on a normal row; "excluding" leaves out normal rows up to 15 s after a fault row of the same label set (after-effects by design).

Interpretation, the limit suggestions and every decision: `docs/phase8_report.md`.
