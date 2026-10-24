# Hardware-in-the-loop test (Phase 7.2, 2026-10-24)

The full system on the bench: Arduino Uno (genuine, COM5) running `machine_monitor`, the dev
backend on serial (`uvicorn app.main:app`), the dashboard open, every row logged.
For each test the label was switched to `fault` (`POST /api/label`) right before the fault
was induced and back to `normal` after full recovery (sensor-fault test: `unknown`).
**No model was trained or evaluated** (Phase 8).

Room: 29.3–31.3 °C, 71–80 %RH, quiet desk. Firmware v1.0.0 at the start, v1.0.2 at the end
(see Fixes). Parity test 71/71 after every firmware change.

## Results

| Test | What was done | Expected | Device state (actual) | LCD | Buzzer | Dashboard headline | Trigger | Recovery to NORMAL |
|---|---|---|---|---|---|---|---|---|
| Baseline | 2 min hands off | NORMAL | NORMAL, 120/120 rows | `NORMAL  T29.3C`, rotating `S.. V0 L..` / `Dist 157cm` | silent | "All systems normal" / ML text | – | – |
| Vibration calibration | 10 s light taps, 10 s firm knocks (old limits 20/60) | – | taps 3–48, knocks 37–312 | – | – | – | – | – |
| Vibration confirm (new limits 50/100) | light taps, firm knocks, very hard knocks | NORMAL / WARNING / CRITICAL | taps 2–49 NORMAL, knocks 51–87 WARNING, hardest 109–236 CRITICAL | as expected | (v1.0.0: silent, see Fixes) | as expected | immediate | CRITICAL → WARNING → NORMAL, 5 s each |
| 4a sound | 5–6 loud claps over ~10 s | WARNING/CRITICAL | CRITICAL, sound 154–505 (one clap 106 → WARNING) | as expected | **not heard** (v1.0.0) | "Sound level above critical limit" | same row | 10 s after the last clap |
| 4b vibration | firm knocks ~10 s | CRITICAL | CRITICAL, vibration 113–286 | as expected | **not heard** (v1.0.0) | "Vibration above critical limit" | same row | 10 s after the last knock |
| Buzzer check (v1.0.2) | taps directly on the SW-420 | CRITICAL + 3-beep pattern | WARNING (84) → CRITICAL (206) | `WARN VIB …`, clean | 3-beep pattern + chirp **heard** | "Vibration above critical limit", then "Vibration near warning limit" | same row | 6 s after the last tap |
| 4c safety zone | hand ~15–20 cm 10 s, then ~8 cm 10 s | WARNING, then CRITICAL | WARNING at 17.8–20.4 cm, CRITICAL at 7.5–9.5 cm | `WARN DIST …<20`, `CRIT DIST …<10` | chirp, then pattern | "Safety zone below warning/critical limit" | same row | 9 s after the hand left |
| 4d water leak | wet finger + drops ~10 s, dried with a tissue | CRITICAL | CRITICAL, leak 449–603; drying 147 → 45 → WARNING | `CRIT LEAK …>200`, `WARN LEAK` | pattern | "Water leak above critical limit" | same row | 28 s after the first wipe (traces must be fully dry) |
| 4e temperature | fingertip on the DHT11, ~2.5 min | WARNING (≥ 32) if reached | WARNING at 32.3 °C, **CRITICAL at 35.0 °C**, peak 35.2 °C | `WARN TMP …>32`, `CRIT TMP 35.x>35` | chirp, then pattern | "Temperature above warning/critical limit"; forecast "approaching" → "reached" | ~20 s to 32 °C | ~4 min after letting go (DHT11 cools slowly) |
| 4f sensor fault | DHT11 signal wire (A0) out ~15 s | WARNING, "Sensor fault: DHT11", forecast no data | WARNING, `temp_c`/`humidity` empty | `SENSOR FAULT` / `DHT11` | chirp | "Sensor fault: DHT11", forecast `no_data`, ML `ML_UNAVAILABLE` ("All systems normal (rules only)" after replug) | ~6 s by design (3 failed reads, one per 2 s) | 5 s after the first good reading |

Humidity rose to 98 % under the finger in 4e and produced **no alarm**, as intended (no
humidity limits, see Decisions). ML showed ANOMALY on real data throughout: expected with the
provisional synthetic-only model (Phase 8).

**Device vs backend mirror (`agrees`):** 3730 logged rows, **15 disagreements**, all right
after a reconnect, none during a test:
- 11:30:00, 4 rows: stale rows from before a board reset arrived as WARNING while the mirror
  started at NORMAL. A mirror that starts mid-stream cannot know the device's earlier state.
- 12:00:00–12:00:10, 11 rows: after a USB replug the board restarted at NORMAL, but the mirror
  kept its CRITICAL from before the drop. **Fixed** (backend resets the mirror when the device
  clock goes backwards); replaying the logged session with the fix gives 0 disagreements.

