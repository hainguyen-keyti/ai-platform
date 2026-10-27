# Plan: a busy runner keeps telling the api it is alive

## 1. Goal

The owner, 2026-09-29, after the real runs: **"ok, làm tiếp đi"**, then **"Duyệt"**.

Traced from the third Gemini real gate's own record (2026-09-29, workspace
ai-platform-acceptance-39_t39n6), whose every Gemini turn was done but four checks were red:

- a runner says it is alive only when it claims, when it pauses on purpose (a ping every 5s) and
  through a job's heartbeat (`worker/src/runner.py:57-94`, `126-137`). While it deletes a thread
  (`_delete_one_thread`, `pool.delete_thread`) it says nothing: Gemini's deletion drives the page
  and took 55s (tombstone claimed 14:52:47, deleted 14:53:42), past the gate's 30s served window,
  so the next check's turn was refused with 503 (api.log:1944)
- when a job is cancelled, the next heartbeat hears it is no longer alive and the heartbeat thread
  returns (`runner.py:132-134`), while the driver goes on with the cancelled turn (a progress post
  for job d484189c came after its cancel, api-2.log:25) and the runner claims and pings nothing: the
  quota check's job, queued meanwhile, was failed as no_worker 31s later, and the next check's job
  was refused with 503 instead of being queued (api-2.log:88)
- the gate waits 60s for a thread deletion (`acceptance.py:672`, "measured at 16s on a quiet host")
  and 45s in the cancel check (`acceptance.py:725`); the Gemini deletion took 64s from the delete
  call, so the check read 0 -> 0 while the thread was deleted a moment later

In production the window is 310s (`api/src/config.py:25-39`), so only a deletion or a wind-down
longer than that refuses turns or fails queued jobs; the gap is the same.

Done means: while a runner deletes a thread, and while it finishes a job that was cancelled, it pings
the api for its provider at least every 5 seconds, and stops pinging when that work ends; the gate
gives a thread deletion up to 150 seconds.

## 2. Non-goals

- How fast the Gemini driver notices a cancel (parked)
- The api's served window, its sweep, the job heartbeat's cadence, any driver
- Any other gate check

## 3. Invariants touched and risk tier

The served signal decides whether a queued job is failed as no_worker and refunded, and whether a
turn is refused with 503. This plan only sends that signal more often while the runner is truly
busy; no refund, charge or settlement path changes. A pinger that outlived its work would keep a
dead provider looking served, so each pinger must stop with its work.

### Risk tier

**Tier 2**: the runner serves all three providers. One code review round; acceptance with three
mutants; no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_runner_liveness.py     # 2/2 PASSED, both RED first
~/cloakbrowser-env/bin/python tests/test_runner_tombstones.py   # 3/3 PASSED, unchanged
~/cloakbrowser-env/bin/python tests/test_runner_health.py       # 4/4 PASSED, unchanged
python acceptance.py                                            # 36/36 PASSED, unchanged
python acceptance.py --real --keep --provider gemini            # once after the fix (real turns)
```

The two new checks drive the runner with a fake client and a fake pool, the ping interval made
short: pings keep coming while a thread deletion runs and stop when it ends; after a heartbeat
hears the job is gone, pings keep coming until the driver returns, and stop then. The Gemini real
gate must turn green on the deletion, the cancel-on-delete, the quota refill and the nobody-serves
checks (their red is the recorded third run).

Mutants, each red: no ping during a deletion; the heartbeat returning when the job is gone (today);
a pinger that never stops.

## 5. Blast radius

```
worker/src/runner.py
tests/test_runner_liveness.py
acceptance.py
```

## 6. Reuse pointers

- `tests/test_runner_tombstones.py`: the fake client and pool around a runner
- `worker/src/runner.py`: the hold loop's ping, `_heartbeat`, `_delete_one_thread`
- The kept workspace ai-platform-acceptance-39_t39n6 (db, api.log, api-2.log)

## Tasks

### T1: Red checks
`tests/test_runner_liveness.py` with the two checks of section 4, both red on today's runner.
**Files:** tests/test_runner_liveness.py
**Acceptance:** 0/2, each red for its reason

### T2: The fix
Pings while deleting and after a cancel, stopping with the work; the gate's two deletion waits.
**Files:** worker/src/runner.py, acceptance.py
**Acceptance:** `tests/test_runner_liveness.py` 2/2; the other runner tests unchanged;
`python acceptance.py` 36/36

### T3: Review, mutants, the Gemini real gate, Evidence
One code review round; the three mutants; the full gate once; the Gemini real gate once.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-29 at **34b533c**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **45/45 PASSED**, exit 0, at 34b533c with the host worker in mock |
| `tests/test_runner_liveness.py` | red first at **0/2** on 3e32a12 (487512e): no ping in a 1.5s deletion; told the job was gone, no ping until the driver returned. **3/3** now (one check added by the review round): 7 pings in the deletion and none after, each naming gemini; a deletion that raises still stops the pings (4 during, none after); the driver told to stop 0.01s after the job is gone, 7 pings until it returned, none after |
| `tests/test_runner_tombstones.py`, `tests/test_runner_health.py` | 3/3 and 4/4, unchanged |
| Mutants on copies (`/tmp/run_live_mutants.py`) | **6 of 6 red**: the plan's three (no ping during a deletion, the heartbeat returning when the job is gone, a pinger that never stops) and the review's survivors of the first version (a ping naming no provider, no finally around the deletion, the driver told to stop only after the wind-down) |
| `python acceptance.py --real --keep --provider gemini` (once, host worker on `chatgpt,grok`) | **25/25 PASSED**, 11 skipped, exit 0, at 34b533c, against 20/25 in the recorded third run: the deletion (0 -> 1), the cancel-on-delete, the quota refill (93 -> 100 -> 99) and the nobody-serves checks all green; the refusal check green with "video None" (the previous plan's gate fix, first seen in a real run). Its two deletions took 8s and 7s, so this run did not need the long-deletion pings: those are proven by the tests and mutants; the run shows no false 503 (none in api.log) and one no_worker job, the check's own |

Review, tier 2: nothing blocking; its test holes were closed by adding cases, accepted by its own
mutants going red. Its notes, parked: the gate's deletion checks read the worker's total count, not
the thread they deleted; a heartbeat answered with anything but 200 neither pings nor sets lost; a
stuck driver keeps its provider looking served.

Deviation: the liveness test has 3 checks, not the planned 2, from the review round.
