# Plan: Gemini as the third provider (chat, image, video script)

## 1. Goal

The owner, 2026-09-25, asked for the scope: **"Chat + ảnh + video script"**. On 2026-09-27:
**"Đóng plan, sang /kt:plan Gemini"**. Gemini works on the platform with chat, image and video
script, and a real Gemini gate is green.

Measured 2026-09-25 against the real account, re-measured without a turn on 2026-09-27 (unchanged):
the session lands on `https://gemini.google.com/app` in 7s with no challenge; the composer is a
Quill editor, `rich-textarea .ql-editor[contenteditable="true"]`; Enter sends; a conversation gets
a stable `/app/<16 hex>` that survives a reload; turns ride `POST /_/BardChatUi/data/batchexecute`
(the turn is rpcid `PCck7e`), no websocket; a generated picture arrives as `image/jpeg` from
`lh3.googleusercontent.com/rd-gg-dl/...` and is then shown from a `blob:` url; an upload goes through
`push.clients6.google.com/upload/` then `ProcessFile`; deletion is the row's `delete-button` and a
`mat-dialog-container` confirm; quota is a page (`/usage`, a percentage and a weekly cap); the
interface of this account is Vietnamese. Recorded in docs/agent/HANDOFF.md.

## 2. Non-goals

- Deep Research, Canvas, Gems, Notebook, scheduled actions; Drive as an upload source
- Replaying `batchexecute` over HTTP, or computing the WAA token: the page signs its own calls
- A second Google account or an account pool; turning activity retention off (the page says
  conversations then last 72 hours, which breaks one thread per conversation)
- A shared base class or helper across the three drivers
- Any api or web change; any change to ChatGPT's or Grok's behaviour

## 3. Invariants touched and risk tier

- **Isolation, twice.** One conversation, one thread, one owner, as for the others. And the
  account-level leak: Gemini's personal context was found ON on 2026-09-25 (the page says it
  learns from earlier conversations). The owner decided on 2026-09-27 that the worker reads it
  **before every turn** and refuses while it is on (`provider_misconfigured`, refunded); a reading
  that fails is `unknown` and does not block, the rule already decided for ChatGPT. Health shows
  the reading in the existing `memory` field (`worker/src/pool.py:218` reads it from any provider)
- **One job, one turn.** `insert_text`, a read-back of both ends, never `keyboard.type`
- **An error is never stored as an answer**, and a user's reference picture is never returned as
  a generated one
- **Quota.** Charged once, refunded exactly once
- **Media bytes stay inside the session and are captured during the turn**: reopening the thread
  did not fetch the picture again (measured 2026-09-25)

### Risk tier

