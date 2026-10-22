# FreqEnforcer post-pitch combination sweep

Generated 2026-10-22 by `tests/sweep/report.py`. The latest run is a full sweep. The sweep is the acceptance test for the post-pitch pipeline (smart low cut, cleanliness, breathiness); its thresholds have not changed since the pre-fix run.

```bash
python tests/sweep/run_sweep.py --tag <label>   # full sweep + probes + this report, adds a history entry
python tests/sweep/report.py                    # rebuild this report from tests/sweep/out/
python -m pytest tests/test_pipeline_combos.py  # the 30 previous-worst combinations + cache collision
```

- Latest run: git `9a4f14b`, Python 3.14.2, Windows-11-10.0.26200-SP0, 22 worker processes, 15.25 min, **10428 renders** through `server.routes.audio._run_pipeline` with settings built by `ProcessRequest(...).model_dump()`.
- librosa imported in any process: no

## Pass rate after each change

One row per full sweep (`tests/sweep/history.json`). *raw* = renders with no failed metric. *post-pitch* = renders with no failure caused after the pitch stage: failures inherited from the pitch-only render, and f0/inharm failures where the pitch stage already missed the note, are excluded. *excl. intended* also allows breathiness > 1 failing the inharmonic rule, which is what that setting is for.

| run | commit | date | renders | raw | post-pitch | post-pitch excl. intended | post-pitch failures | top post-pitch causes |
|---|---|---|---|---|---|---|---|---|
| **prefix** | `a34b4fd` | frozen | 10428 | 6.1 % | 30.2 % | 43.6 % | 12189 | breath_intended 3886, B1 3600, B4 2603, breath_resynth 1686 |
| **change1: output F0 contour** | `b32a998` (dirty) | 2026-10-22 21:19 | 10428 | 4.4 % | 18.6 % | 30.8 % | 13893 | clean 8032, breath_intended 5397, breath 3399, lowcut 87 |
| **change2: cleanliness mask** | `fa5702c` (dirty) | 2026-10-22 21:49 | 10428 | 11.5 % | 47.6 % | 76.9 % | 8029 | breath_intended 4928, breath 2873, clean 554, lowcut 25 |
| **change3: breathiness in WORLD modes** | `26f7941` (dirty) | 2026-10-22 22:19 | 10428 | 24.2 % | 84.3 % | 96.8 % | 1803 | breath_intended 1459, clean 327, lowcut 21, breath 19 |
| **change4: full-buffer cache key** | `9a4f14b` (dirty) | 2026-10-22 22:45 | 10428 | 24.2 % | 84.3 % | 96.8 % | 1803 | breath_intended 1459, clean 327, lowcut 21, breath 19 |

## Before / after (pre-fix vs latest run)

Failed metrics (counted per render):

| metric | all, before | all, after | post-pitch, before | post-pitch, after |
|---|---|---|---|---|
| length | 859 | 859 | 0 | 0 |
| peak | 4055 | 2188 | 2519 | 84 |
| f0 | 4587 | 2004 | 2420 | 79 |
| inharm | 6664 | 4831 | 3261 | 1304 |
| tail | 6307 | 4182 | 3577 | 213 |
| rms | 450 | 173 | 412 | 123 |

Renders passing: raw **6.1 % → 24.2 %**, post-pitch **30.2 % → 84.3 %**, post-pitch excl. intended **43.6 % → 96.8 %**.

Per render (post-pitch, excl. intended): **5621 fixed**, **74 newly failing**, 258 failing before and after.

Newly failing renders (worst 20):

| combination | fails now | causes now | f0 ¢ | inharm Δ | tail | RMS Δ | peak | len Δ |
|---|---|---|---|---|---|---|---|---|
| `harm_A4|sine_spectral|+5|x1.5|lc50|cl25|rb50|br2|hb1` | tail, rms | tail: clean; rms: clean | +703 | +34.0 | −7.1 | −14.4 | −9.4 | −56 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl50|rb0|br5|hb0` | tail, rms | tail: clean; rms: clean | +704 | +29.2 | −12.1 | −15.7 | −7.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl25|rb0|br5|hb0` | tail, rms | tail: clean; rms: clean | +703 | +33.4 | −12.8 | −14.6 | −6.0 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl75|rb0|br5|hb0` | tail | tail: clean | +703 | +22.8 | −9.3 | −18.7 | −8.4 | +0 |
| `breathy_A3|sine_spectral|+12|x1|lc0|cl75|rb0|br0.5|hb0` | tail | tail: clean | −8 | +7.4 | −15.4 | −13.8 | −15.0 | +0 |
| `breathy_A3|sine_spectral|+12|x1|lc0|cl75|rb0|br2|hb0` | tail | tail: clean | −8 | +7.4 | −15.4 | −13.8 | −15.0 | +0 |
| `lead_G3|sine_spectral|+12|x1|lc0|cl100|rb0|br1|hb0` | tail | tail: clean | −5 | +40.4 | −16.1 | −12.1 | −12.2 | +0 |
| `breathy_A3|stft_pitchshift|+0|x1|lc0|cl50|rb0|br2|hb0` | tail, rms | tail: clean; rms: clean | +435 | +19.7 | −29.2 | −7.7 | −8.9 | +0 |
| `harm_A4|sine_spectral|+12|x1|lc0|cl75|rb0|br0|hb0` | tail | tail: clean | +1159 | +11.0 | −16.6 | −9.6 | −7.2 | +0 |
| `harm_A4|sine_spectral|+12|x1|lc0|cl75|rb0|br0.5|hb0` | tail | tail: clean | +1159 | +11.0 | −16.6 | −9.6 | −7.2 | +0 |
| `harm_A4|sine_spectral|+12|x1|lc0|cl75|rb0|br2|hb0` | tail | tail: clean | +1159 | +11.0 | −16.6 | −9.6 | −7.2 | +0 |
| `harm_A4|sine_spectral|+12|x1|lc0|cl75|rb0|br5|hb0` | tail | tail: clean | +1159 | +11.0 | −16.6 | −9.6 | −7.2 | +0 |
| `harm_A5|sine_spectral|-7|x1|lc0|cl100|rb0|br5|hb0` | tail | tail: clean | +702 | +10.3 | −20.2 | −12.9 | −9.9 | +0 |
| `breathy_A3|sine_spectral|-7|x1|lc0|cl100|rb0|br0|hb0` | tail | tail: clean | −8 | +11.7 | −22.6 | −11.9 | −14.0 | +0 |
| `breathy_A3|sine_spectral|-7|x1|lc0|cl100|rb0|br0.5|hb0` | tail | tail: clean | −8 | +11.7 | −22.6 | −11.9 | −14.0 | +0 |
| `breathy_A3|sine_spectral|-7|x1|lc0|cl100|rb0|br2|hb0` | tail | tail: clean | −8 | +11.7 | −22.6 | −11.9 | −14.0 | +0 |
| `breathy_A3|sine_spectral|-7|x1|lc0|cl100|rb0|br5|hb0` | tail | tail: clean | −8 | +11.7 | −22.6 | −11.9 | −14.0 | +0 |
| `breathy_A3|world_hard|+12|x1|lc0|cl50|rb0|br5|hb0` | f0 | f0: multi:clean+breath_intended | +40 | +0.7 | −23.4 | −8.9 | −15.7 | +5 |
| `breathy_A3|sine_spectral|-7|x1|lc0|cl75|rb0|br0|hb0` | tail | tail: clean | −8 | +13.1 | −24.1 | −9.9 | −11.9 | +0 |
| `breathy_A3|sine_spectral|-7|x1|lc0|cl75|rb0|br0.5|hb0` | tail | tail: clean | −8 | +13.1 | −24.1 | −9.9 | −11.9 | +0 |

Post-pitch failures by cause. The pre-fix harness named bugs through counterfactual re-renders (B1-B4, E1, E2); the current harness names the stage whose removal clears the failure:

| cause | before | after | meaning |
|---|---|---|---|
| breath_intended | 3886 | 1459 | breathiness > 1 adds aperiodicity by design (fails the inharmonic rule) |
| B1 | 3600 |  | cleanliness masks the ORIGINAL f0's harmonics (cached WORLD f0 of the input) |
| B4 | 2603 |  | breathiness re-analyses with harvest (default 71-800 Hz) |
| breath_resynth | 1686 |  | breathiness second WORLD resynthesis itself |
| E1 | 826 |  | cleanliness ISTFT start-of-file blow-up (no leading pad, NOLA) |
| B2 | 782 |  | cleanliness 100 %: 10 Hz mask < 21.5 Hz STFT bin, even with correct f0 |
| clean_mask | 555 |  | cleanliness 25-75 % mask with correct f0 |
| clean |  | 327 | cleanliness stage (failure clears with cleanliness off) |
| E2 | 55 |  | cleanliness's own pyin f0 wrong (50-500 Hz range) |
| lowcut_design | 35 |  | smart low cut with correct f0 |
| lowcut |  | 21 | smart low cut stage (clears with low cut off) |
| B3 | 21 |  | smart low cut keyed to the original f0 (state.detected_pitch) |
| breath |  | 19 | breathiness < 1 (clears with breathiness 1) |

The 30 worst pre-fix combinations by post-pitch severity (these are the permanent cases in `tests/test_pipeline_combos.py`), before → after:

| # | combination | post-pitch fails before | post-pitch fails after | peak dBFS | f0 ¢ | inharm Δ dB | tail dB | all failures now: cause |
|---|---|---|---|---|---|---|---|---|
| 1 | `harm_A4|praat_soft|+12|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | **pass** | +64.6 → −7.7 | −1276 → +0 | +44.7 → −12.1 | −24.8 → −64.5 |  |
| 2 | `harm_A5|praat_soft|+5|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | **pass** | +56.8 → −8.0 | −1197 → −1 | +42.9 → −3.8 | −19.1 → −65.9 |  |
| 3 | `vowel_D3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1` | peak, f0, tail | **pass** | +73.2 → −8.5 | +715 → +0 | −7.5 → −6.7 | −25.4 → −44.0 |  |
| 4 | `vowel_D3|praat_soft|+0|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | **pass** | +71.8 → −7.7 | +380 → +0 | −0.7 → +0.5 | −26.7 → −58.9 |  |
| 5 | `vowel_D3|praat_soft|+12|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | **pass** | +71.3 → −7.7 | +715 → +0 | −7.6 → −6.7 | −25.5 → −45.5 |  |
| 6 | `breathy_A3|praat_soft|-12|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | **pass** | +57.9 → −9.9 | −1194 → +1 | +8.6 → −5.5 | −17.1 → −81.1 |  |
| 7 | `harm_A5|praat_soft|-7|x1|lc0|cl75|rb0|br1|hb0` | peak, f0, tail | **pass** | +54.1 → −7.2 | +692 → +0 | +27.9 → +3.3 | −29.2 → −58.3 |  |
| 8 | `vowel_D3|stft_pitchshift|+0|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | **pass** | +53.4 → −7.5 | +380 → −0 | −0.6 → +0.2 | −28.9 → −49.8 |  |
| 9 | `harm_A5|sine_spectral|+0|x1|lc0|cl75|rb0|br1|hb0` | peak, f0 | **pass** | +52.9 → −8.2 | +1179 → −9 | +30.1 → +31.0 | −31.1 → −28.5 | inharm: inherited; tail: inherited |
| 10 | `harm_G3|sine_spectral|+0|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | **pass** | +58.3 → −6.7 | +97 → +0 | +33.8 → +9.7 | −17.7 → −40.9 | inharm: inherited |
| 11 | `harm_G3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1` | peak, f0, tail | **pass** | +62.0 → −9.4 | +152 → +0 | +22.6 → +7.1 | −22.7 → −59.7 | inharm: inherited |
| 12 | `harm_A4|praat_soft|+5|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | **pass** | +63.1 → −7.9 | +138 → −0 | +27.9 → −2.6 | −21.8 → −58.0 |  |
| 13 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br5|hb0` | peak, f0, inharm, tail, rms | **pass** | +0.3 → −2.1 | +1194 → −7 | +40.3 → +13.5 | −21.5 → −29.8 | inharm: inherited; tail: inherited |
| 14 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br0.5|hb0` | peak, f0, inharm, tail, rms | **pass** | +1.2 → −2.1 | +1196 → −7 | +38.1 → +13.5 | −21.9 → −29.8 | inharm: inherited; tail: inherited |
| 15 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br2|hb0` | peak, f0, inharm, tail, rms | **pass** | +0.9 → −2.1 | +1196 → −7 | +38.4 → +13.5 | −21.7 → −29.8 | inharm: inherited; tail: inherited |
| 16 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br5|hb0` | f0, inharm, tail, rms | inharm | −7.0 → −4.1 | +704 → +0 | +45.1 → +27.1 | −22.5 → −31.1 | inharm: breath_intended; tail: inherited |
| 17 | `harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br5|hb0` | f0, inharm, tail, rms | inharm | −7.2 → −4.2 | +704 → +0 | +45.1 → +27.1 | −22.7 → −30.9 | inharm: breath_intended; tail: inherited |
| 18 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br2|hb0` | f0, inharm, tail, rms | inharm | −7.7 → −4.8 | +704 → +0 | +45.1 → +10.2 | −22.5 → −31.3 | inharm: breath_intended; tail: inherited |
| 19 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br0.5|hb0` | f0, inharm, tail, rms | **pass** | −7.8 → −4.9 | +704 → +0 | +45.1 → +0.5 | −22.5 → −31.3 | tail: inherited |
| 20 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br0|hb0` | f0, inharm, tail, rms | **pass** | −7.7 → −4.9 | +704 → +0 | +45.1 → +0.5 | −22.5 → −31.3 | tail: inherited |
| 21 | `harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br2|hb0` | f0, inharm, tail, rms | **pass** | −7.6 → −4.9 | +704 → +0 | +45.1 → +10.2 | −22.7 → −31.1 | inharm: inherited; tail: inherited |
| 22 | `harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br0.5|hb0` | f0, inharm, tail, rms | **pass** | −7.6 → −5.0 | +704 → +0 | +45.1 → +0.8 | −22.7 → −31.1 | tail: inherited |
| 23 | `harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br0|hb0` | f0, inharm, tail, rms | **pass** | −7.5 → −5.0 | +704 → +0 | +45.1 → +0.8 | −22.7 → −31.1 | tail: inherited |
| 24 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl50|rb0|br5|hb0` | peak, f0, inharm, tail, rms | **pass** | +1.0 → −2.4 | +1196 → −7 | +36.7 → +10.1 | −20.5 → −29.7 | inharm: inherited; tail: inherited |
| 25 | `harm_A4|world_soft|+5|x1|lc50|cl25|rb0|br0.5|hb1` | f0, inharm, tail, rms | **pass** | −7.5 → −5.1 | +704 → +0 | +45.1 → +0.8 | −23.2 → −36.5 | tail: inherited |
| 26 | `harm_A4|stft_pitchshift|-7|x1|lc0|cl100|rb0|br0|hb0` | peak, f0, inharm, tail | **pass** | +0.6 → −5.1 | +783 → −4 | +46.9 → +3.4 | −25.4 → −34.4 | tail: inherited |
| 27 | `harm_A4|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1` | peak, inharm, tail | **pass** | +59.2 → −9.1 | +2 → +0 | +37.1 → +6.9 | −4.7 → −61.2 | inharm: inherited |
| 28 | `harm_A4|stft_pitchshift|-7|x1|lc0|cl100|rb0|br0.5|hb0` | peak, f0, inharm, tail | **pass** | +0.5 → −5.1 | +781 → −4 | +46.9 → +3.4 | −25.4 → −34.4 | tail: inherited |
| 29 | `harm_A4|world_hnm|+5|x1.5|lc0|cl50|rb50|br0|hb0` | f0, inharm, tail | **pass** | −5.4 → −5.1 | +702 → +1 | +43.8 → +0.5 | −9.2 → −15.1 | length: inherited; tail: inherited |
| 30 | `harm_A5|praat_soft|+0|x1|lc0|cl75|rb0|br1|hb0` | peak, f0, tail | **pass** | +55.6 → −7.1 | +137 → +0 | +30.5 → −7.8 | −24.3 → −64.8 |  |

## Remaining failures

14237 failed (render, metric) pairs in the latest run:

| category | failures | why it remains |
|---|---|---|
| inherited from the pitch stage | 12286 | The pitch-only render fails the same metric. Fixing pitch modes is out of scope for this change set (see the per-mode table). |
| pitch stage missed the note (f0/inharm) | 148 | Measured against a target the post stages never received. |
| breathiness > 1 (intended) | 1436 | Breathiness above 1 is meant to add aperiodic energy; the inharmonic rule counts that as a failure. |
| **post-pitch** | **367** | listed below |

Pitch-stage failures by mode:

| mode | exception | nonfinite | length | peak | f0 | inharm | tail | rms | pitch_miss |
|---|---|---|---|---|---|---|---|---|---|
| `world_hard` |  |  | 88 | 296 | 55 | 89 | 857 | 17 | 6 |
| `world_soft` |  |  | 77 | 429 | 150 | 183 | 842 | 17 | 2 |
| `world_vt` |  |  | 88 | 418 | 149 | 174 | 831 | 16 | 2 |
| `world_hnm` |  |  | 342 | 370 | 155 | 512 | 77 |  | 1 |
| `praat_soft` |  |  | 66 | 5 | 142 | 468 | 42 |  | 1 |
| `sine_spectral` |  |  | 99 | 443 | 866 | 1363 | 710 |  | 130 |
| `stft_pitchshift` |  |  | 99 | 143 | 270 | 728 | 610 |  | 6 |

Post-pitch failures by metric and cause. *breath = 1*: breathiness off, so the failure comes from cleanliness / low cut alone. *pitch-only misses the note*: the pitch stage already produced the wrong pitch, so cleanliness (which masks the target's harmonics) removes most of the body and tail/rms, which are relative to the body, move with it.

| metric | cause | breath = 1 | pitch-only misses the note | failures |
|---|---|---|---|---|
| tail | clean | no | yes | 139 |
| rms | clean | no | yes | 95 |
| tail | clean | yes | yes | 34 |
| rms | clean | yes | yes | 23 |
| f0 | breath | no | no | 13 |
| f0 | multi:clean+breath_intended | no | no | 12 |
| f0 | clean | yes | no | 9 |
| f0 | clean | no | no | 7 |
| tail | breath | no | no | 6 |
| rms | lowcut | no | no | 5 |
| f0 | clean/breath_intended | no | no | 5 |
| peak | lowcut | no | yes | 5 |
| tail | lowcut | no | yes | 2 |
| tail | clean/breath_intended | no | no | 2 |
| tail | lowcut | no | no | 2 |
| inharm | lowcut/breath_intended | no | no | 2 |
| peak | lowcut | yes | yes | 2 |
| inharm | lowcut | no | no | 1 |
| peak | clean | yes | yes | 1 |
| f0 | lowcut/breath_intended | no | no | 1 |
| inharm | multi:lowcut+breath_intended | no | no | 1 |

Worst post-pitch failures (up to 40):

| combination | metric | cause | f0 ¢ | inharm Δ | tail | RMS Δ | peak | len Δ |
|---|---|---|---|---|---|---|---|---|
| `breathy_A3|world_vt|+12|x1.5|lc100|cl0|rb50|br5|hb1` | f0 | lowcut/breath_intended | −1197 | +9.6 | −40.8 | −8.5 | −12.4 | −44 |
| `breathy_A3|stft_pitchshift|+0|x1.5|lc0|cl100|rb50|br0|hb1` | tail | clean | −790 | +17.8 | −0.7 | −16.4 | −10.5 | −56 |
| `breathy_A3|stft_pitchshift|+5|x1.5|lc100|cl75|rb0|br1|hb0` | tail | clean | −8 | +16.2 | −3.0 | −19.2 | −15.5 | −56 |
| `breathy_A3|stft_pitchshift|+12|x1.5|lc50|cl50|rb50|br5|hb1` | tail | clean | −27 | +18.5 | −3.5 | −11.5 | −13.7 | −56 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl100|rb0|br0|hb0` | tail | clean | +703 | +19.3 | −7.0 | −21.0 | −8.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl100|rb0|br0.5|hb0` | tail | clean | +703 | +19.3 | −7.0 | −21.0 | −8.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl100|rb0|br1|hb0` | tail | clean | +703 | +19.3 | −7.0 | −21.0 | −8.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl100|rb0|br2|hb0` | tail | clean | +703 | +19.3 | −7.0 | −21.0 | −8.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl100|rb0|br5|hb0` | tail | clean | +703 | +19.3 | −7.0 | −21.0 | −8.5 | +0 |
| `harm_A4|sine_spectral|+5|x1.5|lc50|cl25|rb50|br2|hb1` | tail | clean | +703 | +34.0 | −7.1 | −14.4 | −9.4 | −56 |
| `harm_A4|sine_spectral|-7|x1.5|lc100|cl100|rb50|br0.5|hb0` | tail | clean | +1218 | +21.1 | −8.7 | −9.0 | −10.8 | −56 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl75|rb0|br0|hb0` | tail | clean | +703 | +22.8 | −9.3 | −18.7 | −8.4 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl75|rb0|br0.5|hb0` | tail | clean | +703 | +22.8 | −9.3 | −18.7 | −8.4 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl75|rb0|br1|hb0` | tail | clean | +703 | +22.8 | −9.3 | −18.7 | −8.4 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl75|rb0|br2|hb0` | tail | clean | +703 | +22.8 | −9.3 | −18.7 | −8.4 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl75|rb0|br5|hb0` | tail | clean | +703 | +22.8 | −9.3 | −18.7 | −8.4 | +0 |
| `vowel_D3|sine_spectral|+12|x1|lc0|cl100|rb0|br0|hb0` | tail | clean | +142 | +42.3 | −11.1 | −18.8 | −13.0 | +0 |
| `vowel_D3|sine_spectral|+12|x1|lc0|cl100|rb0|br0.5|hb0` | tail | clean | +142 | +42.3 | −11.1 | −18.8 | −13.0 | +0 |
| `vowel_D3|sine_spectral|+12|x1|lc0|cl100|rb0|br1|hb0` | tail | clean | +142 | +42.3 | −11.1 | −18.8 | −13.0 | +0 |
| `vowel_D3|sine_spectral|+12|x1|lc0|cl100|rb0|br2|hb0` | tail | clean | +142 | +42.3 | −11.1 | −18.8 | −13.0 | +0 |
| `vowel_D3|sine_spectral|+12|x1|lc0|cl100|rb0|br5|hb0` | tail | clean | +142 | +42.3 | −11.1 | −18.8 | −13.0 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl50|rb0|br0|hb0` | tail | clean | +704 | +29.2 | −12.1 | −15.7 | −7.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl50|rb0|br0.5|hb0` | tail | clean | +704 | +29.2 | −12.1 | −15.7 | −7.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl50|rb0|br1|hb0` | tail | clean | +704 | +29.2 | −12.1 | −15.7 | −7.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl50|rb0|br2|hb0` | tail | clean | +704 | +29.2 | −12.1 | −15.7 | −7.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl50|rb0|br5|hb0` | tail | clean | +704 | +29.2 | −12.1 | −15.7 | −7.5 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl25|rb0|br0|hb0` | tail | clean | +703 | +33.4 | −12.8 | −14.6 | −6.0 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl25|rb0|br0.5|hb0` | tail | clean | +703 | +33.4 | −12.8 | −14.6 | −6.0 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl25|rb0|br1|hb0` | tail | clean | +703 | +33.4 | −12.8 | −14.6 | −6.0 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl25|rb0|br2|hb0` | tail | clean | +703 | +33.4 | −12.8 | −14.6 | −6.0 | +0 |
| `harm_A4|sine_spectral|+5|x1|lc0|cl25|rb0|br5|hb0` | tail | clean | +703 | +33.4 | −12.8 | −14.6 | −6.0 | +0 |
| `breathy_A3|stft_pitchshift|+5|x1|lc0|cl100|rb0|br0|hb0` | tail | clean | −9 | +14.8 | −13.1 | −21.4 | −15.2 | +0 |
| `breathy_A3|stft_pitchshift|+5|x1|lc0|cl100|rb0|br0.5|hb0` | tail | clean | −9 | +14.8 | −13.1 | −21.4 | −15.2 | +0 |
| `breathy_A3|stft_pitchshift|+5|x1|lc0|cl100|rb0|br1|hb0` | tail | clean | −9 | +14.8 | −13.1 | −21.4 | −15.2 | +0 |
| `breathy_A3|stft_pitchshift|+5|x1|lc0|cl100|rb0|br2|hb0` | tail | clean | −9 | +14.8 | −13.1 | −21.4 | −15.2 | +0 |
| `breathy_A3|stft_pitchshift|+5|x1|lc0|cl100|rb0|br5|hb0` | tail | clean | −9 | +14.8 | −13.1 | −21.4 | −15.2 | +0 |
| `breathy_A3|sine_spectral|+12|x1|lc0|cl100|rb0|br0|hb0` | tail | clean | −8 | +5.8 | −13.5 | −15.8 | −15.3 | +0 |
| `breathy_A3|sine_spectral|+12|x1|lc0|cl100|rb0|br0.5|hb0` | tail | clean | −8 | +5.8 | −13.5 | −15.8 | −15.3 | +0 |
| `breathy_A3|sine_spectral|+12|x1|lc0|cl100|rb0|br1|hb0` | tail | clean | −8 | +5.8 | −13.5 | −15.8 | −15.3 | +0 |
| `breathy_A3|sine_spectral|+12|x1|lc0|cl100|rb0|br2|hb0` | tail | clean | −8 | +5.8 | −13.5 | −15.8 | −15.3 | +0 |

