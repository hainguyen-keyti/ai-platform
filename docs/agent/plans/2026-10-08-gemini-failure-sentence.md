# Plan: Gemini's own failure sentence is a failed turn, not an answer

Approved by the owner on 2026-10-08: **"Duyệt, làm ngay (Recommended)"**, offered with "khi chạy
gate, tôi tắt worker vừa bật khoảng vài phút rồi bật lại".

## 1. Goal

The owner, 2026-10-08 about 01:15: **"Tiếp tục làm tiếp đi"**: the next item offered, "đôi khi
Gemini trả về chính câu báo lỗi của nó, kiểu 'I encountered an error...', và nền tảng lại coi đó là
câu trả lời" (HANDOFF, Parked questions: "Gemini's own failure sentence passes for a reply").

The failing run's own record: job b55dcf5d (video_script, 2026-10-01 13:31:34 to 13:32:40), status
`done`, result text "I encountered an error doing what you asked. Could you try again?", charged;
the same request again (job 7ed93e0e) wrote the script.

Measured on 2026-10-08, read-only, in that turn's thread (b706a1f9605f24e7, `/tmp/gemini_error_markup.py`,
`/tmp/gemini_thread_data.py`, `/tmp/parse_hnvqhb.py`), nothing sent:

- On the page, the error answer's markup is the same as an ordinary earlier answer's in the same
  thread, element for element and class for class (only ids differ)
- In the thread data Gemini keeps (the `hNvQHb` read), the error answer has the same fields as an
  ordinary text answer (`[2]`, a language code "en", model "3.8 Flash"); no status or error field

So the only sign is the sentence itself. Done means: a Gemini turn whose whole answer is Gemini's
own failure sentence (no picture, no video) fails as a provider error: refunded, its words never
stored as the answer, its thread handed back so the conversation goes on in it. An answer that only
quotes the sentence among other words passes as before.

## 2. Non-goals