Serial: `rows_rejected` 0 for the whole session. The backend found the board again by itself
after every USB drop (auto-reconnect works).

## Decisions

- **Vibration limits: warn 50, critical 100, hysteresis 10** (were 20/60/5). Light taps stay
  NORMAL, firm knocks WARNING, very hard knocks CRITICAL. The first two calibration taps
  (70, 85) were firmer than the rest.
- **Humidity has no rule limits** (warn/critical/hysteresis null, `forecast: false`, still shown
  and used by ML): room humidity here sits around 80 %RH, the DHT11 tops out at 90 %RH, and
  humidity is not a machine-fault signal.
- **Demo procedure: tap the vibration sensor itself, not the table.** A knock on the table is
  also loud (sound 46–136, a real sound event the rules correctly report) and shakes the whole
  breadboard. Reach for the sensors from the side, not over the HC-SR04 (the safety zone sees
  your arm). Temperature CRITICAL is reachable with a fingertip (~2 min); a hair dryer is faster.

## Fixes

1. **Passive buzzer (firmware v1.0.1).** The buzzer was silent in 4a/4b. A test sketch in the
   Arduino IDE showed it beeps only with `tone(8, 2000)`, nothing on steady HIGH, LOW or
   floating: it is a **passive** buzzer. The sketch now drives it with `tone()` at 2.5 kHz
   (`BUZZER_PASSIVE 1`, `BUZZER_FREQ_HZ 2500`; `BUZZER_ACTIVE_LOW` removed), `noTone()` + pin
   back to INPUT when silent. Silent readings unchanged (sound 3–5, dry leak 4–8). `tone()`
   uses Timer2, which nothing else uses (`millis()` = Timer0, D2 = INT0, watchdog and I2C are
   separate hardware); a `pulseIn()` distance during a beep reads a few % short.
2. **Sensor blanking to avoid self-interference (firmware v1.0.2).** The microphone heard the
   buzzer: sound 30–39 during beeps, inside the sound hysteresis band (30–40), so after a
   vibration CRITICAL the device named **sound** as the WARNING reason and recovered 1–2 s
   later. The sketch now ignores the microphone while the buzzer sounds and for 50 ms after.
   With blanking: sound 3 on every beeping row, WARNING reason stays "Vibration". The buzzer
   was also moved a bit further from the sound sensor.
3. **Headline level (backend).** In WARNING at 34.5–34.9 °C (inside the critical hysteresis
   band) the headline said "Temperature near warning limit"; it now says "near critical
   limit" (the trigger's own level). Test: `test_warning_inside_critical_band_says_near_critical`.
4. **Mirror reset on device restart (backend).** See the `agrees` note above. Test:
   `test_mirror_resets_when_the_device_clock_restarts`.

## Bench problems (hardware, not code)

- **Loose jumpers after moving the buzzer** (11:39–11:52): the Uno dropped off USB, the LCD
  showed garbage (boxes, `?`), sound spiked 46–87 with nothing happening and leak read 0
  (sensor lost its 5 V). Fixed by re-seating the rail and module jumpers. Later drops at
  12:05:17 and 12:06:32 were an accidental unplug and a few loose wires (fixed).
- **HC-SR04 dropouts:** during knocks the distance field was often empty (no echo pulse = loose
  jumper; an optional sensor, so no state change). The wires were taped after the session's
  first half; afterwards no gaps.
- **Unexplained bump** in the first baseline (10:52:50, vibration 206 → CRITICAL): labelled
  unknown.

## Recording

`data/recordings/real_session_01_20261024.csv`: **3408 rows** (≈ 57 min recorded between
10:52 and 12:23, six parts merged in time order, 8 device-clock segments because of board
resets): **868 normal, 686 fault, 1854 unknown.**

Label clean-up (the label was switched by hand, so it brackets each test loosely):
1. Bench mishaps → unknown: the bump at 10:52:45–10:53:15 and 10:54:05–10:54:25, an object at
   20 cm while preparing the calibration (10:57:15–10:57:52), a bump at 11:18:05–11:18:20, the
   whole loose-jumper part (11:45:41–11:47:28), the unplug/re-wiring during 4d
   (12:05:00–12:07:21), a bump and a hand in the safety zone in the final minutes
   (12:21:48–12:22:30).
2. Inside each fault run only the span from the first to the last induced deviation stays
   `fault` (vibration/sound/leak ≥ 20, distance < 25 cm or empty, temperature +1 °C or
   humidity +5 % over the run's start, a core field empty); the quiet lead-in before the
   action and the tail after it are `unknown`.
3. `normal` rows where the device was not NORMAL (unplanned extra knocks, a loud noise, a hold
   still running after a test) → `unknown`.

Caveats for Phase 8: the fault rows of the 11:30–11:33 buzzer check (v1.0.1) contain buzzer
pickup in `sound_peak` (30–35); the vibration calibration (old limits) is labelled unknown;
small desk bumps (vibration 10–40, below the warning limit) remain in the normal data.
