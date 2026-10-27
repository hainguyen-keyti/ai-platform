# Plan: the chat view keeps following the tail

## 1. Goal

The owner, 2026-09-29, after the recommendation to take the parked "view follows new messages"
next: **"ok, làm tiếp đi"**, then **"Cả ba trường hợp"** and **"Tier 3 với 5 mutant"**.

Measured 2026-09-29 before any change (`/tmp/scroll_race_trace.py`: a 20 message conversation at
1280x900, the list, the conversation, `POST /chat`, the job and the picture all answered in the
browser, nothing sent to a provider):

- the parked flake: with the page's smooth scroll slowed to 4s (as on a busy or slow device), a
  long message then a long reply end **384px** from the bottom, every run. The trace shows a frame
  of the page's own smooth scroll, moving down 433px from the bottom, clearing `stickToBottom` in
  `trackScroll` (`web/src/pages/Chat.jsx`), after which the reply triggers no `scrollTo`. The native
  smooth scroll on an idle machine: 0px (it finishes in about 170ms, before the reply)
- a reply carrying a picture ends **238px** from the bottom, every run, native or slow:
  `MediaImage` shows a 0px placeholder until its file loads, and nothing scrolls when the picture's
  height arrives
- the chat area 300px shorter while at the bottom (a phone keyboard): **300px** from the bottom

A prototype on a copy of `web/` (`/tmp/scroll_fix_prototype.py`: only a scroll moving up leaves the
tail; a `ResizeObserver` on the thread and on the scroll area follows while stuck) measured 0px in
all three cases and in the native one.

Done means: while the view follows the tail, it ends at the bottom after a new message, a reply, a
picture arriving or the area getting shorter, however slow the smooth scroll; a person who
scrolled up to read is left where they are.

## 2. Non-goals

- The 80px threshold, the smooth scroll itself, a "jump to latest" button
- `MediaImage` or any other component; reserving a picture's space before it loads
- The api and the worker
- Anything parked (the phone's Back button, the reply's blank lines, contrast, the gallery's file
  card)

## 3. Invariants touched and risk tier

None: the scroll position of one element; no job, quota, conversation or provider path changes.
The existing 40 ui checks must stay green, "reading history is not interrupted" above all.

### Risk tier

**Tier 3**, the owner's choice on 2026-09-29: no separate review; acceptance with five mutants.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/ui_smoke.py   # 43/43 PASSED (40 + 3 new), the three new checks RED first
(cd web && npm run build)                         # ok
python acceptance.py                              # 36/36 PASSED, unchanged
```

The three new checks run in a second browser context at 1280x900 with the smoke user's session,
the conversation, the send, the job and the picture answered in the browser (no job is made): a
long message and a long reply landing while the page's smooth scroll is slowed to 4 seconds; a
reply whose picture file arrives a second after it; the window made 300px shorter at the bottom.
Each ends under 80px from the bottom.

Mutants, each red: `trackScroll` as before; no `ResizeObserver`; the observer on the scroll area
only; on the thread only; the observer following while the person has scrolled up ("reading
history is not interrupted").

## 5. Blast radius

```
web/src/pages/Chat.jsx
tests/ui_smoke.py
```

## 6. Reuse pointers

- `/tmp/scroll_race_trace.py`: the reproduction (the answered routes, the 4 second smooth scroll,
  the PNG, the shorter window)
- `/tmp/scroll_fix_prototype.py`: the fix as measured
- `tests/ui_smoke.py`: the phone section's second context with the smoke user's token; the served
  checks' `route.fulfill` with `access-control-allow-origin`
- `web/src/pages/Chat.jsx`: `stickToBottom`, `trackScroll`, the scroll effect

## Tasks

### T1: Red checks
The three checks in `tests/ui_smoke.py`, as in section 4, each red on today's web for its reason.
**Files:** tests/ui_smoke.py
**Acceptance:** `tests/ui_smoke.py` with exactly the three new checks red (the probe measured 384,
238 and 300px)

### T2: The fix
`trackScroll` leaves the tail only on a scroll that moves up away from the bottom; a
`ResizeObserver` on the thread (a wrapper inside the scroll area) and on the area scrolls to the
bottom while stuck.
**Files:** web/src/pages/Chat.jsx
**Acceptance:** `npm run build` ok; `tests/ui_smoke.py` 43/43

### T3: Mutants, gates, Evidence
The five mutants; the full gate once.
**Files:** whatever a surviving mutant shows missing, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-29 at **9d3a60b**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **43/43 PASSED**, exit 0, at 9d3a60b with the host worker in mock (load average about 20) |
| `tests/ui_smoke.py`, the three new checks | red first at **40/43** on ab8e210 (252e98d), exactly the three, with the probe's numbers: 384px from the bottom with the smooth scroll slowed, 238px after the reply's picture arrives, 300px after the area gets 300px shorter; now 0px each, "reading history is not interrupted" still at scrollTop 3 |
| Web mutants (`/tmp/run_tail_mutants.py`: a copy of `web/` on port 5174, the served module proven to carry the mutant, the real ui_smoke) | **5 of 5 red**, each on its own check: `trackScroll` as before (slow smooth scroll, 384px), no observer (238 and 300px), the observer on the area only (238px), on the thread only (300px), following after the person scrolled up ("reading history", scrollTop 201) |
| Desktop, ab8e210 against 9d3a60b (`/tmp/mr/desktop_head3.py`: the reviewer's harness, every visible box in content coordinates at 768, 1024, 1280 and 1440px, five states) | every box identical; the one difference is the gap to the bottom of a conversation holding a picture, **238px -> 0px**: the harness's own data reproduces the picture case and its fix |
| Cause, measured before the fix (`/tmp/scroll_race_trace.py`) | a frame of the page's own smooth scroll, moving down 433px from the bottom, cleared the follow flag, and no `scrollTo` followed the reply; with the native smooth scroll on an idle machine the scroll ended in about 170ms, before the reply, which is why the parked check failed only under load (twice, both times 432px) |

Tier 3, the owner's choice: no separate review. No deviation from the plan. The prototype used for
the measurement (`/tmp/scroll_fix_prototype.py`) is the code committed in 9d3a60b.
