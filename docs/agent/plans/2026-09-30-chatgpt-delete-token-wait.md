# Plan: ChatGPT's thread deletion waits for the session read

## 1. Goal

The owner, 2026-09-30, after the status report: **"ok làm đi"**, then **"Duyệt"**.

Measured 2026-09-30: the second cleanup batch failed at its first call with "no session token:
the provider session is logged out" (`worker/src/providers/chatgpt.py:829-836`: `delete_thread`
reads `SESSION_TOKEN` right after the home page's domcontentloaded and judges at once). The same
session read a token 1.1s after the page loaded, with no login button and the composer shown
(`/tmp/chatgpt_session_check.py`). `SESSION_TOKEN` answers null whenever the fetch of
`/api/auth/session` or its JSON fails. Of the driver's four token reads only this one comes right
after a load; the others follow a composer wait or an opened page (lines 372, 464, 515).

Done means: `delete_thread` reads the token again every second for up to 20 seconds before it calls
the session logged out; a session with no token at all still raises the same error and sends no
deletion.

## 2. Non-goals

- The other three token reads, the other drivers, the api, the gate

## 3. Invariants touched and risk tier

None: a deletion is sent exactly as before once a token is read; the wait only delays the
logged-out error.

### Risk tier

**Tier 3**, the owner's choice on 2026-09-30: no separate review; acceptance with three mutants.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py   # 19/19 PASSED (17 + 2 new), the late-token check RED first
python acceptance.py                                            # 36/36 PASSED, unchanged
~/cloakbrowser-env/bin/python /tmp/cold_delete_probe.py         # 5 fresh browsers, delete_thread on made-up ids: 0 of 5 logged out
```

The two new checks, on the fake page: a session whose token answers only on the third read still
deletes (red today); a session with no token still raises logged out and sends no deletion. The
real probe runs before the fix (to count how often today's driver misreads) and after; its ids are
made up, so the server answers 404 and the account does not change; ChatGPT is off the host worker
while it runs.

Mutants, each red: no wait (today); a wait that deletes without a token when it runs out; a wait
that gives up after one read.

## 5. Blast radius

```
worker/src/providers/chatgpt.py
tests/test_chatgpt_composer.py
```

## 6. Reuse pointers

- `tests/test_chatgpt_composer.py`: the fake page (`token`, `evaluate`), `provider_on`
- `worker/src/providers/chatgpt.py`: `_composer_ready`'s loop, `delete_thread`
- `/tmp/chatgpt_session_check.py`: the session read on a fresh browser

## Tasks

### T1: Red check and the real before-count
The two checks in `tests/test_chatgpt_composer.py`, the late-token one red today; the real probe run
once on today's driver.
**Files:** tests/test_chatgpt_composer.py
**Acceptance:** `tests/test_chatgpt_composer.py` 18/19, exactly the late-token check red

### T2: The wait
`delete_thread` reads the token again every second for up to 20 seconds.
**Files:** worker/src/providers/chatgpt.py
**Acceptance:** `tests/test_chatgpt_composer.py` 19/19; `python acceptance.py` 36/36

### T3: Mutants, the real after-count, full gate, Evidence
**Files:** none new
**Acceptance:** section 4

## Evidence

Closed 2026-09-30 at **94efd1f**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **45/45 PASSED**, exit 0, at 94efd1f with the host worker in mock |
| `tests/test_chatgpt_composer.py` | red first at **18/19** on 89e8beb (cea5e69): the late-token session called logged out after 1 read; **19/19** now: it deletes after 3 reads; a session with no token still says logged out and sends nothing |
| Mutants on copies (`/tmp/run_token_mutants.py`) | **3 of 3 red**: no wait (18/19), a wait that deletes without a token when it runs out (a deletion sent with no session), a wait that gives up after one read |
| Real probe on today's driver (`/tmp/cold_delete_probe.py`, 5 fresh browsers, made-up ids) | **0 of 5** logged out, each deleted (404) in 5.4 to 6.5s: the race did not reproduce, so the real probe could not go red for the right reason |
| Real probe after the fix | **NOT RUN**: the owner declined the call; the fix rests on the fake page and the mutants, and the recorded failure of the second cleanup batch |

Tier 3: no separate review. Deviation (narrowing): the real probe was meant to count misreads
before and after; it found none before, and the after-count was not run.