**Tier 1**, as for Grok: a third set of account credentials (the owner's own Google account),
an isolation guard, quota, media. A strong reviewer through a risk lens with at least three
separate mutants, then a scoped re-review of the fixed part and the old repro.

## 4. Acceptance evidence

```
python acceptance.py                                        # 34/34 PASSED, unchanged
python acceptance.py --provider gemini                      # mock, gemini-named: every check PASSED (RED today: no worker serves gemini in mock)
python acceptance.py --real --provider gemini               # every check PASSED, skips named with a reason
~/cloakbrowser-env/bin/python tests/gemini_probe.py all     # every probe prints a measurement
~/cloakbrowser-env/bin/python tests/test_gemini_driver.py   # fake-page tests, red first
```

The real gemini gate must not skip: chat, image file, video script (with its upload), thread reused
within a conversation, threads never cross conversations, the provider thread deleted, health shows
personal context `off`. Anything else it skips is named with the reason, as REAL_SKIPS does for
grok. The mock gate never loads the driver (LESSONS 2026-09-25), so the proof is the real gate and
the probe.

## 5. Blast radius

```
worker/src/providers/gemini.py
worker/src/pool.py
acceptance.py
scripts/login_provider.py
tests/gemini_probe.py
tests/test_gemini_driver.py
tests/fixtures/gemini_*
docs/research/*
```

## 6. Reuse pointers

- `worker/src/providers/grok.py`: `_open` with the wait, `_send` with read-back and retry from an
  empty box, settle on the server's word with a DOM gate, `delete_thread`
- `worker/src/providers/chatgpt.py`: the memory guard (`_read_memory`, refuse with
  `provider_misconfigured`), image capture during the turn, the upload step, the honest open error
- `worker/src/pool.py:14` `build_provider`, which raises for gemini today
- `acceptance.py` `REAL_SKIPS` and `wanted()`; `:1127` the mock PROVIDERS list
- `scripts/login_provider.py` grok's `proves_it`
- `/tmp/gemini_probe.py` (open, net, turn, image, imagenet, upload, settings, panel, switch_off,
  recall, list, menu, delete, purge, peek) and `/tmp/gemini-plan-draft.md`, from 2026-09-25/26

## Tasks

### T1: A login that proves itself, the probes, and the open questions
`scripts/login_provider.py` gains a `proves_it` for gemini (it saves on the cookie alone today).
`/tmp/gemini_probe.py` moves to `tests/gemini_probe.py`. Measure and write to
`docs/research/2026-09-27-gemini.md`: whether the `PCck7e` response body carries the whole answer
(the settle rule rests on it); **why the image turn's and the upload turn's threads were gone
minutes later while chat threads persisted** (if they really do not persist, STOP and ask: that
breaks one thread per conversation for those job kinds); whether an rpc reports personal context
(cheaper than the settings page); the error banner's shape; what the page says when the quota is
spent. Each probe-made thread is deleted only with the owner's yes.
**Files:** scripts/login_provider.py, tests/gemini_probe.py, docs/research/*
**Acceptance:** every probe prints a measurement; the two questions have an answer

### T2: Failing checks first
The mock gate serves gemini too (`acceptance.py:1127`), `REAL_SKIPS` gets a gemini entry,
and `tests/test_gemini_driver.py` drives the driver on a fake page (composer found, one Enter per
multi-line prompt, a draft never sent along, personal context on refuses, a user's picture not
returned), with fixtures captured from the real page.
**Files:** acceptance.py, tests/test_gemini_driver.py, tests/fixtures/gemini_*
**Acceptance:** `python acceptance.py --provider gemini` red because no worker serves gemini;
the driver test red because there is no driver

### T3: The driver
`worker/src/providers/gemini.py`: open, send, settle on the measured signal, capture pictures
during the turn, upload a reference picture, keep the thread, delete a thread, read the quota;
`build_provider` returns it.
**Files:** worker/src/providers/gemini.py, worker/src/pool.py
**Acceptance:** T2 green; `python acceptance.py` 34/34

### T4: The personal context guard
Read before every turn (the rpc if T1 found one, otherwise the settings page in a second tab of the
same context); on refuses with `provider_misconfigured` and a refund; unreadable reads `unknown`
and does not block; health shows it in `memory`.
**Files:** worker/src/providers/gemini.py, tests/test_gemini_driver.py
**Acceptance:** the guard cases of the driver test green; the mock gate's memory checks green for
gemini

### T5: Review, tier 1
A strong reviewer through a risk lens, at least three separate mutants (the guard skipped,
`keyboard.type`, the user's picture returned, a banner stored as an answer), then a scoped re-review.
**Files:** whatever the review names, inside the radius
**Acceptance:** 0 blocking findings, every mutant red

### T6: Gates and Evidence
**Files:** none new
**Acceptance:** the numbers in section 4, and the full gate once on a clean tree

## Evidence

Closed 2026-09-27 at **bbeb471**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| `python acceptance.py --real --provider gemini` | **23/23 PASSED, 11 skipped**, exit 0 at 68958de (21/23 at d121414 and again at 5dece25, see below): chat 4 chars, image 14890 bytes, video script 296 chars with its reference picture uploaded, the thread reused (recalled teal-55455), a new conversation did not know it, the provider thread deleted 0 -> 1, the cancelled turn's own thread deleted 1 -> 2 (both tombstones settled on their first attempt, no error), memory off. Every must-not-skip check ran; the 11 skips are named by REAL_SKIPS |
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **34/34 PASSED**, build ok, **25/25 PASSED**, exit 0, at 68958de with the host worker in mock (`MOCK_DELAY_SECONDS=4`); restored to real afterwards |
| `python acceptance.py` at bbeb471 | **34/34 PASSED**, exit 0; bbeb471 changes only `tests/gemini_probe.py`, which no gate uses |
| `python acceptance.py --provider gemini` at bbeb471 | **34/34 PASSED**, exit 0, mock, speaking to gemini |
| `tests/gemini_probe.py all` at bbeb471 | 5 probes ran, 0 crashed, each printed a measurement: 25 sidebar threads, signed in stays on `/personalization-settings` (anonymous goes to `/saved-info`), the switch read `checked: false` in 2.8s, a StreamGenerate failed on purpose left the reply empty and the address `/app`, the list printed 25 rows. Before bbeb471 the list printed none: it read the sidebar before its rows painted |
| `tests/test_gemini_driver.py` | **58/58 PASSED**, 11 of them run the driver's own page scripts in a real browser on a captured thread; red first at every step, last at 53/58 on 5dece25 with the two errors the gate's database had recorded |
| Mutants (`/tmp/run_gemini_mutants.py`, one at a time on a copy) | **44 of 44 red**: the guard skipped, `keyboard.type`, a loose `/rd-gg` match, a 500 stream accepted, a broken-off stream unheard, the last bubble taken, the oldest question taken, words unchecked, marks missing or unread or under another name, the count not required or not passed or required to be exactly one more, text not normalised (page or prompt), answers not required after the question, a picture listed only after its body is read, one exit from the site taken as signed out, a reopened thread with no history accepted, a thread landing on `/app` accepted, sign-in not signed out, the upload's status unchecked or not waited for, pictures not read on arrival, no second fetch or a second fetch of any url, signed out not refused, unknown blocking, `/saved-info` not recognised, a draft never cleared, any lh3 image kept, a one-character read-back, the old `delete_thread`, the row not waited for or waited for without end, the menu clicked only when shown, the row label unchecked, the thread judged at the composer or right after the delete, any page taken as gone, a thread that neither shows nor leaves deleted anyway, a cancel not waiting for its address or waiting without end |

What the real gate found that no fake page had: at d121414, 21/23 with both deletion checks at
`threads deleted 0 -> 0`. Measured without deleting anything, the list paints a row 0.3 to 2.4s
after the composer and a row's menu button only shows under the pointer, which the moving list
defeats; fixed in 5dece25, with a cancelled turn now waiting for its thread's address. The rerun
at 5dece25 was still 21/23, and its kept database named the real errors: `still opens after
delete` for a thread that had in fact been deleted, `has no row to delete from` for a cancelled
turn's thread that Gemini never kept. Timed read-only: a thread that is not there keeps its address
until 0.5 to 0.9s after the composer is ready, then goes back to `/app`; a live one paints its first
turn 1.0 to 1.7s after it. Fixed in 68958de by waiting for either sign.

Review, tier 1: one strong reviewer through a risk lens, then scoped re-reviews of 7978f05,
734fcc5 and 47cd59b. Two blocking findings in the first round (a stream wait that could hang, an
earlier answer returned for a reopened thread), both fixed with cases seen red first; nothing
blocking after. The last re-review's optional point (a page that rebuilds its question elements
loses the marks) is closed in d121414, with "at least one more question" instead of the
reviewer's "exactly one more", because an earlier turn painting late adds one too.

Deviations: narrowing in T3, the guard's methods landed with the driver because the T2 test pins
them, so T4 became the guard's check on the real page. In T6 the gate's findings were fixed inside
the radius (5dece25, 68958de, bbeb471), each seen red first; no radius or acceptance change.

Left open, non-blocking: `delete_thread` skips the row label check when the title is empty; the
guard reads `unknown` if a second switch ever appears; only the first StreamGenerate stream
counts; a quota wall painted as an ordinary reply with a 200 stream would be returned as the answer
(could not be provoked without spending the quota); multi-picture turns are unmeasured; whether a
thread can still open for a moment right after its delete is confirmed (not seen); how soon after
the send the address becomes the thread's (the cancel wait is bounded at 30s);
`tests/gemini_probe.py purge` still opens a row's menu by hovering a visible button, the flow the
real page defeats, so cleanup goes through the driver's `delete_thread`. The threads made by the
probes, the driver runs and the real gates wait in the owner's account for the owner's yes to be
deleted (HANDOFF lists them).

