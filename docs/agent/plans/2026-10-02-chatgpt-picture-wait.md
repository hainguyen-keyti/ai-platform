# Plan: the ChatGPT driver sees a picture turn end

Revised on 2026-10-02 at 18:15 with the owner's approval ("Đổi hướng, sửa gốc"). The first version
raised the driver's ceiling from 300 to 480 seconds on a wrong premise; T1 and T2 below are what it
did, T3 takes the ceiling back, T4 is the fix.

## 1. Goal

The owner, 2026-10-02, to the agent's offer of "a small plan for a ChatGPT picture turn to wait
longer than 300 seconds" beside the stop probe: **"làm cả 2 đi"**. Then, told that the diagnosis was
wrong (the picture is done after 22 seconds and the driver does not see it), to "Cho tôi đổi hướng
plan sang sửa đúng gốc chứ?": **"Đổi hướng, sửa gốc (Recommended)"**.

Measured:
- The real ChatGPT gate at b589041, 2026-10-02 04:37 (the run's own record): job 7a128c65, the
  chat turn "vẽ cho tôi một hình vuông màu xanh", failed as `provider_timeout`, "chatgpt returned
  nothing after 302s"; the picture was made all the same (the next turn zipped it)
- Every real picture since 2026-09-29 took the ceiling and a little more: 312, 316, 317, 335
  seconds at 300; **492 seconds at 480** (one turn through the platform at 522f3ed, 17:52)
- **One real picture turn watched every 5 seconds (`/tmp/picture_settle_probe.py`, 18:02, thread
  6abf8f36): the picture is on the page and the stop button gone 22 seconds after the send. The
  server's nodes for the turn are "assistant/code/finished_successfully/end=False" and
  "tool/multimodal_text/finished_successfully/end=None", and stay so for the 420 seconds watched:
  no assistant node with `end_turn` ever comes**

Read in the code: `worker/src/providers/chatgpt.py` `_settle_via_server` calls a turn over only
when the newest assistant node is finished with `end_turn`. A picture turn never has one, so the
wait runs to the ceiling and only then collects the picture from the page. Pictures do not take
five minutes; the driver does not see them end.

Done means: a picture turn is over, for the driver, once the server's newest node of the turn is
a finished tool node holding a picture (`multimodal_text`) and has stayed the newest for 10
seconds with the stop button gone; its picture is collected then, about half a minute after the
send. A turn that draws and then writes is not cut at the picture; a tool node that is not a
picture ends nothing; a turn that never ends still gives up at the ceiling, which is 300 seconds
again; the gate's and the journey's waits are back at 420 and 480 seconds.

## 2. Non-goals

- Grok and Gemini
- Why the lost picture of 04:46 was not on the page at 300 seconds (not on record); collecting a
  picture when it appears makes that moment moot
- The page-watching fallback, which already settles on a picture that holds still
- The stop-button economy in `_settle_via_server`, the api's lease, the web's waiting hint
- A turn that makes several pictures (not measured)

## 3. Invariants touched and risk tier

- **One job, one turn's answer.** A turn is called over only on the server's own record of that
  turn (a node new since the send): a finished picture as its newest node, quiet for 10 seconds,
  or an assistant node with `end_turn` as before. Never on a picture from an earlier turn
- **Quota.** A turn that produced nothing still fails and refunds, exactly once

### Risk tier

**Tier 2**: one review round by a separate reviewer; after fixes, acceptance with mutants, no
re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py   # N/N PASSED; the new checks red first on the driver as it stands
python acceptance.py                                           # 43/43 PASSED, unchanged
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: 43/43, build exit 0, 53/53
```

Mutants on a copy, each red: the picture rule taken out; a picture called over at first sight (no
quiet time); the stop button ignored during the quiet time; any finished tool node taken for a
picture; the ceiling left at 480.

Real, on the account, the host worker on the new code: one picture asked for in a chat turn
through the platform is done with its picture in under 90 seconds (it took 492 at 522f3ed).

## 5. Blast radius

```
worker/src/providers/chatgpt.py
tests/test_chatgpt_composer.py
acceptance.py
tests/ui_journey.py
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py` `_settle_via_server`, `_await_result`, `_run`
- `tests/test_chatgpt_composer.py`: the fake page, `DrawingPage`, whole turns through `_run`
- `/tmp/picture_settle_probe.py`: the measurement

## Tasks

### T1: Red checks for a longer wait (done, be482f0; superseded)
A picture that arrives 345 seconds after its send, a turn that never ends at 480 seconds.

### T2: The ceiling at 480 (done, 0994038 and 522f3ed; superseded)
`REPLY_TIMEOUT = 480`, the gate's wait 600, the journey's 660, the relation pinned.

### T3: Red checks for the real shape, the ceiling back
The fake's picture turn is the measured one: the picture at 22 seconds, the stop button gone, the
server's nodes an assistant code node without `end_turn` and a finished tool node of
`multimodal_text`, for good. Checks: such a turn is collected within a minute; a turn that draws
and then writes returns its words and its picture; a finished tool node that is not a picture
ends nothing; a turn that never ends gives up between 300 and 320 seconds; the checks for a
345-second picture go. `REPLY_TIMEOUT` back to 300, the gate's wait to 420, the journey's to 480.
**Files:** tests/test_chatgpt_composer.py, worker/src/providers/chatgpt.py, acceptance.py, tests/ui_journey.py
**Acceptance:** the picture check red on the driver (collected only at the ceiling), the others green

### T4: The driver sees the picture turn end
`_settle_via_server`: the turn is over once its newest node is a finished tool node of
`multimodal_text` that has stayed the newest for `PICTURE_QUIET_SECONDS` (10) with no stop button.
**Files:** worker/src/providers/chatgpt.py
**Acceptance:** `tests/test_chatgpt_composer.py` N/N; `python acceptance.py` 43/43

### T5: Review, mutants, the full gate, one real picture turn, Evidence
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-10-02 at **d2d346d**, clean tree, eight commits (the first three are the first approach,
taken back in the fourth), the audit clean. Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_chatgpt_composer.py` | **37/37 PASSED**. Red first for the fix: 29/30 at 7912613, the measured picture turn "collected after 303s" where a minute is owed; and 34/36 before c36bb11 for the review's two fixes |
| Full gate, once, at d2d346d, clean tree, the host worker in mock (19:16 to 19:23) | `python acceptance.py` **43/43 PASSED** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **53/53 PASSED** exit 0; tree unchanged after |
| Mutants (`/tmp/run_picture_wait_mutants.py`, each on a copy of HEAD) | **15 of 15 red** at d2d346d: the plan's five, five more of the agent's, the reviewer's three survivors and two for the review's fixes |
| **Real, one picture asked for in a chat turn through the platform, the host worker on the new code** | at d2d346d, 19:23: **done in 44s with its picture**; at efe5a20, 19:06: done in 63s with its picture. Before: 492s at 522f3ed (the ceiling at 480), and 312 to 335s in every real run since 2026-09-29 (the ceiling at 300) |
| A plain turn after it, the same way (19:24) | done in 22s, "Tokyo" |

The measurement the fix rests on (`/tmp/picture_settle_probe.py`, 2026-10-02 18:02, one real
picture turn, nothing pressed, thread 6abf8f36 kept): the picture on the page and the stop button
gone 22 seconds after the send; the server's nodes "assistant/code/finished_successfully/end=False"
and "tool/multimodal_text/finished_successfully/end=None", unchanged for the 420 seconds watched.

Review, tier 2:
- The first approach (the ceiling at 480) had its own round: nothing blocking. It could not
  see that the premise was wrong; the real turn that took 492 seconds did
- **The round on the picture rule (b589041..efe5a20): nothing blocking, 7 non-blocking, 4 of its 6
  mutants through.** Fixed in c36bb11 and d2d346d, red first: a picture's node must be this
  turn's own by the server's clock (5 seconds of slack), so an earlier turn's picture cannot end
  a turn whose thread could not be read before the send (that failed as "returned nothing after
  20s"); a picture whose node is there before the page has painted it is waited for, up to 30
  seconds (it failed after 37s); checks for the turn's newest node and for the filter of earlier
  nodes; the stop button's comment says what now leans on it

Left open, said by the review and not changed (HANDOFF, Parked questions):
- A caption that comes more than about 10 seconds after the picture, with no stop button and no
  server node meanwhile, is returned without its words. Not seen on the real site: the measured
  turn has no caption at all
- A picture node without a `create_time`, or one tied with its code node and listed first, misses
  the rule: the turn runs to the ceiling and still collects its picture, as before this plan
- The quiet time is 12 to 16 seconds in practice (the server is read every 3 seconds)
- **Older than this plan, and wider: when the read of the thread before the send fails,
  `_baseline_ids` returns nothing, and every earlier node of the thread counts as this turn's.**
  The picture rule is guarded by the clock now; the old rule for words is not (an earlier answer
  with `end_turn` could be returned at once). A plan of its own
- Why the picture of 04:46 was not on the page at 300 seconds is still not on record

Deviations: the plan was revised once, with the owner's approval, when its premise proved wrong
(the marker removed, the plan rewritten, the marker restored with the same base). The first
approach's three commits stay in the history; `acceptance.py` and `tests/ui_journey.py` end as
they began.

Real ChatGPT turns spent by this plan: four pictures (17:52, 18:02, 19:06, 19:23) and one plain
turn, each in a conversation that is kept (`docs/agent/residue-left-in-accounts.md`).
