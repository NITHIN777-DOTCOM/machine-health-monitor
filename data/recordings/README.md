# Real recordings

Only **real** sensor data recorded from the Arduino lives here (stored column order from
`docs/DATA_CONTRACT.md` §5). `MANIFEST.json` lists every file with its **role**; the test
`backend/tests/test_recordings_manifest.py` fails if a file is missing from it or its counts drift.

| File | Role | Rows | normal / fault / unknown | What it is |
|---|---|---|---|---|
| `real_session_01_20261024.csv` | **train** | 3408 | 868 / 686 / 1854 | Phase 7.2 hardware-in-the-loop test (`firmware/tests/HIL_RESULTS.md`) |
| `real_session_02_test_20261024.csv` | **test** | 1993 | 921 / 246 / 826 | Phase 8.1 held-out test session (below) |

**Roles.** `train` data may be used to train the model and tune thresholds. `test` data is
**held out**: evaluation only, never for training, choosing limits or thresholds. That way the
Phase 8.2 evaluation is on data the model has never seen.

**The roles are enforced in code** (`backend/app/ml/roles.py`, tests in `test_data_roles.py`).
Files are matched by name and by content hash (`sha256` in the manifest, line endings
normalised), so a renamed copy keeps its role:

| Tool | Rule |
|---|---|
| `scripts/train.py`, `generate_synthetic.py --from-real` | every file with real rows must be a `train` session; `test` files, renamed copies and unlisted real recordings are refused |
| `POST /api/model/train` (dashboard retrain) | `test` files refused; unlisted recordings allowed (a deployed machine's own new data) |
| `scripts/evaluate.py` (final test numbers) | `train` sessions refused (the model has seen them) |
| `scripts/evaluate.py --validation` | `train` sessions only, so the test session cannot influence a choice |

## `raw/`: the original, live-labelled files

The cleaned files above have their labels tidied after the session (rules below and in
`firmware/tests/HIL_RESULTS.md`). The originals are kept, **with the labels as they were set
live**, so the clean-up can be checked and the evaluation can be repeated on the live labels.
The manifest lists them as `raw` variants of their session (same role); the sensor rows are
identical, only `label` differs (`test_recordings_manifest.py` checks this).

| File | Session | Rows | Live labels normal / fault / unknown |
|---|---|---|---|
| `raw/session_20261024_105214.csv` … `raw/session_20261024_120014.csv` (6 parts) | 01 (train) | 3408 | 1059 / 1668 / 681 |
| `raw/raw_session_20261024_153633.csv` | 02 (test) | 1993 | 1055 / 621 / 317 |
| `raw/session_02_steps.tsv` | 02 | | the live step log: time, label, step name (used by the per-step evaluation) |
| `raw/clean_session_02.py` | 02 | | the clean-up script that produced `real_session_02_test_20261024.csv` from the raw file |

Training never reads `raw/`: the training session's cleaned labels are the stricter ones.

## Session 02: held-out test (Phase 8.1, 2026-10-24, 15:36–16:09)

Uno on COM5, firmware `machine_monitor v1.0.2`, dev backend on serial, dashboard open.
33 min, 1 row/s, **0 rejected rows, no gaps in the device clock, no empty fields.**
Room: 29.8–30.3 °C, 79–84 %RH. No model was trained or evaluated.

The session includes two **subtle faults that stay below the rule limits** (steps 3 and 4),
to test whether ML notices anything the threshold rules cannot.

### Protocol and results

Ranges are over the final `fault` rows of the step (for normal steps: the `normal` rows).
"Device" is the board's own `dev_state`.

| # | Step | Label | Time | Final rows | Sensor ranges | Device | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Normal, hands off, 3 min | normal | 15:36:33 | 179 normal | T 29.8–30.2, H 80–82, sound 3–4, vib 0, leak 3–9, dist 146–147 | NORMAL 188/188 | 2 distance blips (57, 71 cm: a person in the sensor's view) and one sound 10 → unknown |
| 2 | Everyday activity, 2 min (typing, quiet talk, walking near the table) | normal | 15:39:42 | 151 normal | T 30.2–30.3, H 79–80, sound 3–4, vib 0–6, dist 38–147 | NORMAL 161, WARNING 10 | Typing and talk: no effect on sound. Walking: distance 22–88 cm, stays normal. Two accidental table bumps (vib 88 at 15:40:24, 76 at 15:41:33 → WARNING) and a brush (vib 24) → unknown |
| 3 | **Subtle vibration**: light taps on the table 20–30 cm from the breadboard | fault | 15:43:42 | 35 fault | vib 2–32 (live 0–260), others baseline | NORMAL on all 35 fault rows | Three taps went over the limit (258–260 → CRITICAL, 72 and 52 → WARNING): those rows and their holds → unknown |
| 4 | **Subtle sound**: phone music, then louder/closer humming | fault | 15:48:19 | 36 fault | sound 6–18 (live 3–268) | NORMAL on all 36 fault rows | The microphone barely hears music at 50 cm: 230 of 301 rows read the silent 3–5 → unknown (only audible rows ≥ 6 stay fault). One spike 268 at 15:51:47 (CRITICAL 5 s, WARNING 5 s) → unknown |
| 5 | Strong vibration: firm knocks | fault | 15:54:54 | 29 fault | vib 0–619, leak 0–25 | CRITICAL 24, WARNING 5 | As expected. One knock (vib 72) also moved leak to 25 |
| 6 | Loud claps (5) | fault | 15:56:44 | 11 fault | sound 3–301, vib ≤ 4 | CRITICAL 9, WARNING 2 | As expected, table not touched |
| 7 | Safety zone: hand ~15 cm, then ~5 cm, from the side | fault | 15:57:59 | 29 fault | dist 11–22.7 (WARNING), 3–8 (CRITICAL) | WARNING 17, CRITICAL 11 | Started 8 s before the label switch: 15:57:59–15:58:07 relabelled fault. Recovery 9 s |
| 8 | Water leak: wet finger, then drops | fault | 15:59:53 | 37 fault | leak 0–635 (wet 417–635) | CRITICAL 31, WARNING 6 | The arm also crossed the safety zone (8–17 cm) several times: this step mixes leak and distance faults |
| – | Drying with a tissue | unknown | 16:00:34 | 52 unknown | leak back < 20 by 16:01:01 | | The tissue/hand sat 2 cm in front of the HC-SR04 (CRITICAL) |
| 9 | Temperature: fingertip on the DHT11, 90 s | fault | 16:02:36 | 69 fault | T 31.3–33.8 (baseline 30.2), H 70–83 | WARNING 53, NORMAL 16 | Peak 33.8 °C (WARNING ≥ 32 at 16:03:23, CRITICAL 35 not reached). A bump at 16:03:58 (vib 146 → CRITICAL) → unknown |
| – | Cool-down | unknown | 16:04:16 | 148 unknown | T 33.8 → 30.2 in 2.3 min | WARNING → NORMAL 16:05:3x | |
| 10 | Normal, hands off, 3 min | normal | 16:06:44 | 181 normal | T 29.8–30.2, H 79–82, sound 3, vib 0, leak 4–8, dist 145–146 | NORMAL 186/186 | Distance blips at the start (62–87 cm) → unknown |

Between steps: hands-off gaps labelled normal (60 s, or 30 s after a restart). Three gaps were
disturbed (the table handled, a phone being placed, music still on after STOP) and were
switched to `unknown` live, then restarted. The gap after step 4 is unknown as a whole (the
music was still on after STOP: sound 10–32).

**Final counts: 1993 rows = 921 normal, 246 fault, 826 unknown**
(as labelled live: 1055 normal, 621 fault, 317 unknown).
Fault rows per kind: subtle vibration 35, subtle sound 36, strong vibration 29, sound 11,
safety zone 29, leak (+ distance) 37, temperature 69.

### Label clean-up (same rules as session 01, HIL_RESULTS.md §Recording)

The label was switched by hand (`POST /api/label`); a switch takes effect from the next row.
1. **normal → unknown** for disturbed rows ±1 row: device not NORMAL (incl. holds after a fault),
   vibration ≥ 10, sound ≥ 10, leak ≥ 20, distance < 100 cm (step 2: < 25 cm, since walking near
   the table is that step's activity), or an empty field. The whole gap after step 4 (music still on).
2. **Inside each fault step only the span from the first to the last induced deviation stays
   fault**, the lead-in and tail are unknown: vibration > 0 (step 3) or ≥ 10 (step 5), sound ≥ 20
   (step 6), distance < 25 cm (step 7), leak ≥ 20 or distance < 25 cm (step 8), temperature ≥
   baseline + 1 °C (step 9). The first row after a switch back to normal (still labelled fault) is unknown.
3. **Subtle steps keep only subtle rows:** step 3 rows with vibration ≥ 50 or the device not
   NORMAL are unknown. Step 4 keeps only rows with sound 6–39 and the device NORMAL (the
   silent rows did not hear the fault at all).
4. Step 7 started 8 s early: 15:57:59–15:58:07 (hand at 13–23 cm) is fault.
5. Step 9: rows with vibration ≥ 10 or CRITICAL (the bump) are unknown.

### Live label switches

| Time | Label | Why |
|---|---|---|
| 15:36:33 | normal | recording start, step 1 |
| 15:39:42 | normal | step 2 (everyday activity) |
| 15:42:33 | normal | gap |
| 15:43:42 | fault | step 3 subtle vibration |
| 15:44:53 | normal | gap |
| 15:45:35 | unknown | gap disturbed (table handled, phone being placed) |
| 15:46:25 | normal | gap restart |
| 15:46:56 | unknown | gap disturbed again (taps continued) |
| 15:47:41 | normal | gap restart |
| 15:48:19 | fault | step 4 subtle sound (louder/closer retry at 15:52:39) |
| 15:53:21 | normal | gap |
| 15:53:53 | unknown | gap disturbed (sound 15–32 after STOP) |
| 15:54:16 | normal | gap restart |
| 15:54:54 | fault | step 5 strong vibration |
| 15:55:37 | normal | gap |
| 15:56:44 | fault | step 6 claps |
| 15:57:09 | normal | gap |
| 15:58:07 | fault | step 7 safety zone |
| 15:58:47 | normal | gap |
| 15:59:53 | fault | step 8 leak |
| 16:00:34 | unknown | drying |
| 16:01:26 | normal | gap |
| 16:02:36 | fault | step 9 temperature |
| 16:04:16 | unknown | cool-down |
| 16:06:44 | normal | step 10 |
| 16:09:52 | – | recording stopped |

### Caveats for Phase 8.2

- **The subtle-sound set is small (36 rows, sound 6–18)**: this microphone module reads the
  silent 3 for music at 50 cm; it needs loud or close sound. Normal rows read sound 3–4, so even
  6–18 is a clear change for this sensor.
- The subtle-vibration fault rows include the zero-count seconds between taps (span rule).
- Step 8 is a mixed leak + safety-zone fault; step 9 reached WARNING only.
- Any hand on the table shows up as vibration (all accidental bumps are unknown). Normal rows:
  vibration 0–8, sound 3–4, distance ≥ 38 cm (step 2 walking), device NORMAL throughout.