- A refusal Gemini writes in its own words ("Rất tiếc, hiện tại có quá nhiều yêu cầu tạo video...
  Vui lòng thử lại sau.", 2026-10-06): returned as the answer, as the video plan decided and its
  check "an answer that writes words instead of its video returns the words" pins. Measured
  2026-10-08: that turn's markup carries `contains-extensions-response`, as any tool turn does
- Any sentence not seen on the real site: a Vietnamese version of the failure sentence is not
  guessed; it is added when one is seen
- Reading the stream's body; ChatGPT and Grok; the api; the web's error text

## 3. Invariants touched and risk tier

- **Quota.** A turn that produced only Gemini's failure sentence is refunded exactly once, by the
  existing settle of a failed job (`api/src/jobs.py` `record_result`)
- **One job, one turn's answer.** The failure sentence is never stored as an assistant message
- **The conversation keeps its thread.** A failed turn hands its thread back; `record_result` writes
  it to the conversation whatever the status

### Risk tier

**Tier 2**: one review round by a separate reviewer; after fixes, acceptance with mutants, no
re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_gemini_driver.py   # N/N PASSED (136 before); the new checks red first on the driver as it stands
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: 44/44, build exit 0, 57/57
```

Mutants on a copy, each red: the check removed; a match anywhere in the answer instead of the whole
answer; the turn returned as a success; no thread handed back; the whitespace not flattened.

Real, through the platform, the host worker on the new code: one ordinary Gemini chat turn comes
back with its words. Gemini's failure cannot be called up on demand; it is proven on the fake page
only, and said so.

The host worker runs in a tab of the desktop app's Terminal panel opened by the agent; it is stopped
for the full gate (the gate needs it in mock mode), a few minutes, and started again.

## 5. Blast radius

```
worker/src/providers/gemini.py
tests/test_gemini_driver.py
# Widened on 2026-10-08 with the owner's "Cho sửa luôn (Recommended)": the full gate's
# intermittent "the view keeps following when its own smooth scroll is slow", its cause found (T4).
tests/ui_smoke.py
```

## 6. Reuse pointers

- `worker/src/providers/gemini.py`: `_flat` (whitespace flattened), the message constants
  (`SIGNED_OUT`, `BLOCKED`), the end of `_run` (the "neither words nor a picture" failure and
  `landed`)
- `tests/test_gemini_driver.py`: `Page.answer` with `stream_ok`, `provider_on(page, off())`,
  `video_turn(words=...)`, the check "an answer that writes words instead of its video returns the
  words"

## Tasks

### T1: Red checks
Checks: a turn whose answer is the failure sentence fails as a provider error and hands back its
thread; the same with extra spaces and line breaks around it; a video turn whose words after the
note are the failure sentence fails the same way; an answer that quotes the sentence among other
words is returned as words.
**Files:** tests/test_gemini_driver.py
**Acceptance:** the new failing-turn checks red on the driver as it stands, the 136 others green

### T2: The driver
A list of Gemini's failure sentences seen on the real site (one so far); a turn with no media whose
flattened answer is one of them fails as `provider_error`, saying Gemini answered with its own
failure sentence, with its thread.
**Files:** worker/src/providers/gemini.py
**Acceptance:** `tests/test_gemini_driver.py` N/N; `python acceptance.py` 44/44

### T3: Review, mutants, the full gate, one real Gemini turn, Evidence
**Files:** whatever the review names inside the radius
**Acceptance:** section 4

### T4: The test's slowed smooth scroll never moves back (added 2026-10-08)
The full gate at 7fcf154 was 56/57: "the view keeps following when its own smooth scroll is slow",
384px from the bottom. The check alone (`/tmp/tail_slow_repro.py`, `/tmp/tail_slow_trace.py`, the
check's own code sliced from `tests/ui_smoke.py`) failed about 1 run in 7, always 384px. Traced: in
every failing run a frame of `SLOW_SMOOTH` ran stamped 4.6 to 5.3ms before the call that started it,
so its `t` was below 0 and it set the scroll back by about half a pixel (648 to 647); the app's
`trackScroll` read that as a person scrolling up and let go of the tail. Not Chrome's scroll
anchoring (still failing with `overflow-anchor: none`). With `t` held at 0 or above: 30 of 30
green. A real smooth scroll never moves back; the emulation did.
**Files:** tests/ui_smoke.py
**Acceptance:** the slow check alone 30 of 30 green on the fixed emulation (it failed about 1 in 7
before); still red on a copy of the web whose `trackScroll` is the one from before 9d3a60b; then the
full gate once, 57/57

## Evidence

Closed 2026-10-08 at **63ec5dd**, clean tree, four commits from 508c748, the audit clean (the radius
widened once, with the owner's yes, the base kept). Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_gemini_driver.py` | **143/143 PASSED** at 63ec5dd. Red first: **137/140** at 1fafd18, exactly the three failing-turn checks (the sentence returned as a success, `kind None`); 140/140 at a69c06d |
| **Full gate, once on the final tree, at 63ec5dd, the host worker in mock** | `python acceptance.py` **44/44** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **57/57** exit 0, "no console errors" []; tree unchanged after |
| The full gate at 7fcf154 | **red**: 44/44, build exit 0, ui_smoke **56/57**, "the view keeps following when its own smooth scroll is slow" 384px from the bottom; led to T4 |
| T4, the slow check alone (`/tmp/tail_slow_repro.py`, its code sliced from `tests/ui_smoke.py`) | before: failed 2 of 15, then in the traced runs about 13 of some 94, always 384px; every failing run had a `SLOW_SMOOTH` frame stamped 4.6 to 5.3ms before its call that set the scroll 648 to 647; still failing with `overflow-anchor: none` (2 of 10, verified applied). After the fix: **0 of 30 failed**; on a copy of the web (port 5174, the served module proven to carry it) with `trackScroll` as before 9d3a60b: **10 of 10 red**, 384px |
| Mutants of the driver, each on a copy (`/tmp/run_failure_sentence_mutants.py`) | **8 of 8 red** at 7fcf154: the check removed, a match anywhere, a start match, an end match, a success returned, no thread, no flattening, no media guard |
| **Real, one ordinary Gemini turn through the web (2026-10-08 10:44), the host worker on 7fcf154's driver** | **PASSED: "Thủ đô của Nhật Bản là Tokyo."** in 18s in the web (job a2d37adf, done, 14s in the worker), no error shown, no console error |

Review, tier 2: nothing blocking; four points. Two test gaps (an answer that opens or ends with the
sentence, a picture turn whose words are the sentence) closed in 7fcf154, each red on its mutant.
Section 3 says the sentence is "never stored as an assistant message", while section 1 and the
code let a picture or video turn keep its words, the sentence included (the plan's own "(no
picture, no video)"); left as it is. The cooldown a `provider_error` starts can be called up for
free; parked for the owner (HANDOFF, Parked questions).

Deviations:
- **The radius was widened** (DECISIONS 2026-10-08) to `tests/ui_smoke.py`: the full gate's
  intermittent failure was the test's own slowed smooth scroll moving back half a pixel, not the app
- Gemini's failure itself is proven on the fake page only: it cannot be called up on demand on the
  real site, as the plan said

Left open:
- A Vietnamese (or any other) version of the failure sentence passes as an answer until one is seen
- The cooldown after such a failure (above)
