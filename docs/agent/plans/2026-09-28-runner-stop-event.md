# Plan: a runner that has ended still answers /health

## 1. Goal

The owner, 2026-09-28, after the overview named the parked `Runner._stop` defect as the next thing
to fix: **"ok, làm tiếp đi"**, then **"Duyệt"** for this plan.

Reproduced 2026-09-28 on the worker's python (3.10.14, `/tmp/runner_stop_repro.py`): once a runner's
thread has ended, `is_alive()`, `snapshot()` and `join(1)` all raise
`TypeError: 'Event' object is not callable`. `Runner` subclasses `threading.Thread` and keeps its
stop Event in `self._stop` (`worker/src/runner.py:30`), which hides the `_stop()` method the thread
machinery itself calls once the thread is done. `/health` builds `runners` from `r.snapshot()` for
every runner (`worker/src/main.py:66`), so one ended runner takes the whole endpoint down, at the
very moment it should report `alive: false`.

Done means: the Event has a name the thread machinery does not use, and an ended runner answers
`is_alive()` False, `snapshot()["alive"]` False and `join()` without raising; stopping a runner works
as before.

## 2. Non-goals

- Restarting a runner that has ended (a feature, not this fix)
- Any change to health's fields, to how runners are started or stopped (`main.py`), or to the loop
- Any other file

## 3. Invariants touched and risk tier

None: a private attribute is renamed; no job, quota, thread or provider behaviour changes. The stop
signal's meaning (set once, the loop leaves at its next wait) stays exactly as it is.

### Risk tier

**Tier 3**: a small slice. No separate reviewer; acceptance by the coordinator with one mutant.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_runner_health.py       # N/N PASSED; RED first with the TypeError above
~/cloakbrowser-env/bin/python tests/test_runner_tombstones.py   # 3/3 PASSED, unchanged
python acceptance.py                                            # 34/34 PASSED, unchanged
```

Mutant: the Event named `_stop` again, red. Real: the host worker restarted on the fix, `/health`
answers with every runner `alive: true`.

## 5. Blast radius

```
worker/src/runner.py
tests/test_runner_health.py
```

## 6. Reuse pointers

- `tests/test_runner_tombstones.py`: building a `Runner` with a stub pool, no browser, no api
- `/tmp/runner_stop_repro.py`: the reproduction

## Tasks

### T1: The red test
`tests/test_runner_health.py`: a runner whose thread has ended answers `is_alive()` False,
`snapshot()["alive"]` False and `join()`; a running one that is told to stop leaves its loop.
**Files:** tests/test_runner_health.py
**Acceptance:** red on the current runner with `TypeError: 'Event' object is not callable`

### T2: The rename, the gates, the real worker
Rename the Event in `worker/src/runner.py`; run section 4; restart the host worker and read
`/health`.
**Files:** worker/src/runner.py
**Acceptance:** section 4

## Evidence

Closed 2026-09-28 at **26dc5fc**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_runner_health.py` | **4/4 PASSED**; red first at 0/4 on 20f1aad, every case `TypeError: 'Event' object is not callable` (an ended runner's `is_alive()`, `snapshot()`, `join(1)`, and `join(3)` after `stop()`) |
| `tests/test_runner_tombstones.py` | **3/3 PASSED**, unchanged |
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **34/34 PASSED**, build ok, **25/25 PASSED**, exit 0, at 26dc5fc with the host worker in mock |
| Mutant (`/tmp/run_runner_mutant.py`, the Event named `_stop` again on a copy) | **red**, 0/4, the same TypeError |
| Real worker | restarted at 26dc5fc with `PROVIDERS=chatgpt,grok,gemini`: `/health` 200, all three providers ready, all three runners `alive: true` |

Deviation, narrowing: the comment in `tests/test_runner_tombstones.py:73` ("No join(): Runner names
its Event _stop, which shadows Thread._stop") is now out of date; it is outside the radius, so it
was parked rather than edited.
