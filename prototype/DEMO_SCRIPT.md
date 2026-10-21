# Demo video script (about 3 minutes)

Record with Windows Game Bar (Win + G, then the record button) or OBS. Browser zoom 110%. Close other tabs and apps first.
Every number on screen comes from a recorded run or saved evidence. Say "mock model, one laptop" once, early. If you record a fresh run, the exact numbers can differ slightly: read them off the screen instead of from this script.

## Before you record (5 minutes)
```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
.venv\Scripts\python.exe -m dashboard.duel_run                        # optional: fresh recording, about 1 minute
.venv\Scripts\python.exe -m uvicorn dashboard.app:app --port 8095     # leave this window open
```
Open `http://127.0.0.1:8095/duel`. If the page says NOT RUN, run the `duel_run` line first.

## Shots (narration in simple English; say it in your own words)
**0:00-0:20 | Problem (face or title)**
"Red tries to break an AI, Blue defends it, and both run in one shared sandbox. The hard part is that Red must not learn Blue's secret rule, not even from small side signals like how long a reply takes."

**0:20-1:30 | Same attack, two outcomes (`/duel`, press Play, speed 1x, then use Step)**
- Point at the LEFT panel: "Without defense, the gateway answers as soon as it is ready. Blocked requests come back in about 0.05 seconds, allowed ones in 0.27. Red can read Blue's rule from a stopwatch." (Show the bars and the line "Blocked median 0.05 s vs allowed 0.27 s".)
- Point at the RIGHT panel: "With our solution every reply comes at one fixed time, about 0.93 seconds, always the same shape: HTTP 202, pending, 64 bytes." (Show the equal bars and "gap 1 ms".)
- Step through one blocked probe: "Blue blocked this, but Red only sees pending."
- Probe 13: "A long request is not cancelled. It finishes later, in the background."
- Point at the meter: "Red only gets a coarse hint, LOW, STABLE or IMPROVING, only after a batch of ten."
- Point at the accuracy box: "How well can an attacker tell rule A from rule B? Without defense about 98 to 100 percent. With our solution about 50 percent, which is guessing."

**1:30-2:05 | Walls and audit (press Presenter mode, then Next to screen 2)**
"Red cannot reach Blue, the model, the audit service or the internet: 11 of 11 checks pass. And if anyone edits the audit log, 7 of 7 tampered copies are detected."
(Optional live proof if Docker is running: `docker compose exec -T red-client python demo_isolation.py ...` and `docker compose run --rm --entrypoint python verifier demo_audit_tamper.py --run-id <id>`; see README.)

**2:05-2:30 | Measured, not claimed (Next to screen 3, the chart)**
"Each bar is Red's accuracy over 200 unseen runs. The dashed line is guessing. The hatched bars were not run, and we show them as not run."

**2:30-3:00 | Honest limits (Next to screen 4)**
"This is a mock model on one laptop. Under a worst-case flood the old default still leaks (76 percent); our recommended profile gave 47 percent in one run. CPU load, repeated queries that average the noisy report, and the hosted model's cache are not solved. We also ran a real DeepSeek model: 60 requests, fixed timing, no rule in 36 outputs. We say what is protected, what failed, and where the guarantee breaks."

## Do not say
"secure", "zero leakage", "formally private", "proves". Say "the tested attacker could not reliably distinguish".

## If something goes wrong
- Page empty or NOT RUN: run `python -m dashboard.duel_run`, reload.
- Port busy: use `--port 8096` and open that port.
- Speed up the player with the 2x speed control; you can cut the video to 3 minutes afterwards.