**Every remaining post-pitch failure, by documented reason:**

| reason | failures | why it is not fixed here |
|---|---|---|
| pitch_miss_body | 301 | Pitch-only render already misses the target note. Cleanliness masks the target's harmonics, so it removes most of the (off-target) body; tail and rms are measured relative to that body. Fix belongs to the pitch mode (mostly sine_spectral / stft_pitchshift), not the post stages. |
| yin_bias | 47 | YIN (the sweep's f0 metric) misreads the note: the spectral peaks of harmonics 1-4 sit within 2 cents of the target. Seen on the breathy fixture once its pitch-locked aspiration noise is removed. The pitch is right; the metric is left unchanged, as required. |
| lowcut_100 | 10 | Smart low cut at 100 %: the cutoff is 0.85 x the output's lowest f0 (filtfilt, 2nd order), which takes ~3.6 dB off the fundamental by design; stacked with other stages it crosses the rule. Lowering the 0.85 ceiling would change the control's documented behaviour - a product decision. |
| marginal_tail | 4 | The pitch-only render's own release smear sits just under -40 dB; the post stages raise it by 3 dB or less, past the line. The extra energy is in voiced release frames of the pitch mode's synthesis. |
| hnm_low_release | 5 | world_hnm on C1-C2 targets, tail failures caused only by breathiness < 1 and/or the low cut (all within ~1 dB of the -40 dB limit in this sweep). Breathiness < 1 makes the decaying release frames fully periodic, so HNM's harmonic part rings longer; with the low cut, the IIR high-pass (cutoff ~40 Hz) rings after the offset. Fixing either is a design change (keep release frames' aperiodicity / guard the low cut's envelope), proposed as a follow-up rather than tuned here. |

Evidence for *yin_bias* (up to 24): YIN reading vs the offset of harmonics 1-4 from n x target (1 M-point FFT of the note body):

| combination | YIN ¢ | spectral H1..H4 ¢ |
|---|---|---|
| `breathy_A3|world_vt|+12|x1.5|lc100|cl0|rb50|br5|hb1` | −1196.7 | +0.00, +0.00, +0.06, +0.00 |
| `breathy_A3|world_hard|+5|x1|lc0|cl0|rb0|br0|hb0` | +44.2 | +0.12, −0.01, −0.05, −0.01 |
| `breathy_A3|world_hard|+5|x1|lc0|cl25|rb0|br0|hb0` | +43.4 | +0.12, −0.01, −0.05, −0.01 |
| `breathy_A3|world_hard|+5|x1|lc0|cl100|rb0|br0|hb0` | +43.2 | +0.12, −0.01, −0.05, −0.01 |
| `breathy_A3|world_hard|+12|x1|lc0|cl50|rb0|br5|hb0` | +39.9 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+12|x1|lc0|cl50|rb0|br2|hb0` | +39.1 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_soft|+12|x1|lc0|cl25|rb0|br2|hb0` | +38.1 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+12|x1|lc0|cl25|rb0|br2|hb0` | +37.1 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+12|x1|lc0|cl75|rb0|br2|hb0` | +37.0 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+12|x1|lc0|cl100|rb0|br2|hb0` | +36.6 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+12|x1|lc0|cl75|rb0|br5|hb0` | +36.3 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_vt|+12|x1|lc0|cl25|rb0|br5|hb0` | +35.9 | +0.00, −0.08, +0.00, +0.00 |
| `breathy_A3|world_vt|+12|x1|lc0|cl25|rb0|br0.5|hb0` | +35.5 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+5|x1|lc0|cl50|rb0|br0|hb0` | +35.1 | +0.12, −0.01, −0.05, −0.01 |
| `breathy_A3|world_vt|+12|x1|lc0|cl25|rb0|br1|hb0` | +34.8 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+5|x1|lc0|cl75|rb0|br0|hb0` | +34.8 | +0.12, −0.01, −0.05, −0.01 |
| `breathy_A3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1` | +34.1 | −0.49, −0.58, −0.88, −0.82 |
| `breathy_A3|world_hard|+12|x1|lc0|cl100|rb0|br5|hb0` | +33.8 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_vt|+12|x1|lc0|cl25|rb0|br2|hb0` | +33.7 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_hard|+12|x1|lc0|cl75|rb0|br1|hb0` | +32.9 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_soft|+12|x1|lc0|cl50|rb0|br2|hb0` | +32.4 | +0.00, +0.00, +0.00, +0.00 |
| `breathy_A3|world_soft|+5|x1|lc0|cl0|rb0|br0|hb0` | +25.2 | +0.12, −0.01, −0.05, −0.01 |
| `breathy_A3|world_hard|-7|x1.5|lc50|cl75|rb50|br0|hb1` | +23.5 | −0.13, +0.12, +0.03, −0.01 |
| `breathy_A3|world_hnm|+5|x1|lc0|cl25|rb0|br5|hb0` | +23.3 | +0.12, +0.12, +0.03, +0.12 |


## Intentional output changes

Golden references regenerated because their render has cleanliness, breathiness or low cut active (`tests/sweep/intentional_changes.json`). Pitch-only references are unchanged. Metrics use the sweep's definitions on the 2 s C4 fixture; *H1 vs input* is the fundamental's level relative to the source's.

| change | file | why | peak dBFS | RMS Δ dB | f0 ¢ | inharm Δ dB | H1 vs input dB | max\|old−new\| | sweep fails before | sweep fails after |
|---|---|---|---|---|---|---|---|---|---|---|
| change1 | `tests/golden/test_2s_C4/pipe_clean__na__F4.wav` | cleanliness masks the output F0 contour (was the input's cached WORLD F0); smart low cut keyed to the output contour | −2.1 → +57.3 | −13.4 → −1.2 | +1 → +0 | +9.2 → −3.8 | −16.0 → −0.7 | 734.1271 | inharm, rms | peak |
| change2 | `tests/golden/test_2s_C4/pipe_clean__na__F4.wav` | cleanliness: n_fft from output F0, mask >= 2 bins, time-smoothed, both-end padding (E1), envelope guard | +57.3 → −2.5 | −1.2 → −1.2 | +0 → +0 | −3.8 → −3.8 | −0.7 → −0.7 | 734.1239 | peak | pass |
| change3 | `tests/golden/test_2s_C4/pipe_breath__na__F4.wav` | breathiness shapes the WORLD mode's own aperiodicity before its single synthesis (was a second harvest/cheaptrick/d4c/synthesize pass on the output) | −0.5 → −1.4 | +0.2 → −0.6 | +0 → +0 | +4.0 → +3.5 | +0.8 → −0.0 | 0.8286 | pass | pass |

## Suspected bugs: before / after

Each probe renders through `_run_pipeline` and compares a render with its pitch-only twin (`tests/sweep/probes.py`); *before* is the same probe code on the pre-fix pipeline.

### B1 - cleanliness used the original audio's f0

G3 +5 st, world_hard, cleanliness 100: note body vs pitch-only **−23.0 dB → −1.6 dB**, f0 +702 ¢ → −0 ¢. Probe renders with a post-pitch f0 failure: 8 → 0.

| fixture | shift | target | clean | body vs pitch-only dB | f0 ¢ | post-pitch fails |
|---|---|---|---|---|---|---|
| harm_G3 | −12 | G2 | 50 | −3.6 → −0.3 | +1200 → +0 | f0 → pass |
| harm_G3 | −12 | G2 | 100 | −9.5 → −1.7 | +1200 → +0 | f0, tail → pass |
| harm_G3 | −7 | C3 | 50 | −6.1 → −0.3 | +0 → +0 | pass → pass |
| harm_G3 | −7 | C3 | 100 | −17.8 → −1.6 | +702 → +0 | f0, tail → pass |
| harm_G3 | +0 | G3 | 50 | −0.3 → −0.3 | +0 → +0 | pass → pass |
| harm_G3 | +0 | G3 | 100 | −6.0 → −1.6 | +0 → +0 | tail → pass |
| harm_G3 | +5 | C4 | 50 | −7.0 → −0.3 | −0 → −0 | rms → pass |
| harm_G3 | +5 | C4 | 100 | −23.0 → −1.6 | +702 → −0 | f0, inharm, tail → pass |
| harm_G3 | +12 | G4 | 50 | −0.3 → −0.3 | +0 → +0 | pass → pass |
| harm_G3 | +12 | G4 | 100 | −9.4 → −1.7 | +0 → +0 | pass → pass |
| test_2s_C4 | −12 | C3 | 50 | −3.8 → −0.3 | +1200 → +0 | f0 → pass |
| test_2s_C4 | −12 | C3 | 100 | −10.7 → −1.6 | +1200 → +0 | f0 → pass |
| test_2s_C4 | −7 | F3 | 50 | −8.5 → −0.3 | −0 → −0 | rms → pass |
| test_2s_C4 | −7 | F3 | 100 | −23.7 → −1.7 | +701 → −0 | f0 → pass |
| test_2s_C4 | +0 | C4 | 50 | −0.3 → −0.3 | −0 → −0 | pass → pass |
| test_2s_C4 | +0 | C4 | 100 | −7.2 → −1.7 | −0 → −0 | pass → pass |
| test_2s_C4 | +5 | F4 | 50 | −12.8 → −0.3 | +1 → +0 | inharm, rms → pass |
| test_2s_C4 | +5 | F4 | 100 | −35.2 → −1.7 | +703 → +0 | f0, inharm → pass |
| test_2s_C4 | +12 | C5 | 50 | −0.3 → −0.3 | +0 → +1 | pass → pass |
| test_2s_C4 | +12 | C5 | 100 | −14.6 → −1.7 | +1 → +1 | pass → pass |

praat_soft G3 +5 st (before: breathiness ≠ 1 switched cleanliness to the cached original f0):

| clean | breath | body vs pitch-only dB | f0 ¢ | inharm Δ dB | post-pitch fails |
|---|---|---|---|---|---|
| 50 | 1.0 | −0.3 → −0.3 | −0 → −0 | +0.8 → +0.7 | peak → pass |
| 50 | 0.5 | −6.0 → −0.3 | −0 → −0 | +9.5 → +0.7 | tail, rms → pass |
| 100 | 1.0 | −8.1 → −1.7 | −0 → −0 | −0.8 → −2.6 | peak, tail → pass |
| 100 | 0.5 | −22.9 → −1.7 | −1031 → −0 | +38.5 → −2.6 | f0, inharm, tail → pass |

### B2 - cleanliness mask narrower than the STFT resolution

Noise-free tones at shift 0 (the f0 was right before and after), cleanliness vs the pitch-only render:

| tone | mode | clean | harmonic energy dB | H1 dB | tail dB | late tail dB | peak dBFS | post-pitch fails |
|---|---|---|---|---|---|---|---|---|
| pure_C2 | world_hard | 50 | −0.3 → −0.1 | −0.3 → −0.1 | −35.9 → −36.9 | −146.8 → −148.7 | −1.6 → −1.4 | pass → pass |
| pure_C2 | world_hard | 80 | −1.3 → −0.4 | −1.3 → −0.4 | −33.3 → −37.5 | −145.7 → −147.3 | −1.6 → −1.7 | pass → pass |
| pure_C2 | world_hard | 90 | −2.7 → −1.0 | −2.6 → −1.0 | −30.0 → −37.3 | −144.4 → −147.7 | −1.6 → −2.3 | tail → pass |
| pure_C2 | world_hard | 100 | −4.3 → −1.6 | −3.7 → −1.6 | −27.9 → −36.8 | −142.7 → −147.1 | −1.6 → −2.9 | tail → pass |
| pure_C2 | praat_soft | 50 | −0.3 → +0.0 | −0.3 → +0.0 | −51.8 → −∞ | −∞ → −∞ | +43.3 → −6.0 | peak → pass |
| pure_C2 | praat_soft | 80 | −1.3 → +0.0 | −1.3 → +0.0 | −39.3 → −∞ | −∞ → −∞ | +55.1 → −6.0 | peak, tail → pass |
| pure_C2 | praat_soft | 90 | −2.7 → +0.0 | −2.6 → +0.0 | −33.0 → −∞ | −∞ → −∞ | +60.3 → −6.0 | peak, tail → pass |
| pure_C2 | praat_soft | 100 | −4.4 → +0.0 | −3.7 → +0.0 | −29.8 → −∞ | −∞ → −∞ | +62.4 → −6.0 | peak, tail → pass |
| pure_G3 | world_hard | 50 | −0.3 → −0.3 | −0.3 → −0.3 | −30.7 → −32.6 | −145.7 → −147.8 | −2.0 → −2.5 | pass → pass |
| pure_G3 | world_hard | 80 | −1.4 → −1.4 | −1.3 → −1.3 | −27.5 → −31.2 | −144.7 → −150.6 | −2.0 → −3.5 | pass → pass |
| pure_G3 | world_hard | 90 | −2.9 → −1.6 | −2.7 → −1.6 | −25.6 → −30.9 | −143.2 → −150.9 | −1.9 → −3.8 | tail → pass |
| pure_G3 | world_hard | 100 | −6.0 → −1.6 | −4.8 → −1.6 | −23.9 → −30.9 | −140.0 → −150.9 | −1.9 → −3.8 | tail → pass |
| pure_G3 | praat_soft | 50 | −0.3 → −0.3 | −0.3 → −0.3 | −34.7 → −51.0 | −105.9 → −105.9 | +34.5 → −6.3 | peak, tail → pass |
| pure_G3 | praat_soft | 80 | −1.4 → −1.4 | −1.3 → −1.3 | −28.6 → −50.9 | −105.9 → −105.9 | +56.1 → −7.4 | peak, tail → pass |
| pure_G3 | praat_soft | 90 | −2.9 → −1.6 | −2.7 → −1.6 | −25.9 → −50.7 | −105.6 → −105.9 | +66.6 → −7.6 | peak, tail → pass |
| pure_G3 | praat_soft | 100 | −6.2 → −1.6 | −4.8 → −1.6 | −24.2 → −50.7 | −103.2 → −105.9 | +70.1 → −7.6 | peak, tail → pass |
| pure_A4 | world_hard | 50 | −0.3 → −0.3 | −0.3 → −0.3 | −32.8 → −33.5 | −146.1 → −150.4 | −2.3 → −2.7 | pass → pass |
| pure_A4 | world_hard | 80 | −1.4 → −1.4 | −1.4 → −1.4 | −29.9 → −32.3 | −145.0 → −153.1 | −2.3 → −3.8 | pass → pass |
| pure_A4 | world_hard | 90 | −3.4 → −1.7 | −3.6 → −1.8 | −28.0 → −31.9 | −143.0 → −153.5 | −2.3 → −4.1 | pass → pass |
| pure_A4 | world_hard | 100 | −12.2 → −1.7 | −25.3 → −1.8 | −24.6 → −31.9 | −134.3 → −153.5 | −2.3 → −4.1 | tail → pass |
| pure_A4 | praat_soft | 50 | −1.5 → −0.4 | −0.7 → −0.3 | −47.5 → −91.3 | −129.1 → −130.2 | +45.0 → −6.3 | peak → pass |
| pure_A4 | praat_soft | 80 | −3.8 → −1.4 | −2.8 → −1.4 | −33.8 → −88.6 | −127.8 → −130.1 | +59.4 → −7.4 | peak, tail → pass |
| pure_A4 | praat_soft | 90 | −6.5 → −1.7 | −5.5 → −1.8 | −29.3 → −88.2 | −126.5 → −130.1 | +65.6 → −7.7 | peak, tail → pass |
| pure_A4 | praat_soft | 100 | −17.7 → −1.7 | −26.8 → −1.8 | −22.4 → −88.2 | −116.3 → −130.1 | +55.0 → −7.7 | peak, tail → pass |

### B3 - smart low cut keyed to the original f0

Worst fundamental (H1) loss vs pitch-only on downward shifts: **−19.4 dB → −3.7 dB**; on upward shifts −3.7 → −3.7 dB.

| fixture | shift | lowcut | target f0 | H1 vs pitch-only dB | body dB | post-pitch fails |
|---|---|---|---|---|---|---|
| harm_C2 | −12 | 50 | 32.7 | −2.1 → −1.4 | −0.5 → −0.3 | tail → pass |
| harm_C2 | −12 | 100 | 32.7 | −5.0 → −2.7 | −1.9 → −0.8 | tail → tail |
| harm_C2 | −7 | 50 | 43.7 | −1.0 → −0.5 | −0.5 → −0.3 | tail → pass |
| harm_C2 | −7 | 100 | 43.7 | −3.8 → −1.5 | −1.9 → −0.8 | tail → tail |
| harm_C2 | +0 | 50 | 65.4 | −0.9 → −0.4 | −0.5 → −0.3 | tail → pass |
| harm_C2 | +0 | 100 | 65.4 | −3.6 → −1.4 | −1.9 → −0.8 | tail → tail |
| harm_C2 | +5 | 50 | 87.3 | −0.9 → −0.4 | −0.5 → −0.3 | tail → pass |
| harm_C2 | +5 | 100 | 87.3 | −3.6 → −1.4 | −1.9 → −0.8 | tail → tail |
| harm_C2 | +12 | 50 | 130.8 | −0.1 → −0.0 | −0.5 → −0.3 | tail → pass |
| harm_C2 | +12 | 100 | 130.8 | −0.3 → −0.1 | −1.9 → −0.8 | tail → tail |
| harm_G3 | −12 | 50 | 98.0 | −5.2 → −0.6 | −0.5 → −0.1 | pass → pass |
| harm_G3 | −12 | 100 | 98.0 | −19.4 → −3.6 | −1.9 → −0.4 | rms → pass |
| harm_G3 | −7 | 50 | 130.8 | −2.0 → −0.5 | −0.6 → −0.2 | pass → pass |
| harm_G3 | −7 | 100 | 130.8 | −11.2 → −3.6 | −2.0 → −0.9 | pass → pass |
| harm_G3 | +0 | 50 | 196.0 | −0.4 → −0.4 | −0.3 → −0.3 | pass → pass |
| harm_G3 | +0 | 100 | 196.0 | −3.6 → −3.6 | −1.9 → −1.9 | pass → pass |
| harm_G3 | +5 | 50 | 261.6 | −0.1 → −0.4 | −0.2 → −0.3 | pass → pass |
| harm_G3 | +5 | 100 | 261.6 | −1.3 → −3.6 | −0.8 → −1.8 | pass → pass |
| harm_G3 | +12 | 50 | 392.0 | −0.0 → −0.4 | −0.9 → −1.1 | pass → pass |
| harm_G3 | +12 | 100 | 392.0 | −0.3 → −3.6 | −1.0 → −2.9 | pass → pass |

### B4 - breathiness ran a second WORLD pass (harvest, default range); 1/0 at breathiness 0

pyworld calls in one render (G3 +5 st, cleanliness 50), **before**:

| mode | breath | calls |
|---|---|---|
| world_hard | 0.5 | dio(f0_floor=50, f0_ceil=500) → stonemask → cheaptrick → d4c → cheaptrick → d4c → synthesize → harvest → cheaptrick → d4c → synthesize |
| world_hard | 1.0 | dio(f0_floor=50, f0_ceil=500) → stonemask → cheaptrick → d4c → cheaptrick → d4c → synthesize |
| praat_soft | 0.5 | dio(f0_floor=50, f0_ceil=500) → stonemask → cheaptrick → d4c → harvest → cheaptrick → d4c → synthesize |
| praat_soft | 1.0 | (none) |

**after**:

| mode | breath | calls |
|---|---|---|
| world_hard | 0.5 | dio(f0_floor=50, f0_ceil=500, frame_period=5) → stonemask → cheaptrick → d4c → cheaptrick → d4c → synthesize |
| world_hard | 1.0 | dio(f0_floor=50, f0_ceil=500, frame_period=5) → stonemask → cheaptrick → d4c → cheaptrick → d4c → synthesize |
| praat_soft | 0.5 | (none) |
| praat_soft | 1.0 | (none) |

Breathiness 0.5 vs pitch-only:

| fixture | mode | shift | target f0 | f0 ¢ | inharm Δ dB | post-pitch fails |
|---|---|---|---|---|---|---|
| harm_C2 | world_hard | −12 | 32.7 | −1263 → +0 | +33.9 → −0.1 | f0, inharm → pass |
| harm_C2 | world_hard | +0 | 65.4 | −1191 → +0 | +34.8 → +0.1 | f0, inharm, tail → pass |
| harm_C2 | world_hard | +12 | 130.8 | +0 → +0 | +1.0 → +0.8 | tail → pass |
| harm_C2 | praat_soft | −12 | 32.7 | −1151 → +1200 | +33.4 → +0.1 | inharm, tail → pass |
| harm_C2 | praat_soft | +0 | 65.4 | −1161 → +0 | +34.8 → +0.0 | f0, inharm, tail → pass |
| harm_C2 | praat_soft | +12 | 130.8 | −1183 → −1200 | +35.6 → +34.5 | tail → pass |
| harm_G3 | world_hard | −12 | 98.0 | +0 → +0 | +3.7 → +3.6 | pass → pass |
| harm_G3 | world_hard | +0 | 196.0 | +0 → +0 | +0.2 → −0.1 | pass → pass |
| harm_G3 | world_hard | +12 | 392.0 | −0 → +0 | −3.4 → −2.8 | pass → pass |
| harm_G3 | praat_soft | −12 | 98.0 | +0 → +0 | +1.3 → +1.4 | tail → pass |
| harm_G3 | praat_soft | +0 | 196.0 | +0 → +0 | −0.0 → −0.0 | tail → pass |
| harm_G3 | praat_soft | +12 | 392.0 | −2 → −0 | +38.1 → +17.2 | inharm, tail → pass |
| harm_A4 | world_hard | −12 | 220.0 | +0 → +0 | +6.9 → +6.0 | pass → pass |
| harm_A4 | world_hard | +0 | 440.0 | +1 → +1 | +2.5 → +0.0 | pass → pass |
| harm_A4 | world_hard | +12 | 880.0 | +3 → +1 | +39.9 → +1.9 | peak, inharm → pass |
| harm_A4 | praat_soft | −12 | 220.0 | −0 → −1 | +9.1 → +25.3 | tail → pass |
| harm_A4 | praat_soft | +0 | 440.0 | +0 → −0 | +9.5 → +23.3 | tail → pass |
| harm_A4 | praat_soft | +12 | 880.0 | +2 → +1 | +46.8 → +24.5 | peak, inharm, tail → pass |
| harm_A5 | world_hard | −12 | 440.0 | +1200 → +1201 | +17.1 → +18.2 | peak → pass |
| harm_A5 | world_hard | +0 | 880.0 | +4 → +1 | +44.0 → +1.4 | peak, inharm → pass |
| harm_A5 | world_hard | +12 | 1760.0 | +3 → +1 | +47.1 → +41.4 | peak → pass |
| harm_A5 | praat_soft | −12 | 440.0 | +1209 → +1201 | +39.5 → +27.2 | peak, inharm, tail → pass |
| harm_A5 | praat_soft | +0 | 880.0 | −0 → +1 | +44.8 → +27.7 | peak, inharm, tail → pass |
| harm_A5 | praat_soft | +12 | 1760.0 | +2 → +2 | +30.3 → +29.9 | peak, tail → pass |

Breathiness 0.99 vs 1.0 (world_hard, shift 0):

| fixture | clean | waveform residual dB | inharm dB at 0.99 |
|---|---|---|---|
| harm_G3 | 0 | −4.4 → −72.8 | −41.6 → −41.9 (1.0: −41.9) |
| harm_G3 | 75 | −2.1 → −77.0 | −41.7 → −42.0 (1.0: −42.0) |
| test_2s_C4 | 0 | −5.7 → −65.9 | −31.4 → −31.9 (1.0: −31.9) |
| test_2s_C4 | 75 | −9.2 → −68.0 | −36.5 → −39.7 (1.0: −39.7) |

Breathiness 0:

| fixture | mode | hf_bias | warnings before | warnings after | NaN/inf samples | residual vs 0.01 dB |
|---|---|---|---|---|---|---|
| harm_G3 | world_hard | 0.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −63.2 → −65.1 |
| harm_G3 | world_hard | 1.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −61.9 → −63.0 |
| harm_G3 | praat_soft | 0.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −64.9 → −∞ |
| harm_G3 | praat_soft | 1.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −60.3 → −∞ |
| breathy_A3 | world_hard | 0.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −31.3 → −31.3 |
| breathy_A3 | world_hard | 1.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −31.0 → −29.5 |
| breathy_A3 | praat_soft | 0.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −33.3 → −∞ |
| breathy_A3 | praat_soft | 1.0 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | – | 0 → 0 | −30.9 → −∞ |

### B5 - WORLD cache keyed on md5 of the first 1000 samples

A = `lead_G3`, then B (same 300 ms of leading zeros for `lead_A4`) without resetting the cache, vs a cold render of B:

| B | mode | post | cache hit | len warm/cold | warm vs cold residual dB |
|---|---|---|---|---|---|
| lead_A4 | world_hard | cl 0 / br 1 | yes → no | 79600/66370 → 66370/66370 | 1.1 → −∞ |
| lead_A4 | world_soft | cl 0 / br 1 | yes → no | 79600/66370 → 66370/66370 | 3.0 → −∞ |
| lead_A4 | praat_soft | cl 50 / br 0.5 | yes → no | 66150/66150 → 66150/66150 | 6.7 → −∞ |
| lead_A4 | world_hard | cl 100 / br 1 | yes → no | 79600/66370 → 66370/66370 | 6.6 → −∞ |
| nolead_A4 | world_hard | cl 0 / br 1 | no → no | 53140/53140 → 53140/53140 | −∞ → −∞ |
| nolead_A4 | world_soft | cl 0 / br 1 | no → no | 53140/53140 → 53140/53140 | −∞ → −∞ |
| nolead_A4 | praat_soft | cl 50 / br 0.5 | no → no | 52920/52920 → 52920/52920 | −∞ → −∞ |
| nolead_A4 | world_hard | cl 100 / br 1 | no → no | 53140/53140 → 53140/53140 | −∞ → −∞ |

### E1 - cleanliness spiked the first samples of the file

| fixture | mode | clean | peak dBFS | peak at ms | pitch-only peak | NOLA warning |
|---|---|---|---|---|---|---|
| harm_G3 | praat_soft | 25 | +34.9 → −6.1 | 0.07 → 17.85 | −6.0 | yes → no |
| harm_G3 | praat_soft | 50 | +39.0 → −6.4 | 0.07 → 17.85 | −6.0 | yes → no |
| harm_G3 | praat_soft | 75 | +50.0 → −7.0 | 0.07 → 104.58 | −6.0 | yes → no |
| harm_G3 | praat_soft | 100 | +60.6 → −7.7 | 0.09 → 33.15 | −6.0 | yes → no |
| harm_G3 | world_hard | 25 | −1.4 → −1.4 | 984.74 → 984.74 | −1.2 | yes → no |
| harm_G3 | world_hard | 50 | −1.4 → −1.6 | 15.35 → 658.21 | −1.2 | yes → no |
| harm_G3 | world_hard | 75 | −1.4 → −2.3 | 15.35 → 627.60 | −1.2 | yes → no |
| harm_G3 | world_hard | 100 | −1.3 → −2.9 | 15.35 → 627.60 | −1.2 | yes → no |
| test_2s_C4 | praat_soft | 25 | +45.5 → −2.9 | 0.07 → 1770.66 | −2.4 | yes → no |
| test_2s_C4 | praat_soft | 50 | +51.5 → −3.1 | 0.07 → 1488.68 | −2.4 | yes → no |
| test_2s_C4 | praat_soft | 75 | +63.4 → −3.9 | 0.07 → 1124.78 | −2.4 | yes → no |
| test_2s_C4 | praat_soft | 100 | +76.0 → −4.6 | 0.07 → 1124.78 | −2.4 | yes → no |
| test_2s_C4 | world_hard | 25 | +0.3 → +0.3 | 15.94 → 1995.87 | +0.5 | yes → no |
| test_2s_C4 | world_hard | 50 | +0.3 → +0.0 | 15.94 → 1992.06 | +0.5 | yes → no |
| test_2s_C4 | world_hard | 75 | +0.3 → −0.8 | 15.94 → 1992.06 | +0.5 | yes → no |
| test_2s_C4 | world_hard | 100 | +0.4 → −1.4 | 15.94 → 1988.21 | +0.5 | yes → no |
| lead_G3 | praat_soft | 25 | −6.2 → −6.2 | 349.48 → 349.48 | −6.0 | yes → no |
| lead_G3 | praat_soft | 50 | −6.4 → −6.4 | 349.48 → 349.48 | −6.0 | yes → no |
| lead_G3 | praat_soft | 75 | −7.0 → −7.0 | 334.17 → 349.48 | −6.0 | yes → no |
| lead_G3 | praat_soft | 100 | −14.1 → −7.7 | 323.97 → 334.17 | −6.0 | yes → no |
| lead_G3 | world_hard | 25 | −3.4 → −3.5 | 316.37 → 535.76 | −3.4 | yes → no |
| lead_G3 | world_hard | 50 | −3.4 → −3.7 | 316.37 → 535.76 | −3.4 | yes → no |
| lead_G3 | world_hard | 75 | −3.4 → −4.4 | 316.37 → 719.43 | −3.4 | yes → no |
| lead_G3 | world_hard | 100 | −3.4 → −5.0 | 316.37 → 719.43 | −3.4 | yes → no |


## Root causes in the latest run

Post-pitch failures (1803):

| rank | cause | explains | sole | renders | meaning |
|---|---|---|---|---|---|
| 1 | breath_intended | 1459 | 1436 | 1331 | breathiness > 1 adds aperiodicity by design (fails the inharmonic rule) |
| 2 | clean | 327 | 308 | 295 | cleanliness stage (failure clears with cleanliness off) |
| 3 | lowcut | 21 | 17 | 18 | smart low cut stage (clears with low cut off) |
| 4 | breath | 19 | 19 | 19 | breathiness < 1 (clears with breathiness 1) |

All failures (14237):

| rank | cause | explains | sole | renders | meaning |
|---|---|---|---|---|---|
| 1 | pitch:tail | 3969 | 3969 | 3969 | pitch stage: energy past the source offset (the mode's release smear) |
| 2 | pitch:inharm | 3517 | 3517 | 3517 | pitch stage: mode adds inharmonic energy |
| 3 | pitch:peak | 2104 | 2104 | 2104 | pitch stage: output above 0 dBFS (onset spikes, hot real fixture) |
| 4 | pitch:f0 | 1787 | 1787 | 1787 | pitch stage: mode misses the target note |
| 5 | breath_intended | 1459 | 1436 | 1331 | breathiness > 1 adds aperiodicity by design (fails the inharmonic rule) |
| 6 | pitch:length | 859 | 859 | 859 | pitch/stretch stage: output length off by more than the tolerance |
| 7 | clean | 327 | 308 | 295 | cleanliness stage (failure clears with cleanliness off) |
| 8 | pitch_miss | 148 | 148 | 148 | pitch stage missed the target note; f0/inharm after it are measured against a pitch the post stages never received |
| 9 | pitch:rms | 50 | 50 | 50 | pitch stage: level drop |
| 10 | lowcut | 21 | 17 | 18 | smart low cut stage (clears with low cut off) |
| 11 | breath | 19 | 19 | 19 | breathiness < 1 (clears with breathiness 1) |

## Pass/fail rules (unchanged)

All thresholds live in `tests/sweep/sweep_config.py`. A failure is *inherited* when the group's pitch-only render fails the metric too and the render is not worse by more than the metric's margin (10 ms, 1 dB, 15 ¢, 6 dB, 6 dB, 6 dB). Other failures are attributed by re-rendering with one post-pitch stage switched off.

| metric | fails when |
|---|---|
| exception / nonfinite | any exception from `_run_pipeline`, any NaN/inf sample |
| length | \|len(out) − round(len(in) × stretch)\| > 10 ms |
| peak | peak > 0 dBFS |
| f0 | \|median YIN f0 of the note body − target\| > 15 cents, or no pitch found |
| inharm | inharmonic energy ratio worse than the input's by > 6 dB |
| tail | energy in the 200 ms after the source offset > -40 dB re note body |
| rms | note-body RMS drop vs input > 6 dB at cleanliness ≤ 50 % |

## Fixtures

| fixture | kind | truth | detected at load | dur s | tail | content |
|---|---|---|---|---|---|---|
| `harm_C2` | synthetic | C2 (65.41 Hz) | C2 (65.4 Hz) | 1.50 | yes | 1/k harmonic tone at C2 (65.41 Hz), noise -45 dB |
| `harm_G3` | synthetic | G3 (196.00 Hz) | G3 (196.0 Hz) | 1.50 | yes | 1/k harmonic tone at G3 (196.00 Hz), noise -45 dB |
| `harm_A4` | synthetic | A4 (440.00 Hz) | A4 (440.1 Hz) | 1.50 | yes | 1/k harmonic tone at A4 (440.00 Hz), noise -45 dB |
| `harm_A5` | synthetic | A5 (880.00 Hz) | A4 (440.1 Hz) | 1.50 | yes | 1/k harmonic tone at A5 (880.00 Hz), noise -45 dB |
| `vowel_D3` | synthetic | D3 (146.83 Hz) | D3 (146.8 Hz) | 1.50 | yes | band-limited pulse train at D3 (146.83 Hz) through /a/ formants 700/1220/2600 Hz |
| `breathy_A3` | synthetic | A3 (220.00 Hz) | F3 (170.4 Hz) | 1.50 | yes | 1/k^2 harmonics at A3 (220.00 Hz) + pitch-synchronous aspiration noise (HP 1 kHz, -12 dB) |
| `short_C4` | synthetic | C4 (261.63 Hz) | C4 (261.6 Hz) | 0.15 | no | 0.15 s 1/k harmonic tone at C4, no tail |
| `lead_G3` | synthetic | G3 (196.00 Hz) | G3 (196.0 Hz) | 1.80 | yes | 300 ms digital silence + 1/k tone at G3 + tail |
| `test_2s_C4` | real | C4 (261.63 Hz) | C4 (261.6 Hz) | 2.00 | no | tests/fixtures/test_2s_C4.wav (truth = detected note C4) |
| `test_10s_C4` | real | C4 (261.63 Hz) | C4 (261.6 Hz) | 10.00 | no | tests/fixtures/test_10s_C4.wav (truth = detected note C4) |
| `test_10s_C4_Fs4_tuned` | real | C4 (261.63 Hz) | C4 (261.6 Hz) | 10.00 | no | tests/fixtures/test_10s_C4_Fs4_tuned.wav (truth = detected note C4) |

## Top 20 worst combinations (latest run)

Ranked by post-pitch severity (sum of value / threshold over post-pitch failures).

| # | combination | fails | post sev | all sev | f0 ¢ | inharm Δ | tail | RMS Δ | peak | len Δ | causes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `test_10s_C4_Fs4_tuned|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | length, peak, f0, inharm | 28.0 | 30.8 | −1186 | +27.3 | – | +0.9 | +7.3 | −28 | length: inherited; peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 2 | `harm_A4|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm | 27.3 | 27.3 | −1199 | +43.7 | −45.1 | +0.5 | −0.1 | −3 | f0: breath_intended; inharm: breath_intended |
| 3 | `harm_A5|world_hard|-7|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm | 27.2 | 27.2 | −1199 | +43.1 | −41.7 | −1.9 | −2.5 | +5 | f0: breath_intended; inharm: breath_intended |
| 4 | `harm_A5|world_hard|+5|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm, tail | 27.1 | 29.2 | −1198 | +42.5 | −29.3 | −0.2 | −2.3 | +5 | f0: breath_intended; inharm: breath_intended; tail: inherited |
| 5 | `test_10s_C4_Fs4_tuned|world_hnm|+5|x1|lc0|cl0|rb0|br5|hb0` | length, peak, f0, inharm | 27.0 | 29.8 | −1186 | +24.5 | – | +0.8 | +5.8 | −28 | length: inherited; peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 6 | `harm_A4|world_hnm|+5|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm | 26.9 | 26.9 | −1199 | +41.5 | −45.8 | +0.4 | −1.1 | −3 | f0: breath_intended; inharm: breath_intended |
| 7 | `harm_A4|world_hnm|+0|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm | 26.7 | 26.7 | −1198 | +40.0 | −41.2 | +0.4 | −0.1 | −3 | f0: breath_intended; inharm: breath_intended |
| 8 | `short_C4|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | peak, f0, inharm | 26.5 | 26.5 | −1196 | +31.9 | – | +0.4 | +0.5 | −0 | peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 9 | `short_C4|world_hnm|+12|x1|lc0|cl25|rb0|br5|hb0` | peak, f0, inharm | 26.5 | 26.5 | −1196 | +31.9 | – | +0.4 | +0.5 | −0 | peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 10 | `short_C4|world_hnm|+12|x1|lc0|cl50|rb0|br5|hb0` | peak, f0, inharm | 26.5 | 26.5 | −1196 | +31.9 | – | +0.4 | +0.5 | −0 | peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 11 | `short_C4|world_hnm|+12|x1|lc0|cl75|rb0|br5|hb0` | peak, f0, inharm | 26.5 | 26.5 | −1196 | +31.9 | – | +0.4 | +0.5 | −0 | peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 12 | `short_C4|world_hnm|+12|x1|lc0|cl100|rb0|br5|hb0` | peak, f0, inharm | 26.5 | 26.5 | −1196 | +31.9 | – | +0.4 | +0.5 | −0 | peak: breath_intended; f0: breath_intended; inharm: breath_intended |
| 13 | `lead_G3|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm | 25.8 | 25.8 | −1199 | +35.1 | −44.3 | +0.5 | −2.3 | −4 | f0: breath_intended; inharm: breath_intended |
| 14 | `harm_G3|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm | 25.8 | 25.8 | −1199 | +34.7 | −50.3 | +0.8 | −0.0 | −3 | f0: breath_intended; inharm: breath_intended |
| 15 | `test_2s_C4|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | peak, f0, inharm | 24.6 | 28.1 | −1188 | +27.8 | – | +0.8 | +7.5 | −5 | peak: inherited; f0: breath_intended; inharm: breath_intended |
| 16 | `test_10s_C4|world_hnm|+12|x1|lc0|cl0|rb0|br5|hb0` | length, peak, f0, inharm | 24.6 | 30.4 | −1191 | +27.6 | – | +0.9 | +7.5 | −23 | length: inherited; peak: inherited; f0: breath_intended; inharm: breath_intended |
| 17 | `test_2s_C4|world_hnm|+5|x1|lc0|cl0|rb0|br5|hb0` | peak, f0, inharm | 24.2 | 27.3 | −1186 | +25.2 | – | +0.8 | +6.3 | −5 | peak: inherited; f0: breath_intended; inharm: breath_intended |
| 18 | `test_10s_C4|world_hnm|+5|x1|lc0|cl0|rb0|br5|hb0` | length, peak, f0, inharm | 24.1 | 29.5 | −1197 | +24.8 | – | +0.8 | +6.2 | −23 | length: inherited; peak: inherited; f0: breath_intended; inharm: breath_intended |
| 19 | `breathy_A3|world_hard|+12|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm, tail, rms | 22.4 | 26.2 | −1200 | +14.2 | −22.5 | −6.4 | −11.4 | +5 | f0: breath_intended; inharm: breath_intended; tail: inherited; rms: inherited |
| 20 | `breathy_A3|world_soft|+12|x1|lc0|cl0|rb0|br5|hb0` | f0, inharm, tail, rms | 22.3 | 26.2 | −1201 | +13.9 | −21.8 | −6.5 | −11.7 | +5 | f0: breath_intended; inharm: breath_intended; tail: inherited; rms: inherited |

## Failure counts per parameter (latest run)

*post-pitch* = renders with at least one post-pitch failure.

### Pairwise set

**mode**

| mode | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `world_hard` | 66 | 50 | 6 | 5 |  |  | 33 | 1 | 5 | 5 | 33 | 4 |
| `world_soft` | 66 | 56 | 5 | 0 |  |  | 22 | 13 | 8 | 13 | 38 | 1 |
| `world_vt` | 55 | 49 | 10 | 6 |  |  | 33 | 6 | 8 | 15 | 32 | 3 |
| `world_hnm` | 55 | 43 | 11 | 3 |  |  | 37 | 5 | 6 | 25 | 23 |  |
| `praat_soft` | 66 | 31 | 3 | 3 |  |  | 11 |  | 8 | 25 | 9 |  |
| `sine_spectral` | 66 | 66 | 9 | 9 |  |  | 44 | 7 | 43 | 64 | 39 | 2 |
| `stft_pitchshift` | 88 | 73 | 5 | 5 |  |  | 44 | 3 | 15 | 39 | 43 | 2 |

**shift**

| shift | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| -12 | 88 | 75 | 10 | 7 |  |  | 46 | 17 | 23 | 39 | 42 |  |
| -7 | 88 | 69 | 5 | 5 |  |  | 44 | 8 | 18 | 34 | 41 |  |
| 0 | 110 | 76 | 4 | 4 |  |  | 46 | 6 | 15 | 29 | 46 |  |
| 5 | 77 | 63 | 4 | 3 |  |  | 44 | 2 | 17 | 28 | 44 | 2 |
| 12 | 99 | 85 | 26 | 12 |  |  | 44 | 2 | 20 | 56 | 44 | 10 |

**stretch**

| stretch | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 242 | 148 | 12 | 11 |  |  | 4 | 27 | 34 | 76 | 79 | 5 |
| 1.5 | 220 | 220 | 37 | 20 |  |  | 220 | 8 | 59 | 110 | 138 | 7 |

**lowcut**

| lowcut | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 165 | 137 | 16 | 3 |  |  | 99 | 7 | 25 | 64 | 81 | 2 |
| 50 | 121 | 95 | 12 | 12 |  |  | 57 | 12 | 36 | 47 | 54 | 3 |
| 100 | 176 | 136 | 21 | 16 |  |  | 68 | 16 | 32 | 75 | 82 | 7 |

**clean**

| clean | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 99 | 83 | 22 | 10 |  |  | 44 | 13 | 28 | 63 | 45 | 3 |
| 25 | 99 | 83 | 10 | 8 |  |  | 55 | 6 | 22 | 38 | 51 | 7 |
| 50 | 99 | 83 | 3 | 3 |  |  | 66 | 1 | 13 | 35 | 52 | 2 |
| 75 | 77 | 59 | 4 | 4 |  |  | 24 | 11 | 12 | 22 | 35 |  |
| 100 | 88 | 60 | 10 | 6 |  |  | 35 | 4 | 18 | 28 | 34 |  |

**hfrb**

| hfrb | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 187 | 128 | 16 | 13 |  |  | 79 | 10 | 27 | 55 | 77 | 6 |
| 50 | 275 | 240 | 33 | 18 |  |  | 145 | 25 | 66 | 131 | 140 | 6 |

**breath**

| breath | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 99 | 83 | 6 | 6 |  |  | 44 | 7 | 11 | 31 | 51 | 4 |
| 0.5 | 77 | 59 | 3 | 3 |  |  | 35 | 3 | 20 | 35 | 35 |  |
| 1 | 88 | 79 | 5 | 5 |  |  | 44 | 14 | 15 | 33 | 45 |  |
| 2 | 99 | 83 | 18 | 7 |  |  | 66 | 7 | 30 | 53 | 50 | 3 |
| 5 | 99 | 64 | 17 | 10 |  |  | 35 | 4 | 17 | 34 | 36 | 5 |

**hfbias**

| hfbias | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 242 | 197 | 25 | 14 |  |  | 121 | 16 | 54 | 120 | 117 | 5 |
| 1 | 220 | 171 | 24 | 17 |  |  | 103 | 19 | 39 | 66 | 100 | 7 |

### Grid set

**mode**

| mode | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `world_hard` | 1375 | 1126 | 375 | 22 |  |  |  | 314 | 75 | 434 | 811 | 15 |
| `world_soft` | 1375 | 1168 | 342 | 3 |  |  |  | 425 | 142 | 505 | 770 | 15 |
| `world_vt` | 1375 | 1167 | 348 | 5 |  |  |  | 423 | 143 | 504 | 770 | 14 |
| `world_hnm` | 1375 | 976 | 278 | 22 |  |  | 250 | 407 | 178 | 720 | 35 |  |
| `praat_soft` | 1375 | 465 | 0 | 0 |  |  |  | 5 | 130 | 420 |  |  |
| `sine_spectral` | 1375 | 1345 | 180 | 180 |  |  |  | 440 | 905 | 1245 | 740 | 90 |
| `stft_pitchshift` | 1375 | 920 | 70 | 70 |  |  |  | 140 | 250 | 650 | 605 | 25 |

**shift**

| shift | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| -12 | 1925 | 1547 | 242 | 11 |  |  | 50 | 777 | 465 | 915 | 803 |  |
| -7 | 1925 | 1612 | 324 | 45 |  |  | 50 | 512 | 421 | 1069 | 810 | 10 |
| 0 | 1925 | 1261 | 290 | 23 |  |  | 50 | 317 | 206 | 695 | 617 | 5 |
| 5 | 1925 | 1427 | 348 | 87 |  |  | 50 | 303 | 394 | 926 | 776 | 35 |
| 12 | 1925 | 1320 | 389 | 136 |  |  | 50 | 245 | 337 | 873 | 725 | 109 |

**clean**

| clean | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1925 | 1625 | 349 | 6 |  |  | 50 | 581 | 449 | 1166 | 761 | 14 |
| 25 | 1925 | 1504 | 343 | 68 |  |  | 50 | 483 | 393 | 989 | 749 | 65 |
| 50 | 1925 | 1453 | 342 | 81 |  |  | 50 | 431 | 367 | 911 | 744 | 80 |
| 75 | 1925 | 1317 | 280 | 60 |  |  | 50 | 344 | 316 | 750 | 740 |  |
| 100 | 1925 | 1268 | 279 | 87 |  |  | 50 | 315 | 298 | 662 | 737 |  |

**breath**

| breath | renders | failing | post-pitch | post excl. intended | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1925 | 1337 | 65 | 65 |  |  | 50 | 414 | 360 | 634 | 744 | 32 |
| 0.5 | 1925 | 1349 | 56 | 56 |  |  | 50 | 423 | 352 | 635 | 744 | 32 |
| 1 | 1925 | 1359 | 58 | 58 |  |  | 50 | 430 | 360 | 650 | 743 | 32 |
| 2 | 1925 | 1504 | 462 | 61 |  |  | 50 | 426 | 362 | 1077 | 744 | 32 |
| 5 | 1925 | 1618 | 952 | 62 |  |  | 50 | 461 | 389 | 1482 | 756 | 31 |

### Per fixture

| fixture | renders | failing | post-pitch | post excl. intended |
|---|---|---|---|---|
| `harm_C2` | 948 | 813 | 138 | 15 |
| `harm_G3` | 948 | 736 | 167 | 0 |
| `harm_A4` | 948 | 784 | 190 | 48 |
| `harm_A5` | 948 | 898 | 64 | 55 |
| `vowel_D3` | 948 | 792 | 172 | 11 |
| `breathy_A3` | 948 | 741 | 198 | 158 |
| `short_C4` | 948 | 587 | 161 | 1 |
| `lead_G3` | 948 | 761 | 167 | 5 |
| `test_2s_C4` | 948 | 577 | 132 | 13 |
| `test_10s_C4` | 948 | 590 | 127 | 13 |
| `test_10s_C4_Fs4_tuned` | 948 | 624 | 125 | 13 |

<!-- frozen copy of the pre-fix report; tests/sweep/baseline/prefix_report.md -->
## Appendix: pre-fix report (frozen)

Generated 2026-10-22 by `tests/sweep/report.py` from a run of `python tests/sweep/run_sweep.py`.
This sweep measures; nothing in `server/` was changed.

```bash
python tests/sweep/run_sweep.py          # full sweep + probes + this report
python tests/sweep/report.py             # rebuild this report from tests/sweep/out/
```

- git `a34b4fd`, Python 3.14.2, Windows-11-10.0.26200-SP0, 22 worker processes, 41.33 min wall clock
- **10428 renders** through `server.routes.audio._run_pipeline` (called directly, no HTTP), settings built with `ProcessRequest(...).model_dump()` exactly as `/api/process` does
- Counterfactual replica fidelity: 990/990 checks bit-identical to `_run_pipeline`
- librosa imported in any process: no

### Root causes ranked by failures explained

#### Post-pitch defects only

12189 failed (render, metric) pairs belong to the post-pitch stages: they are neither inherited from the pitch-only render nor measured on a pitch the stage never received. *breath_intended* (breathiness > 1 failing the inharmonic rule by design) is left out of this view.

| rank | cause | explains | sole | renders | share of post-pitch failures |
|---|---|---|---|---|---|
| 1 | B1 | 3600 | 2938 | 2584 | 30 % |
| 2 | B4 | 2603 | 1931 | 2238 | 21 % |
| 3 | breath_resynth | 1686 | 1235 | 1520 | 14 % |
| 4 | E1 | 826 | 567 | 826 | 7 % |
| 5 | B2 | 782 | 323 | 717 | 6 % |
| 6 | clean_mask | 555 | 100 | 549 | 5 % |
| 7 | E2 | 55 | 53 | 42 | 0 % |
| 8 | lowcut_design | 35 | 1 | 35 | 0 % |
| 9 | B3 | 21 | 4 | 21 | 0 % |

#### All causes

22922 failed (render, metric) pairs in total. *explains* counts every failure the cause is credited with, alone or jointly. *sole* counts failures it is the only credited cause for. Columns overlap, so they do not sum to the total.

| rank | cause | explains | sole | renders | share | what |
|---|---|---|---|---|---|---|
| 1 | breath_intended | 3886 | 3420 | 2949 | 17 % | breathiness > 1 adds aperiodicity (intended effect, fails the inharmonic rule) |
| 2 | **B1** | 3600 | 2938 | 2584 | 16 % | B1 - cleanliness masks the ORIGINAL f0's harmonics (cached WORLD f0 of the input) |
| 3 | pitch:inharm | 3233 | 3233 | 3233 | 14 % | pitch stage: mode adds inharmonic energy |
| 4 | pitch:tail | 2730 | 2730 | 2730 | 12 % | pitch stage: energy past the source offset (release smear of the pitch mode) - inherited tail |
| 5 | **B4** | 2603 | 1931 | 2238 | 11 % | B4 - breathiness re-analyses with harvest (default 71-800 Hz) instead of the right f0 |
| 6 | breath_resynth | 1686 | 1235 | 1520 | 7 % | breathiness second WORLD resynthesis itself (amount < 1, correct f0 does not help) |
| 7 | pitch:f0 | 1643 | 1643 | 1643 | 7 % | pitch stage: mode misses the target note (see pitch-stage table) |
| 8 | pitch:peak | 1536 | 1536 | 1536 | 7 % | pitch stage: mode output above 0 dBFS (e.g. onset spikes, hot real fixture) |
| 9 | pitch:length | 859 | 859 | 859 | 4 % | pitch/stretch stage: output length off by more than the tolerance (see length table) |
| 10 | **E1** | 826 | 567 | 826 | 4 % | E1 - cleanliness ISTFT edge blow-up: no leading pad, first samples / ~0 window sum (NOLA) |
| 11 | **B2** | 782 | 323 | 717 | 3 % | B2 - cleanliness 100 %: 10 Hz mask < 21.5 Hz STFT bin, even with correct f0 |
| 12 | pitch_miss | 694 | 694 | 693 | 3 % | pitch stage missed the target note; later f0/inharm failures are measured against a pitch the post stages never received (not credited to post-pitch bugs) |
| 13 | clean_mask | 555 | 100 | 549 | 2 % | cleanliness 25-75 % mask with correct f0 (STFT smear / harmonic loss below B2's extreme) |
| 14 | **E2** | 55 | 53 | 42 | 0 % | E2 - cleanliness's own pyin f0 (no WORLD cache) is wrong, e.g. target outside its 50-500 Hz range |
| 15 | pitch:rms | 38 | 38 | 38 | 0 % | pitch stage: level drop |
| 16 | lowcut_design | 35 | 1 | 35 | 0 % | smart low cut with correct f0 (0.85 x f0 cutoff, filtfilt) |
| 17 | **B3** | 21 | 4 | 21 | 0 % | B3 - smart low cut keyed to the original f0 (state.detected_pitch) |

### Pass/fail rules

All thresholds live in `tests/sweep/sweep_config.py`.

| metric | fails when |
|---|---|
| exception / nonfinite | any exception from `_run_pipeline`, any NaN/inf sample |
| length | \|len(out) − round(len(in) × stretch)\| > 10 ms (WORLD rounds to 5 ms frames; exact-rule count given below) |
| peak | peak > 0 dBFS |
| f0 | \|median YIN f0 of the note body − target\| > 15 cents, or no pitch found |
| inharm | inharmonic energy ratio (between target harmonics / total) worse than the input's by > 6 dB |
| tail | energy in the 200 ms after the source offset (× stretch) > -40 dB re note body (fixtures with a silent tail only) |
| rms | note-body RMS drop vs input > 6 dB, checked only at cleanliness ≤ 50 % |

**Attribution.** For every failed (render, metric) the worker asks, in order: is it *inherited* (the group's pitch-only render fails it too and the render is not worse by more than the metric's threshold)? Does one counterfactual toggle clear it - **F1** (cleanliness gets the cached f0 rescaled to the target), **F3** (low cut from the target f0), **F4** (breathiness analysed with the correct f0), **F5** (cleanliness input pre-padded, isolating E1), **F6** (cleanliness without a WORLD cache gets the correct f0 instead of its own pyin, isolating E2)? Only all toggles together (*joint*)? With all toggles on, does switching one stage off clear it (*B2* at cleanliness 100, *clean_mask* below, *breath_resynth*, *breath_intended*, *lowcut_design*), or only switching several off (*multi*)? Toggles change arguments to the unmodified server functions (`tests/sweep/counterfactual.py`).

### Fixtures

Synthetic WAVs are written to `tests/sweep/out/fixtures/`. *Detected* is what `/api/load-audio` stores in `state.detected_pitch` (the smart low cut uses it); targets are truth note + shift.

| fixture | kind | truth | detected | dur s | tail | input inharm dB | content |
|---|---|---|---|---|---|---|---|
| `harm_C2` | synthetic | C2 (65.41 Hz) | C2 (65.4 Hz) | 1.50 | yes | −36.8 | 1/k harmonic tone at C2 (65.41 Hz), noise -45 dB |
| `harm_G3` | synthetic | G3 (196.00 Hz) | G3 (196.0 Hz) | 1.50 | yes | −41.8 | 1/k harmonic tone at G3 (196.00 Hz), noise -45 dB |
| `harm_A4` | synthetic | A4 (440.00 Hz) | A4 (440.1 Hz) | 1.50 | yes | −47.9 | 1/k harmonic tone at A4 (440.00 Hz), noise -45 dB |
| `harm_A5` | synthetic | A5 (880.00 Hz) | A4 (440.1 Hz) | 1.50 | yes | −48.9 | 1/k harmonic tone at A5 (880.00 Hz), noise -45 dB |
| `vowel_D3` | synthetic | D3 (146.83 Hz) | D3 (146.8 Hz) | 1.50 | yes | −42.4 | band-limited pulse train at D3 (146.83 Hz) through /a/ formants 700/1220/2600 Hz |
| `breathy_A3` | synthetic | A3 (220.00 Hz) | F3 (170.4 Hz) | 1.50 | yes | −20.0 | 1/k^2 harmonics at A3 (220.00 Hz) + pitch-synchronous aspiration noise (HP 1 kHz, -12 dB) |
| `short_C4` | synthetic | C4 (261.63 Hz) | C4 (261.6 Hz) | 0.15 | no | −38.9 | 0.15 s 1/k harmonic tone at C4, no tail |
| `lead_G3` | synthetic | G3 (196.00 Hz) | G3 (196.0 Hz) | 1.80 | yes | −41.8 | 300 ms digital silence + 1/k tone at G3 + tail |
| `test_2s_C4` | real | C4 (261.63 Hz) | C4 (261.6 Hz) | 2.00 | no | −32.4 | tests/fixtures/test_2s_C4.wav (truth = detected note C4) |
| `test_10s_C4` | real | C4 (261.63 Hz) | C4 (261.6 Hz) | 10.00 | no | −32.4 | tests/fixtures/test_10s_C4.wav (truth = detected note C4) |
| `test_10s_C4_Fs4_tuned` | real | C4 (261.63 Hz) | C4 (261.6 Hz) | 10.00 | no | −32.2 | tests/fixtures/test_10s_C4_Fs4_tuned.wav (truth = detected note C4) |

### Coverage

| set | renders | definition |
|---|---|---|
| pairwise | 462 | 42 covering-array rows × 11 fixtures; verified pair coverage 100.0% over mode × shift × stretch × lowcut × cleanliness × hf_rollback × breathiness × hf_bias |
| grid | 9625 | cleanliness [0.0, 25.0, 50.0, 75.0, 100.0] × breathiness [0.0, 0.5, 1.0, 2.0, 5.0] × shift [-12, -7, 0, 5, 12] × 7 modes × 11 fixtures (stretch 1, lowcut 0, rollback 0, hf_bias 0) |
| baseline | 770 | pitch-only render of every (fixture, mode, shift, stretch) |

A render can belong to several sets; counts below are per set.

### Suspected bugs


#### B1 - cleanliness gets the original audio's f0: **CONFIRMED**

*Rule: CONFIRMED if at G3 +5 st / cleanliness 100 the cleanliness stage loses > 6 dB more with the app's f0 than with the rescaled f0, the app's output fails f0 and the rescaled one does not, and the sweep attributes failures to B1.*

- Your quick check reproduces: G3 +5 st (→ C4), world_hard, cleanliness 100 - the cleanliness stage changes the note-body RMS by **−23.0 dB** with the cached f0 (196.0 Hz, the original G3) vs **−7.4 dB** with that f0 rescaled to 261.6 Hz (you measured 23.7 vs 7.6 dB). Output f0 error +702 ¢ vs −0 ¢.
- In the sweep F1 alone clears **3600 failed metrics in 2584 renders**. By shift: -12 st: 1060, -7 st: 1039, +0 st: 0, +5 st: 1394, +12 st: 107 (shift 0 has the right f0, so ~0 is expected there).
- The cache exists only for world_* modes or breathiness ≠ 1. B1 failures by (WORLD mode, breath ≠ 1): WORLD/breath≠1: 1985, WORLD/breath=1: 471, non-WORLD/breath≠1: 1144, non-WORLD/breath=1: 0. Non-WORLD modes with breath = 1 run pyin on the processed audio and are not affected.

| fixture | shift | target | clean | cached f0 | target f0 | stage dB (app) | stage dB (F1) | f0 ¢ app | f0 ¢ F1 | fails app | fails F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| harm_G3 | −12 | G2 | 50 | 196.0 | 98.0 | −3.6 | −0.3 | +1200 | +0 | peak, f0, tail | peak, tail |
| harm_G3 | −12 | G2 | 100 | 196.0 | 98.0 | −9.5 | −8.6 | +1200 | +0 | peak, f0, tail | peak, tail |
| harm_G3 | −7 | C3 | 50 | 196.0 | 130.8 | −6.1 | −0.3 | +0 | +0 | peak, tail | peak, tail |
| harm_G3 | −7 | C3 | 100 | 196.0 | 130.8 | −17.8 | −6.1 | +702 | +0 | peak, f0, tail | peak, tail |
| harm_G3 | +0 | G3 | 50 | 196.0 | 196.0 | −0.3 | −0.3 | +0 | +0 | tail | tail |
| harm_G3 | +0 | G3 | 100 | 196.0 | 196.0 | −6.0 | −6.0 | +0 | +0 | tail | tail |
| harm_G3 | +5 | C4 | 50 | 196.0 | 261.6 | −7.0 | −0.3 | −0 | −0 | tail, rms | tail |
| harm_G3 | +5 | C4 | 100 | 196.0 | 261.6 | −23.0 | −7.4 | +702 | −0 | f0, inharm, tail | tail |
| harm_G3 | +12 | G4 | 50 | 196.0 | 392.0 | −0.3 | −0.3 | +0 | +0 | tail | tail |
| harm_G3 | +12 | G4 | 100 | 196.0 | 392.0 | −9.4 | −9.4 | +0 | +0 | tail | tail |
| test_2s_C4 | −12 | C3 | 50 | 261.6 | 130.8 | −3.8 | −0.3 | +1200 | +0 | peak, f0 | peak |
| test_2s_C4 | −12 | C3 | 100 | 261.6 | 130.8 | −10.7 | −6.5 | +1200 | +0 | peak, f0 | peak |
| test_2s_C4 | −7 | F3 | 50 | 261.6 | 174.6 | −8.5 | −0.3 | −0 | −0 | peak, rms | peak |
| test_2s_C4 | −7 | F3 | 100 | 261.6 | 174.6 | −23.7 | −7.1 | +701 | −0 | peak, f0 | peak |
| test_2s_C4 | +0 | C4 | 50 | 261.6 | 261.6 | −0.3 | −0.3 | −0 | −0 | peak | peak |
| test_2s_C4 | +0 | C4 | 100 | 261.6 | 261.6 | −7.2 | −7.3 | −0 | −0 | peak | peak |
| test_2s_C4 | +5 | F4 | 50 | 261.6 | 349.2 | −12.8 | −0.3 | +1 | +0 | inharm, rms | pass |
| test_2s_C4 | +5 | F4 | 100 | 261.6 | 349.2 | −35.2 | −10.0 | +703 | +0 | f0, inharm | pass |
| test_2s_C4 | +12 | C5 | 50 | 261.6 | 523.3 | −0.3 | −0.3 | +0 | +1 | pass | pass |
| test_2s_C4 | +12 | C5 | 100 | 261.6 | 523.3 | −14.6 | −14.8 | +1 | +1 | pass | pass |

Same input, non-WORLD mode (praat_soft, +5 st): turning breathiness from 1.0 to 0.5 switches cleanliness from pyin-on-the-output to the cached original f0:

| clean | breath | cleanliness f0 source | RMS Δ | f0 ¢ | inharm Δ | fails |
|---|---|---|---|---|---|---|
| 50.0 | 1.0 | pyin (no cache) | −1.8 | −0 | +0.8 | peak |
| 50.0 | 0.5 | WORLD cache | −7.5 | −0 | +9.5 | inharm, tail, rms |
| 50.0 | 0.5 | WORLD cache + F1 (rescaled) | −1.8 | −0 | −2.1 | tail |
| 100.0 | 1.0 | pyin (no cache) | −9.5 | −0 | −0.8 | peak, tail |
| 100.0 | 0.5 | WORLD cache | −24.4 | −1031 | +38.5 | f0, inharm, tail |
| 100.0 | 0.5 | WORLD cache + F1 (rescaled) | −8.6 | −0 | −1.5 | tail |

#### B2 - mask narrower than an STFT bin: **CONFIRMED** (harmonic loss yes; release smear yes; sustained ringing no)

*Rule: CONFIRMED if, with the exact f0 supplied, cleanliness 100 removes ≥ 3 dB of harmonic energy on every noise-free tone while FWHM < bin width. Ringing is reported separately: tail = 0-200 ms after offset (the sweep rule), late tail = 50-200 ms (sustained ringing).*

- At 100 % the Gaussian FWHM is 10 Hz = 0.46 of the 21.53 Hz bin (Hann main lobe ±43 Hz). With the **exact** f0 the mask still removes pure_C2 −4.4 dB (H1 −3.7), pure_G3 −6.2 dB (H1 −4.8), pure_A4 −11.7 dB (H1 −25.4) of harmonic energy. The loss depends on where each harmonic falls between bin centres (picket fence), so it is f0-dependent, and it is the same through the pyin path.
- Ringing: the 0-200 ms tail rises steadily with cleanliness, from −58.8, −49.0, −54.6 dB at 10 % to −27.7 dB, −26.9 dB, −27.4 dB at 100 %. The 50-200 ms late tail stays at −∞ dB, −∞ dB, −∞ dB: the energy is a release smear confined to one STFT window (46 ms), not a sustained ring.
- In the sweep B2 (cleanliness 100, failure persists with every toggle and clears without cleanliness) explains **782 failed metrics in 717 renders**. The same mechanism at 25-75 % (*clean_mask*) explains 555 in 549.

| tone | clean | FWHM Hz | FWHM/bin | harm Δ dB (exact f0) | H1 Δ dB | harm Δ dB (pyin) | tail dB | late tail dB | inharm dB |
|---|---|---|---|---|---|---|---|---|---|
| pure_C2 | 0 | 200.0 | 9.29 | +0.0 | +0.0 | +0.0 | −∞ | −∞ | −36.9 |
| pure_C2 | 50 | 105.0 | 4.88 | −0.3 | −0.3 | −0.3 | −49.5 | −∞ | −36.9 |
| pure_C2 | 70 | 67.0 | 3.11 | −0.8 | −0.8 | −0.8 | −42.2 | −∞ | −36.8 |
| pure_C2 | 80 | 48.0 | 2.23 | −1.3 | −1.3 | −1.3 | −37.1 | −∞ | −36.8 |
| pure_C2 | 90 | 29.0 | 1.35 | −2.7 | −2.6 | −2.7 | −30.8 | −∞ | −36.6 |
| pure_C2 | 100 | 10.0 | 0.46 | −4.4 | −3.7 | −4.4 | −27.7 | −∞ | −36.1 |
| pure_G3 | 0 | 200.0 | 9.29 | +0.0 | +0.0 | +0.0 | −∞ | −∞ | −42.2 |
| pure_G3 | 50 | 105.0 | 4.88 | −0.3 | −0.3 | −0.3 | −41.1 | −∞ | −42.2 |
| pure_G3 | 70 | 67.0 | 3.11 | −0.8 | −0.8 | −0.8 | −35.8 | −∞ | −42.2 |
| pure_G3 | 80 | 48.0 | 2.23 | −1.4 | −1.3 | −1.4 | −32.6 | −∞ | −42.1 |
| pure_G3 | 90 | 29.0 | 1.35 | −2.9 | −2.7 | −2.9 | −29.2 | −∞ | −41.7 |
| pure_G3 | 100 | 10.0 | 0.46 | −6.2 | −4.8 | −6.2 | −26.9 | −∞ | −40.6 |
| pure_A4 | 0 | 200.0 | 9.29 | +0.0 | +0.0 | +0.0 | −∞ | −∞ | −52.7 |
| pure_A4 | 50 | 105.0 | 4.88 | −0.3 | −0.3 | −0.3 | −44.7 | −∞ | −52.7 |
| pure_A4 | 70 | 67.0 | 3.11 | −0.8 | −0.8 | −0.8 | −38.0 | −∞ | −52.2 |
| pure_A4 | 80 | 48.0 | 2.23 | −1.4 | −1.4 | −1.4 | −34.4 | −∞ | −50.6 |
| pure_A4 | 90 | 29.0 | 1.35 | −3.4 | −3.6 | −3.4 | −31.1 | −∞ | −48.5 |
| pure_A4 | 100 | 10.0 | 0.46 | −11.7 | −25.4 | −11.6 | −27.4 | −∞ | −49.2 |

#### B3 - smart low cut uses the original f0: **CONFIRMED**

*Rule: CONFIRMED if on some downward shift the cutoff exceeds the new fundamental and the fundamental (H1) loses > 3 dB more than with the cutoff computed from the target f0.*

- On downward shifts the cutoff is above the new fundamental in 18/32 probe cases (up to 1.70 × f0 at −12 st / 100 %). H1 then drops by up to −19.4 dB vs the pitch-only render, against −3.7 dB when the cutoff comes from the target.
- The reverse happens on upward shifts: the cutoff is too *low*, so the app cuts less than intended (17/32 cases where the target-f0 cutoff would remove > 1 dB more H1).
- The sweep rules rarely catch it. Losing H1 changes body RMS by only −2.8 dB at worst, so F3 alone clears **21 failed metrics in 21 renders**. The damage is spectral (a thin, fundamental-less low end) rather than a level drop the rules measure.

| fixture | mode | shift | lowcut | detected f0 | target f0 | cutoff | cutoff/f0 | H1 Δ app | H1 Δ F3 | RMS Δ app | fails app |
|---|---|---|---|---|---|---|---|---|---|---|---|
| harm_C2 | praat_soft | −12 | 50 | 65.4 | 32.7 | 37.8 | 1.16 | −2.1 | −0.7 | −0.5 | f0, tail |
| harm_C2 | praat_soft | −12 | 100 | 65.4 | 32.7 | 55.6 | 1.70 | −5.0 | −1.0 | −1.9 | f0, tail |
| harm_C2 | praat_soft | −7 | 50 | 65.4 | 43.7 | 37.8 | 0.87 | −1.0 | −0.3 | −0.5 | f0, inharm, tail |
| harm_C2 | praat_soft | −7 | 100 | 65.4 | 43.7 | 55.6 | 1.27 | −3.8 | −0.9 | −1.9 | f0, inharm, tail |
| harm_C2 | praat_soft | +0 | 50 | 65.4 | 65.4 | 37.8 | 0.58 | −0.9 | −0.9 | −0.5 | tail |
| harm_C2 | praat_soft | +0 | 100 | 65.4 | 65.4 | 55.6 | 0.85 | −3.6 | −3.6 | −1.9 | tail |
| harm_C2 | praat_soft | +5 | 50 | 65.4 | 87.3 | 37.8 | 0.43 | −0.9 | −2.0 | −0.5 | f0, inharm, tail |
| harm_C2 | praat_soft | +5 | 100 | 65.4 | 87.3 | 55.6 | 0.64 | −3.6 | −8.4 | −1.9 | f0, inharm, tail |
| harm_C2 | praat_soft | +12 | 50 | 65.4 | 130.8 | 37.8 | 0.29 | −0.1 | −0.5 | −0.5 | f0, inharm, tail |
| harm_C2 | praat_soft | +12 | 100 | 65.4 | 130.8 | 55.6 | 0.43 | −0.3 | −3.6 | −1.9 | f0, inharm, tail |
| harm_G3 | praat_soft | −12 | 50 | 196.0 | 98.0 | 93.3 | 0.95 | −5.2 | −0.6 | −0.5 | pass |
| harm_G3 | praat_soft | −12 | 100 | 196.0 | 98.0 | 166.6 | 1.70 | −19.4 | −3.6 | −1.9 | rms |
| harm_G3 | praat_soft | −7 | 50 | 196.0 | 130.8 | 93.3 | 0.71 | −2.0 | −0.5 | −0.6 | inharm |
| harm_G3 | praat_soft | −7 | 100 | 196.0 | 130.8 | 166.6 | 1.27 | −11.2 | −3.6 | −2.0 | inharm |
| harm_G3 | praat_soft | +0 | 50 | 196.0 | 196.0 | 93.3 | 0.48 | −0.4 | −0.4 | −0.3 | pass |
| harm_G3 | praat_soft | +0 | 100 | 196.0 | 196.0 | 166.6 | 0.85 | −3.6 | −3.6 | −1.9 | pass |
| harm_G3 | praat_soft | +5 | 50 | 196.0 | 261.6 | 93.3 | 0.36 | −0.1 | −0.4 | −0.2 | inharm |
| harm_G3 | praat_soft | +5 | 100 | 196.0 | 261.6 | 166.6 | 0.64 | −1.3 | −3.6 | −0.8 | inharm |
| harm_G3 | praat_soft | +12 | 50 | 196.0 | 392.0 | 93.3 | 0.24 | −0.0 | −0.4 | −0.9 | inharm |
| harm_G3 | praat_soft | +12 | 100 | 196.0 | 392.0 | 166.6 | 0.43 | −0.3 | −3.6 | −1.0 | inharm |

#### B4 - second WORLD pass with harvest's default range; 1/0 at breathiness 0: **CONFIRMED** (divide by zero: **CONFIRMED, benign**)

*Rule: CONFIRMED if instrumentation shows `harvest` called without a range after the pipeline's own analysis, and some fixture fails with harvest but passes with the correct-f0 analysis. Divide by zero: CONFIRMED if numpy's divide-by-zero warning fires; benign if the output stays finite.*

pyworld calls logged during one `_run_pipeline` (G3 +5 st, cleanliness 50):

| mode | breath | pyworld calls in order |
|---|---|---|
| world_hard | 0.5 | dio(f0_floor=50, f0_ceil=500) → stonemask → cheaptrick → d4c → cheaptrick → d4c → synthesize → harvest() → cheaptrick → d4c → synthesize |
| praat_soft | 0.5 | dio(f0_floor=50, f0_ceil=500) → stonemask → cheaptrick → d4c → harvest() → cheaptrick → d4c → synthesize |
| praat_soft | 1.0 | (no WORLD calls) |

- With breath ≠ 1 every render runs a third analysis and a second synthesis. For non-WORLD modes the step-0 `sp`/`ap` is computed but then thrown away (`apply_breathiness(world_cache=None)`), and its f0 only reaches cleanliness, where it causes B1.
- Range: harvest's default 71-800 Hz misses the pitch in 7/12 probe signals: harm_C2 −12 (target 32.7 Hz → harvest no pitch, voiced 0.00); harm_C2 +0 (target 65.4 Hz → harvest no pitch, voiced 0.00); harm_C2 +12 (target 130.8 Hz → harvest no pitch, voiced 0.00); harm_A4 +12 (target 880.0 Hz → harvest 91.0 Hz, voiced 0.25); harm_A5 −12 (target 440.0 Hz → harvest 297.1 Hz, voiced 0.35); harm_A5 +0 (target 880.0 Hz → harvest 91.3 Hz, voiced 0.39); harm_A5 +12 (target 1760.0 Hz → harvest 88.5 Hz, voiced 0.61). 7/12 cases fail f0 with harvest but not with the correct f0, or are > 6 dB more inharmonic. The dio 50-500 column shows whether the range used elsewhere would be enough.
- Sweep: F4 alone clears **2603 failed metrics in 2238 renders**. Another 1686 in 1520 renders persist with the correct f0 and clear only without breathiness: the resynthesis itself.

Breathiness 0.5 on the praat_soft output (cell = f0 error / inharmonic Δ):

| fixture | shift | target f0 | harvest f0 | harvest voiced | app (harvest) | dio 50-500 | correct f0 |
|---|---|---|---|---|---|---|---|
| harm_C2 | −12 | 32.7 | – | 0.00 | −1151 ¢ / +33.4 dB | +1200 ¢ / +0.1 dB | −0 ¢ / +13.4 dB |
| harm_C2 | +0 | 65.4 | – | 0.00 | −1161 ¢ / +34.8 dB | +0 ¢ / +0.1 dB | +0 ¢ / +0.1 dB |
| harm_C2 | +12 | 130.8 | – | 0.00 | −1183 ¢ / +35.6 dB | −1200 ¢ / +34.6 dB | +0 ¢ / +20.8 dB |
| harm_G3 | −12 | 98.0 | 98.0 | 0.66 | +0 ¢ / +1.3 dB | −0 ¢ / +1.3 dB | +0 ¢ / +1.2 dB |
| harm_G3 | +0 | 196.0 | 196.0 | 0.67 | +0 ¢ / −0.0 dB | +0 ¢ / +0.1 dB | +0 ¢ / −0.1 dB |
| harm_G3 | +12 | 392.0 | 391.8 | 0.38 | −2 ¢ / +38.1 dB | −1 ¢ / +6.7 dB | +0 ¢ / +3.6 dB |
| harm_A4 | −12 | 220.0 | 219.9 | 0.67 | −0 ¢ / +9.1 dB | −1 ¢ / +16.4 dB | +0 ¢ / +8.8 dB |
| harm_A4 | +0 | 440.0 | 439.9 | 0.67 | +0 ¢ / +9.5 dB | −2 ¢ / +18.6 dB | +0 ¢ / +9.2 dB |
| harm_A4 | +12 | 880.0 | 91.0 | 0.25 | +2 ¢ / +46.8 dB | +2 ¢ / +41.2 dB | +1 ¢ / +18.6 dB |
| harm_A5 | −12 | 440.0 | 297.1 | 0.35 | +1209 ¢ / +39.5 dB | +1199 ¢ / +47.6 dB | +1201 ¢ / +21.0 dB |
| harm_A5 | +0 | 880.0 | 91.3 | 0.39 | −0 ¢ / +44.8 dB | −1 ¢ / +47.1 dB | +1 ¢ / +14.8 dB |
| harm_A5 | +12 | 1760.0 | 88.5 | 0.61 | +2 ¢ / +30.3 dB | +2 ¢ / +30.2 dB | +2 ¢ / +26.0 dB |

Near-identity resynthesis (world_hard, shift 0): breathiness 0.99 vs 1.0 (1.0 skips the stage):

| fixture | clean | waveform residual dB | inharm dB at 1.0 | inharm dB at 0.99 |
|---|---|---|---|---|
| harm_G3 | 0 | −4.4 | −41.9 | −41.6 |
| harm_G3 | 75 | −2.1 | −42.0 | −41.7 |
| test_2s_C4 | 0 | −5.7 | −31.9 | −31.4 |
| test_2s_C4 | 75 | −9.2 | −39.7 | −36.5 |

A 1 % change of the setting rewrites the waveform: the residual is −9.2 to −2.1 dB re signal, because the stage re-synthesises everything. The inharmonic ratio moves +0.3 to +3.2 dB, which bounds how much the second pass on its own undoes cleanliness when the f0 is right.

Breathiness 0 → `effective_amount` = 0 → `ap ** (1/0)`:

| fixture | breath | hf_bias | bins with exponent 1/0 | warnings | NaN/inf samples | residual vs breath 0.01 (dB) |
|---|---|---|---|---|---|---|
| harm_G3 | 0.01 | 0.0 | 0 | – | 0 | −∞ |
| harm_G3 | 0.0 | 0.0 | 1025 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | 0 | −64.9 |
| harm_G3 | 0.0 | 1.0 | 816 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | 0 | −60.3 |
| breathy_A3 | 0.01 | 0.0 | 0 | – | 0 | −∞ |
| breathy_A3 | 0.0 | 0.0 | 1025 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | 0 | −33.3 |
| breathy_A3 | 0.0 | 1.0 | 816 | RuntimeWarning: divide by zero encountered in divide @ autotuner.py:95 | 0 | −30.9 |

`ap ** inf` is 0 for every ap < 1, so amount 0 behaves as the limit of small amounts (fully periodic). The division is real but does not corrupt the output.

#### B5 - cache keyed on md5 of the first 1000 samples: **CONFIRMED** (latent: not reachable through the current endpoints)

*Rule: CONFIRMED if B with A's identical leading silence hits A's cache and its output differs from a cold-cache render of B (different length, or residual > −60 dB). Reachability is read from the endpoint source.*

- A = `lead_G3` (1.8 s), B = `lead_A4` (1.5 s), both starting with 300 ms of digital zeros. 4/4 settings hit A's cache and give a different B. For world_* modes B is rendered on A's time axis, so its output is **+300 ms** longer than a cold render. The f0 column shows the pitch damage. Control (B without leading silence): no cache hit, bit-identical to cold.
- Not reachable today: `/api/load-audio` and `/api/load-audio-upload` both reset `state.world_cache` before anything else, and `/api/process` and multisample always reuse the loaded `state.original_audio`. The collision fires only if a future caller runs `_run_pipeline` / `_world_cache_for` on other audio without a load, e.g. batch processing or a trimmed variant.

| B | mode | post | hash equal | cache hit | len warm / cold | residual dB | f0 ¢ warm / cold | fails warm | fails cold | exception |
|---|---|---|---|---|---|---|---|---|---|---|
| lead_A4 | world_hard | cl 0 / br 1 | True | True | 79600 / 66370 | 1.1 | +703 / +0 | length, f0, inharm, tail | tail | – |
| lead_A4 | world_soft | cl 0 / br 1 | True | True | 79600 / 66370 | 3.0 | +703 / +0 | length, f0, inharm, tail | inharm, tail | – |
| lead_A4 | praat_soft | cl 50 / br 0.5 | True | True | 66150 / 66150 | 6.7 | +0 / +701 | inharm, tail | f0, inharm, tail, rms | – |
| lead_A4 | world_hard | cl 100 / br 1 | True | True | 79600 / 66370 | 6.6 | +702 / +703 | length, f0, inharm, tail | f0, tail | – |
| nolead_A4 | world_hard | cl 0 / br 1 | False | False | 53140 / 53140 | −∞ | +0 / +0 | tail | tail | – |
| nolead_A4 | world_soft | cl 0 / br 1 | False | False | 53140 / 53140 | −∞ | +0 / +0 | tail | tail | – |
| nolead_A4 | praat_soft | cl 50 / br 0.5 | False | False | 52920 / 52920 | −∞ | +697 / +697 | f0, inharm, tail, rms | f0, inharm, tail, rms | – |
| nolead_A4 | world_hard | cl 100 / br 1 | False | False | 53140 / 53140 | −∞ | +703 / +703 | f0, tail | f0, tail | – |

| endpoint | resets cache | runs pipeline |
|---|---|---|
| `load_audio` | yes | no |
| `load_audio_upload` | yes | no |
| `process_audio` | no | yes |
| `render_multisample` | no | yes |

### Other findings (outside B1-B5)

#### E1 - cleanliness ISTFT blows up the first samples of the file

`apply_cleanliness` pads n_fft zeros at the end only. Its `scipy.signal.istft(..., boundary=False)` then divides the first samples by a window sum of ~0 (scipy warns *NOLA condition failed* on every call). Whatever the mask did to those first samples gets multiplied by up to ~1/w[n]. Any file whose audio starts within the first STFT frame spikes, and real recordings usually do. Leading silence avoids it. Pre-padding the input (F5) removes it completely.

- The sweep credits E1 with **826 failed metrics in 826 renders** (mostly *peak*).
- Severity grows with cleanliness because a narrower mask changes those edge samples more.

| fixture | clean | NOLA warning | audio starts at ms | peak dBFS (app) | peak at ms | peak after 50 ms | peak dBFS (pre-padded) | input peak |
|---|---|---|---|---|---|---|---|---|
| harm_G3 | 25 | True | 0.02 | +34.9 | 0.07 | −6.2 | −6.1 | −6.0 |
| harm_G3 | 50 | True | 0.02 | +39.0 | 0.07 | −6.4 | −6.4 | −6.0 |
| harm_G3 | 75 | True | 0.02 | +50.0 | 0.07 | −7.0 | −7.0 | −6.0 |
| harm_G3 | 100 | True | 0.02 | +60.6 | 0.09 | −11.8 | −11.8 | −6.0 |
| test_2s_C4 | 25 | True | 0.00 | +45.5 | 0.07 | −2.9 | −2.9 | −2.4 |
| test_2s_C4 | 50 | True | 0.00 | +51.5 | 0.07 | −3.1 | −3.1 | −2.4 |
| test_2s_C4 | 75 | True | 0.00 | +63.4 | 0.07 | −3.9 | −3.9 | −2.4 |
| test_2s_C4 | 100 | True | 0.00 | +76.0 | 0.07 | −11.7 | −11.7 | −2.4 |
| lead_G3 | 25 | True | 300.02 | −6.2 | 349.48 | −6.2 | −6.2 | −6.0 |
| lead_G3 | 50 | True | 300.02 | −6.4 | 349.48 | −6.4 | −6.4 | −6.0 |
| lead_G3 | 75 | True | 300.02 | −7.0 | 334.17 | −7.0 | −7.0 | −6.0 |
| lead_G3 | 100 | True | 300.02 | −14.1 | 323.97 | −14.1 | −14.1 | −6.0 |

In the sweep (cleanliness > 0, all fixtures except `lead_G3`), how often the spike survives to the output. A breathiness pass after cleanliness re-synthesises the audio and mostly hides it. WORLD modes start their output more gently, so the edge samples the mask disturbs are smaller:

| mode | breath | renders | peak failures credited to E1 | median peak dBFS | max peak dBFS |
|---|---|---|---|---|---|
| `world_hard` | 1 | 210 | 0 | −2.3 | +4.2 |
| `world_hard` | ≠ 1 | 840 | 2 | −1.5 | +9.0 |
| `world_soft` | 1 | 220 | 0 | −1.9 | +3.2 |
| `world_soft` | ≠ 1 | 830 | 0 | −1.4 | +8.5 |
| `world_vt` | 1 | 210 | 0 | −2.4 | +2.9 |
| `world_vt` | ≠ 1 | 820 | 2 | −1.3 | +8.5 |
| `world_hnm` | 1 | 210 | 0 | −3.9 | +8.1 |
| `world_hnm` | ≠ 1 | 830 | 1 | −2.1 | +7.8 |
| `praat_soft` | 1 | 210 | 189 | +50.0 | +76.0 |
| `praat_soft` | ≠ 1 | 810 | 22 | −2.5 | +5.9 |
| `sine_spectral` | 1 | 200 | 180 | +50.8 | +84.7 |
| `sine_spectral` | ≠ 1 | 840 | 10 | +1.1 | +8.1 |
| `stft_pitchshift` | 1 | 210 | 189 | +50.8 | +80.9 |
| `stft_pitchshift` | ≠ 1 | 850 | 6 | −1.4 | +8.1 |

#### sine_spectral output is not harmonic at the target (pitch stage, golden included)

Most of sine_spectral's pitch-only renders miss the target note or fail the inharmonic rule (tables below). The committed golden reference has the same defect, so the regression test protects it. Strongest spectral peaks of `tests/golden/test_2s_C4/pipe_mode_sine_spectral__na__F4.wav` (target F4 = 349.2 Hz, harmonics 698.5, 1047.7 Hz…): 158.8 Hz (-16 dB), 165.9 Hz (-14 dB), 177.0 Hz (-14 dB), 203.2 Hz (-15 dB), 695.5 Hz (+0 dB), 1390.9 Hz (-16 dB).

#### Pitch-stage failures (inherited, not post-pitch)

Failures the pitch-only render already has, and the post stages do not make worse beyond the metric's threshold:

| mode | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|
| `world_hard` |  |  | 88 | 295 | 40 | 97 | 493 | 17 |
| `world_soft` |  |  | 77 | 284 | 145 | 167 | 591 | 17 |
| `world_vt` |  |  | 88 | 274 | 141 | 148 | 562 | 4 |
| `world_hnm` |  |  | 342 | 333 | 143 | 473 | 56 |  |
| `praat_soft` |  |  | 66 | 3 | 99 | 332 | 42 |  |
| `sine_spectral` |  |  | 99 | 245 | 809 | 1367 | 592 |  |
| `stft_pitchshift` |  |  | 99 | 102 | 266 | 649 | 394 |  |

#### Pitch-only renders that miss the target note

| mode | renders | fixture shift |
|---|---|---|
| `praat_soft` | 13 | breathy_A3 +0, breathy_A3 +5, harm_A5 -12, harm_C2 +12, harm_C2 +5, harm_C2 -12, harm_C2 -7 |
| `sine_spectral` | 96 | breathy_A3 +0, breathy_A3 +12, breathy_A3 +5, breathy_A3 -12, breathy_A3 -7, harm_A4 +12, harm_A4 +5, harm_A4 -12, harm_A4 -7, harm_A5 +12, harm_A5 +5, harm_A5 -12 … |
| `stft_pitchshift` | 24 | breathy_A3 +0, breathy_A3 +12, breathy_A3 +5, breathy_A3 -12, breathy_A3 -7, harm_A5 +0, harm_A5 +12, harm_A5 +5, harm_A5 -12, harm_A5 -7, harm_C2 +12, vowel_D3 -12 |
| `world_hard` | 5 | breathy_A3 +0, harm_A5 -12, harm_C2 -12 |
| `world_hnm` | 13 | breathy_A3 +12, harm_A5 +0, harm_A5 +12, harm_A5 +5, harm_A5 -12, harm_A5 -7, harm_C2 -12 |
| `world_soft` | 13 | breathy_A3 +0, harm_A5 +0, harm_A5 +12, harm_A5 +5, harm_A5 -12, harm_A5 -7, harm_C2 -12 |
| `world_vt` | 13 | breathy_A3 +0, harm_A5 +0, harm_A5 +12, harm_A5 +5, harm_A5 -12, harm_A5 -7, harm_C2 -12 |

#### Output length vs expected (pitch-only renders, ms)

| mode | stretch | median Δ | min Δ | max Δ |
|---|---|---|---|---|
| `praat_soft` | 1.0 | +0.0 | +0.0 | +0.0 |
| `praat_soft` | 1.5 | −55.7 | −62.4 | −42.2 |
| `sine_spectral` | 1.0 | +0.0 | +0.0 | +0.0 |
| `sine_spectral` | 1.5 | −55.7 | −62.4 | −42.2 |
| `stft_pitchshift` | 1.0 | +0.0 | +0.0 | +0.0 |
| `stft_pitchshift` | 1.5 | −55.7 | −62.4 | −42.2 |
| `world_hard` | 1.0 | +5.0 | +0.0 | +5.0 |
| `world_hard` | 1.5 | −44.1 | −52.9 | −34.7 |
| `world_hnm` | 1.0 | −3.4 | −27.6 | −0.3 |
| `world_hnm` | 1.5 | −55.7 | −88.7 | −55.7 |
| `world_soft` | 1.0 | +5.0 | +0.0 | +5.0 |
| `world_soft` | 1.5 | −44.1 | −52.9 | −34.7 |
| `world_vt` | 1.0 | +5.0 | +0.0 | +5.0 |
| `world_vt` | 1.5 | −44.1 | −52.9 | −34.7 |

#### Load-time pitch detection (feeds the smart low cut)

`get_pitch_summary` (pyin 50-500 Hz) misreads: `harm_A5`: truth A5, detected A4 (440.1 Hz); `breathy_A3`: truth A3, detected F3 (170.4 Hz). Every low-cut cutoff on those fixtures is computed from the wrong f0, independently of B3.


### Top 20 worst combinations

Ranked by **post-pitch severity**: the sum of value / threshold over the failed metrics that are *not* inherited from the pitch-only render. Overall severity (all failed metrics) is shown next to it. Exceptions count 1000 and NaN 500; f0 is capped at 20. Ranking by overall severity would instead surface pitch-mode defects, mostly sine_spectral. Id = fixture | mode | shift | stretch | lowcut | cleanliness | hf_rollback | breathiness | hf_bias. Columns: f0 error (cents), inharmonic ratio vs input (dB), tail (dB re body), body RMS change (dB), peak (dBFS), length Δ (ms).

| # | combination | fails | post sev | all sev | f0 ¢ | inharm Δ | tail | RMS Δ | peak | len Δ | attribution |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `harm_A4|praat_soft|+12|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | 52.5 | 52.5 | −1276 | +44.7 | −24.8 | −9.6 | +64.6 | +0 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 2 | `harm_A5|praat_soft|+5|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | 50.2 | 50.2 | −1197 | +42.9 | −19.1 | −20.7 | +56.8 | +0 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 3 | `vowel_D3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1` | peak, f0, tail | 47.9 | 47.9 | +715 | −7.5 | −25.4 | −7.6 | +73.2 | +0 | peak: E1; f0: B2; tail: multi:B2+lowcut_design |
| 4 | `vowel_D3|praat_soft|+0|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | 47.3 | 47.3 | +380 | −0.7 | −26.7 | −6.5 | +71.8 | +0 | peak: E1; f0: B2; tail: B2 |
| 5 | `vowel_D3|praat_soft|+12|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | 47.2 | 47.2 | +715 | −7.6 | −25.5 | −7.1 | +71.3 | +0 | peak: E1; f0: B2; tail: B2 |
| 6 | `breathy_A3|praat_soft|-12|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | 45.0 | 45.0 | −1194 | +8.6 | −17.1 | −27.7 | +57.9 | +0 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 7 | `harm_A5|praat_soft|-7|x1|lc0|cl75|rb0|br1|hb0` | peak, f0, inharm, tail | 41.1 | 45.8 | +692 | +27.9 | −29.2 | −11.1 | +54.1 | +0 | peak: E1; f0: E2; inharm: inherited; tail: clean_mask_75 |
| 8 | `vowel_D3|stft_pitchshift|+0|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, tail | 40.9 | 40.9 | +380 | −0.6 | −28.9 | −6.5 | +53.4 | +0 | peak: E1; f0: B2; tail: B2 |
| 9 | `harm_A5|sine_spectral|+0|x1|lc0|cl75|rb0|br1|hb0` | peak, f0, inharm, tail | 38.6 | 45.6 | +1179 | +30.1 | −31.1 | −2.8 | +52.9 | +0 | peak: E1; f0: E2; inharm: inherited; tail: inherited |
| 10 | `harm_G3|sine_spectral|+0|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | 35.8 | 35.8 | +97 | +33.8 | −17.7 | −26.3 | +58.3 | +0 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 11 | `harm_G3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1` | peak, f0, inharm, tail | 34.5 | 38.3 | +152 | +22.6 | −22.7 | −20.2 | +62.0 | +0 | peak: E1; f0: E2; inharm: inherited; tail: B2 |
| 12 | `harm_A4|praat_soft|+5|x1|lc0|cl100|rb0|br1|hb0` | peak, f0, inharm, tail | 34.1 | 38.7 | +138 | +27.9 | −21.8 | −17.7 | +63.1 | +0 | peak: E1; f0: E2; inharm: inherited; tail: B2 |
| 13 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br5|hb0` | peak, f0, inharm, tail, rms | 32.0 | 32.0 | +1194 | +40.3 | −21.5 | −7.8 | +0.3 | +0 | peak: B4; f0: B1; inharm: breath_intended; tail: B1; rms: B1/B4 |
| 14 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br0.5|hb0` | peak, f0, inharm, tail, rms | 31.9 | 31.9 | +1196 | +38.1 | −21.9 | −7.8 | +1.2 | +0 | peak: breath_resynth; f0: B1; inharm: B1/B4; tail: B1/B4; rms: B1/B4 |
| 15 | `harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br2|hb0` | peak, f0, inharm, tail, rms | 31.9 | 31.9 | +1196 | +38.4 | −21.7 | −7.8 | +0.9 | +0 | peak: breath_intended; f0: B1; inharm: B1; tail: B1/B4; rms: B1/B4 |
| 16 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br5|hb0` | f0, inharm, tail, rms | 31.8 | 31.8 | +704 | +45.1 | −22.5 | −8.9 | −7.0 | +5 | f0: B1; inharm: breath_intended; tail: B1/B4; rms: B1 |
| 17 | `harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br5|hb0` | f0, inharm, tail, rms | 31.8 | 31.8 | +704 | +45.1 | −22.7 | −9.0 | −7.2 | +5 | f0: B1; inharm: breath_intended; tail: B1/B4; rms: B1 |
| 18 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br2|hb0` | f0, inharm, tail, rms | 31.7 | 31.7 | +704 | +45.1 | −22.5 | −8.9 | −7.7 | +5 | f0: B1; inharm: breath_intended; tail: B1/B4; rms: B1 |
| 19 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br0.5|hb0` | f0, inharm, tail, rms | 31.7 | 31.7 | +704 | +45.1 | −22.5 | −8.9 | −7.8 | +5 | f0: B1; inharm: B1; tail: B1/B4; rms: B1 |
| 20 | `harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br0|hb0` | f0, inharm, tail, rms | 31.7 | 31.7 | +704 | +45.1 | −22.5 | −8.9 | −7.7 | +5 | f0: B1; inharm: B1/B4; tail: B1/B4; rms: B1 |

### Failure counts per parameter

*failing* = renders with at least one failed metric; *post-pitch* = renders with at least one failure not inherited from the pitch-only render; metric columns count failed metrics.

**All renders:** 9791/10428 failing (94 %), 7275 with a post-pitch failure. By metric: length 859, peak 4055, f0 4587, inharm 6664, tail 6307, rms 450. With an exact-length rule instead of ±10 ms, 5832 renders would fail on length.

#### Pairwise set

**mode**

| mode | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `world_hard` | 66 | 59 | 89 % | 39 |  |  | 33 | 10 | 27 | 25 | 42 | 1 |
| `world_soft` | 66 | 59 | 89 % | 37 |  |  | 22 | 17 | 26 | 20 | 41 | 5 |
| `world_vt` | 55 | 53 | 96 % | 37 |  |  | 33 | 10 | 31 | 25 | 35 |  |
| `world_hnm` | 55 | 54 | 98 % | 40 |  |  | 37 | 11 | 19 | 32 | 35 | 8 |
| `praat_soft` | 66 | 65 | 98 % | 52 |  |  | 11 | 18 | 22 | 43 | 40 | 6 |
| `sine_spectral` | 66 | 66 | 100 % | 32 |  |  | 44 | 31 | 50 | 65 | 39 |  |
| `stft_pitchshift` | 88 | 88 | 100 % | 72 |  |  | 44 | 45 | 32 | 69 | 54 | 6 |

**shift**

| shift | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| -12 | 88 | 86 | 98 % | 73 |  |  | 46 | 30 | 66 | 52 | 54 | 2 |
| -7 | 88 | 86 | 98 % | 68 |  |  | 44 | 18 | 54 | 57 | 56 | 12 |
| 0 | 110 | 102 | 93 % | 53 |  |  | 46 | 28 | 25 | 49 | 66 |  |
| 5 | 77 | 75 | 97 % | 53 |  |  | 44 | 26 | 37 | 46 | 49 | 8 |
| 12 | 99 | 95 | 96 % | 62 |  |  | 44 | 40 | 25 | 75 | 61 | 4 |

**stretch**

| stretch | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 242 | 224 | 93 % | 168 |  |  | 4 | 72 | 110 | 145 | 146 | 14 |
| 1.5 | 220 | 220 | 100 % | 141 |  |  | 220 | 70 | 97 | 134 | 140 | 12 |

**lowcut**

| lowcut | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 165 | 164 | 99 % | 124 |  |  | 99 | 57 | 75 | 110 | 101 | 10 |
| 50 | 121 | 118 | 98 % | 78 |  |  | 57 | 49 | 51 | 70 | 76 | 5 |
| 100 | 176 | 162 | 92 % | 107 |  |  | 68 | 36 | 81 | 99 | 109 | 11 |

**clean**

| clean | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 99 | 94 | 95 % | 54 |  |  | 44 | 33 | 27 | 67 | 57 |  |
| 25 | 99 | 94 | 95 % | 52 |  |  | 55 | 27 | 34 | 49 | 63 | 12 |
| 50 | 99 | 95 | 96 % | 64 |  |  | 66 | 29 | 34 | 58 | 61 | 14 |
| 75 | 77 | 74 | 96 % | 57 |  |  | 24 | 23 | 53 | 43 | 49 |  |
| 100 | 88 | 87 | 99 % | 82 |  |  | 35 | 30 | 59 | 62 | 56 |  |

**hfrb**

| hfrb | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 187 | 181 | 97 % | 138 |  |  | 79 | 63 | 76 | 121 | 118 | 15 |
| 50 | 275 | 263 | 96 % | 171 |  |  | 145 | 79 | 131 | 158 | 168 | 11 |

**breath**

| breath | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 99 | 93 | 94 % | 68 |  |  | 44 | 29 | 40 | 52 | 63 | 13 |
| 0.5 | 77 | 72 | 94 % | 49 |  |  | 35 | 21 | 34 | 34 | 48 | 4 |
| 1 | 88 | 83 | 94 % | 37 |  |  | 44 | 24 | 30 | 36 | 52 | 4 |
| 2 | 99 | 98 | 99 % | 80 |  |  | 66 | 44 | 54 | 78 | 62 | 3 |
| 5 | 99 | 98 | 99 % | 75 |  |  | 35 | 24 | 49 | 79 | 61 | 2 |

**hfbias**

| hfbias | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 242 | 232 | 96 % | 168 |  |  | 121 | 87 | 115 | 167 | 150 | 10 |
| 1 | 220 | 212 | 96 % | 141 |  |  | 103 | 55 | 92 | 112 | 136 | 16 |


#### Grid set

**mode**

| mode | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `world_hard` | 1375 | 1233 | 90 % | 949 |  |  |  | 434 | 452 | 685 | 852 | 74 |
| `world_soft` | 1375 | 1261 | 92 % | 919 |  |  |  | 520 | 532 | 702 | 854 | 73 |
| `world_vt` | 1375 | 1259 | 92 % | 936 |  |  |  | 519 | 545 | 701 | 853 | 60 |
| `world_hnm` | 1375 | 1293 | 94 % | 1077 |  |  | 250 | 510 | 549 | 879 | 787 | 49 |
| `praat_soft` | 1375 | 1251 | 91 % | 1172 |  |  |  | 507 | 474 | 839 | 769 | 94 |
| `sine_spectral` | 1375 | 1375 | 100 % | 819 |  |  |  | 796 | 1174 | 1328 | 854 | 8 |
| `stft_pitchshift` | 1375 | 1333 | 97 % | 1134 |  |  |  | 643 | 585 | 1114 | 836 | 64 |

**shift**

| shift | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| -12 | 1925 | 1842 | 96 % | 1479 |  |  | 50 | 1094 | 1386 | 1181 | 1160 | 25 |
| -7 | 1925 | 1847 | 96 % | 1459 |  |  | 50 | 775 | 1077 | 1364 | 1173 | 99 |
| 0 | 1925 | 1802 | 94 % | 1340 |  |  | 50 | 760 | 376 | 1013 | 1149 | 3 |
| 5 | 1925 | 1838 | 95 % | 1559 |  |  | 50 | 705 | 970 | 1447 | 1171 | 256 |
| 12 | 1925 | 1676 | 87 % | 1169 |  |  | 50 | 595 | 502 | 1243 | 1152 | 39 |

**clean**

| clean | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1925 | 1778 | 92 % | 1175 |  |  | 50 | 833 | 508 | 1223 | 1123 | 15 |
| 25 | 1925 | 1801 | 94 % | 1337 |  |  | 50 | 821 | 704 | 1197 | 1130 | 128 |
| 50 | 1925 | 1807 | 94 % | 1448 |  |  | 50 | 801 | 817 | 1262 | 1146 | 279 |
| 75 | 1925 | 1817 | 94 % | 1484 |  |  | 50 | 766 | 1111 | 1262 | 1192 |  |
| 100 | 1925 | 1802 | 94 % | 1562 |  |  | 50 | 708 | 1171 | 1304 | 1214 |  |

**breath**

| breath | renders | failing | % | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1925 | 1743 | 91 % | 1348 |  |  | 50 | 757 | 918 | 934 | 1216 | 82 |
| 0.5 | 1925 | 1745 | 91 % | 1336 |  |  | 50 | 742 | 905 | 962 | 1216 | 82 |
| 1 | 1925 | 1709 | 89 % | 941 |  |  | 50 | 940 | 699 | 821 | 939 | 87 |
| 2 | 1925 | 1903 | 99 % | 1621 |  |  | 50 | 738 | 899 | 1641 | 1216 | 82 |
| 5 | 1925 | 1905 | 99 % | 1760 |  |  | 50 | 752 | 890 | 1890 | 1218 | 89 |

#### Per fixture (all sets)

| fixture | renders | failing | post-pitch | exception | nonfinite | length | peak | f0 | inharm | tail | rms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `harm_C2` | 948 | 935 | 723 |  |  | 55 | 121 | 571 | 775 | 877 | 13 |
| `harm_G3` | 948 | 939 | 689 |  |  | 55 | 237 | 325 | 596 | 914 | 29 |
| `harm_A4` | 948 | 947 | 749 |  |  | 55 | 291 | 487 | 766 | 898 | 58 |
| `harm_A5` | 948 | 948 | 792 |  |  | 55 | 821 | 709 | 938 | 874 | 8 |
| `vowel_D3` | 948 | 944 | 732 |  |  | 55 | 82 | 353 | 608 | 912 |  |
| `breathy_A3` | 948 | 939 | 679 |  |  | 55 | 81 | 588 | 478 | 924 | 108 |
| `short_C4` | 948 | 594 | 379 |  |  | 55 | 201 | 108 | 455 |  |  |
| `lead_G3` | 948 | 926 | 638 |  |  | 55 | 44 | 319 | 586 | 908 | 25 |
| `test_2s_C4` | 948 | 868 | 634 |  |  | 55 | 737 | 378 | 497 |  | 72 |
| `test_10s_C4` | 948 | 867 | 638 |  |  | 182 | 740 | 377 | 492 |  | 73 |
| `test_10s_C4_Fs4_tuned` | 948 | 884 | 622 |  |  | 182 | 700 | 372 | 473 |  | 64 |

### Listening: the 10 worst renders

In `tests/sweep/out/worst/`, each next to a `…__pitch_only.wav` of the same fixture, mode, shift and stretch for A/B. Selected by post-pitch severity, at most 3 per pitch mode and 4 per dominant post-pitch metric so the list is not ten copies of one failure. **Samples are clipped to ±1.0** so E1 spikes cannot hurt ears or speakers (the loudest render in the sweep peaks at +84.7 dBFS). The true peak is in the table.

| # | file | fails | dominant | true peak dBFS | attribution |
|---|---|---|---|---|---|
| 1 | `01_harm_A4__praat_soft__p12__x1__lc0__cl100__rb0__br1__hb0.wav` | peak, f0, inharm, tail | peak | +64.6 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 2 | `02_harm_A5__praat_soft__p5__x1__lc0__cl100__rb0__br1__hb0.wav` | peak, f0, inharm, tail | f0 | +56.8 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 3 | `03_vowel_D3__praat_soft__p12__x1__lc50__cl100__rb50__br1__hb1.wav` | peak, f0, tail | peak | +73.2 | peak: E1; f0: B2; tail: multi:B2+lowcut_design |
| 4 | `04_vowel_D3__stft_pitchshift__p0__x1__lc0__cl100__rb0__br1__hb0.wav` | peak, f0, tail | f0 | +53.4 | peak: E1; f0: B2; tail: B2 |
| 5 | `05_harm_A5__sine_spectral__p0__x1__lc0__cl75__rb0__br1__hb0.wav` | peak, f0, inharm, tail | f0 | +52.9 | peak: E1; f0: E2; inharm: inherited; tail: inherited |
| 6 | `06_harm_G3__sine_spectral__p0__x1__lc0__cl100__rb0__br1__hb0.wav` | peak, f0, inharm, tail | peak | +58.3 | peak: E1; f0: E2; inharm: E2; tail: B2 |
| 7 | `07_harm_A4__stft_pitchshift__-12__x1__lc0__cl25__rb0__br5__hb0.wav` | peak, f0, inharm, tail, rms | f0 | +0.3 | peak: B4; f0: B1; inharm: breath_intended; tail: B1; rms: B1/B4 |
| 8 | `08_test_10s_C4__sine_spectral__-12__x1__lc0__cl100__rb0__br1__hb0.wav` | peak, f0, inharm | peak | +84.7 | peak: E1; f0: inherited; inharm: inherited |
| 9 | `09_harm_A4__stft_pitchshift__p12__x1__lc0__cl100__rb0__br5__hb0.wav` | peak, f0, inharm, tail | inharm | +1.8 | peak: B4/E1; f0: B4; inharm: breath_intended; tail: multi:B2+breath_intended |
| 10 | `10_harm_A4__world_hnm__p12__x1__lc0__cl0__rb0__br0.5__hb0.wav` | peak, inharm, tail | inharm | +5.1 | peak: B4; inharm: B4; tail: breath_resynth |

