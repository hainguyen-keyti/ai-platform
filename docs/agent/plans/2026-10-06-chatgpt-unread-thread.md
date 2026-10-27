# Plan: ChatGPT never takes an earlier turn's answer when its thread could not be read

Approved by the owner on 2026-10-07: **"Duyệt, làm ngay (Recommended)"**, offered with "tôi tạm tắt
worker bạn đang chạy trong Terminal 2 lần, mỗi lần vài phút, rồi bật lại trong tab của app Claude".

## 1. Goal

The owner, 2026-10-06 about 20:20: **"Thôi giờ làm tiếp tục đi, cái task khác"**: the next item of
the list the owner approved ("được, tôi duyệt toàn bộ", 2026-10-01), offered twice since 2026-10-02
as "khi không đọc được thread trước lúc gửi, driver có thể trả nhầm câu trả lời của lượt trước".

Measured (2026-10-06, on the fake page of `tests/test_chatgpt_composer.py`, `/tmp/earlier_answer_repro.py`):
a follow-up turn in a thread that already holds an answer, the read of the thread before the send
answering

| that read | what the driver returned |
|---|---|
| 200 | success after 43s, this turn's words ("Here it is.") |
| 429 | **success after 9s, the previous turn's answer ("An earlier answer.")** |
| 500 | **success after 9s, the previous turn's answer** |

Read in the code: `worker/src/providers/chatgpt.py` `_baseline_ids` returns an empty set whenever
that read fails (`data` None, or a status other than 200), so `_settle_via_server` takes every
earlier node of the thread for this turn's, and the earlier answer, finished with `end_turn`, closes
the turn at the first look. The user is charged for it. Found by the picture plan's review on
2026-10-02 (a 429 on that read); a 429 is what ChatGPT answers reads that come too close together
(LESSONS, 2026-09-24), and that read comes right after the previous turn's polling.

Done means: before a follow-up turn is sent, the thread is read until it answers, a few tries with a
pause between; if it still cannot be read, the turn fails before anything is typed or attached, and
is refunded. An earlier turn's answer is never returned as this turn's.

## 2. Non-goals

- The picture rule, the page-watching fallback, the stop button, the 300 second ceiling
- A clock guard for words (the picture rule's `create_time` check): it would hang this turn's words
  on the machine's clock agreeing with the server's
- Grok and Gemini
- ChatGPT's pacing and its 429s in general
- A first turn in a new conversation: it has no thread to read, so nothing changes for it

## 3. Invariants touched and risk tier

- **One job, one turn's answer.** An answer is taken only from the nodes the thread did not hold
  before the send; when those cannot be known, nothing is sent
- **Quota.** A turn that fails before its send is refunded exactly once, by the existing settle
- **Nothing left behind.** A turn that fails before its send leaves no picture attached in the shared
  composer and no prompt typed

### Risk tier

**Tier 2**: one review round by a separate reviewer; after fixes, acceptance with mutants, no
re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py   # N/N PASSED (37 before); the new checks red first on the driver as it stands
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: 44/44, build exit 0, 56/56
```

Mutants on a copy, each red: the empty set back on a failed read; no retry; a retry with no bound;
the read made after the picture is attached; the failure raised after the send.

Real, through the platform, the host worker on the new code: one follow-up ChatGPT turn in a
conversation that already has an answer comes back with its own words (the read answers 200, as
almost always). The failing read cannot be called up on the real site without hammering ChatGPT,
which draws Cloudflare's check; it is proven on the fake page only, and said so.

The host worker the owner runs in a window of Terminal.app has to be stopped twice for this (the
full gate needs the worker in mock mode; the real turn needs it on the new code), a few minutes each
time, and is started again in the desktop app's Terminal panel.

## 5. Blast radius

```
worker/src/providers/chatgpt.py
tests/test_chatgpt_composer.py
# Widened on 2026-10-07 with the owner's "Cho sửa luôn (Recommended)": the full gate's intermittent
# console error, its cause found (T4).
web/src/components/MediaVideo.jsx
tests/ui_smoke.py
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py`: `_thread_nodes` (a 401 drops the token so the next read gets a
  new one), `_baseline_ids`, `_run` (the order: open, memory, upload, snapshots, baseline, send),
  `_stop_unsent`
- `tests/test_chatgpt_composer.py`: `DrawingPage` (`earlier="words"`, `first_read`), `draw_on`, the
  check "an earlier turn's answer is not this turn's"; `page.attached` for an upload
- `/tmp/earlier_answer_repro.py`: the measurement

## Tasks

### T1: Red checks
`DrawingPage` learns that its first few reads can fail. Checks: a follow-up turn whose first read
answers 429, then 500, returns this turn's words, never the earlier answer; a thread that stays
unreadable fails the turn within about 20 seconds, nothing typed and nothing attached (with a
picture to upload); a new conversation still sends without reading.
**Files:** tests/test_chatgpt_composer.py
**Acceptance:** the new checks red on the driver as it stands, the 37 others green

### T2: The driver
The thread is read before anything is attached, up to three times with a growing pause while it
does not answer 200; still unreadable, the turn fails as a provider error saying nothing was sent.
**Files:** worker/src/providers/chatgpt.py
**Acceptance:** `tests/test_chatgpt_composer.py` N/N; `python acceptance.py` 44/44

### T3: Review, mutants, the full gate, one real follow-up turn, Evidence
**Files:** whatever the review names inside the radius
**Acceptance:** section 4

### T4: The video player stops its load before it lets its file go (added 2026-10-07)
The full gate at 8496c15 was 55/56: "no console errors" caught `Failed to load resource:
net::ERR_FILE_NOT_FOUND` on a blob address, now named by its step: after "08d-unserved", where the
test opens the gallery and goes back to the chat at once. Reproduced 3 of 3 (`/tmp/blob_sync.py`): a
video element given a blob address, taken off the page and its blob revoked in one step logs that
error; stopping its load first (`removeAttribute('src')`, then `load()`) logs nothing, 3 of 3.
`MediaVideo` revokes its blob when it unmounts, while its player may not have started to load. A
UI check that mounts a video and leaves it at once, red first; then the player released before
the revoke.
**Files:** tests/ui_smoke.py, web/src/components/MediaVideo.jsx
**Acceptance:** the check red on the web as it stands; then the full gate once, 56/56 (and the
check's own count)

## Evidence

Closed 2026-10-07 at **508c748**, clean tree, five commits from c691726, the audit clean (the radius
widened once, with the owner's yes, the base kept). Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_chatgpt_composer.py` | **49/49 PASSED** at 508c748. Red first: 38/41 at c098b1f (the earlier answer returned after 9s on a first read of 429 and of 500; an unreadable thread sent anyway with its picture attached); then the review's checks 44/49 before 8496c15 |
| **Full gate, once on the final tree, at 508c748, the host worker in mock** | `python acceptance.py` **44/44** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **57/57** exit 0, "no console errors" []; tree unchanged after |
| The full gate at 8496c15 (01:19 to 01:26) | **red**: 44/44, build exit 0, ui_smoke **55/56**, "no console errors": `ERR_FILE_NOT_FOUND` on a blob "after 08d-unserved", which named the step and led to T4 |
| `tests/ui_smoke.py`, T4's check | red first **55/57** (the new check and "no console errors", `ERR_FILE_NOT_FOUND` "after 08-gallery"); the cause reproduced 3 of 3 with a bare video element (`/tmp/blob_sync.py`), and the app's own sequence 3 of 3 on the live web (`/tmp/leave_check.py`), each clean after the fix |
| Mutants, each on a copy (`/tmp/run_unread_mutants.py`, `/tmp/run_unread_review_mutants.py`) | **16 of 16 red** on the final code: the empty set back, no retry, an endless retry, the read after the picture is attached, a 429 taken for an empty thread, no stop check between tries (red once its check had a time bound: it stopped after 18s, not 6s), no pause, no doubling, an empty set with no token, the picture clock guard removed, a wait before every read, the pause at 2s, a 200 with no node taken, no stop check before the refusal, the missing picture checked after the read, no check that the page is still on its thread |
| **Real, one follow-up ChatGPT turn through the web (2026-10-07 01:54)** | **NOT PASSED: Cloudflare's check.** The first ChatGPT turn after the worker started on 8496c15 (01:53) met "cloudflare_challenge" (job 9d4c6765, `provider_error` after 61s, refunded). By the rule, the check is never passed by the agent: ChatGPT was taken off the host worker and the owner told |
| **Real, the same follow-up, run again at 11:30 with the owner's yes ("Cho tôi thử 1 lượt"), the host worker on 508c748** | **PASSED: done in 68s, "Thủ đô của Đức là Berlin."**, this turn's own words in the conversation that had answered "Thủ đô của Pháp là Paris." (job aaaa5c96, settled by the server, memory off); Cloudflare's check had lifted, ChatGPT is back on the host worker |

Review, tier 2: nothing blocking; seven points, all fixed in 8496c15, red first: a page that left
its thread before the send (older than this plan, its window widened by the pauses) is now refused;
the picture clock guard's own check restored with a late earlier picture; the pauses pinned (6s and
12s, as long as the polling after the send waits on a 429); no token and a 200 with no node are no
read; a stop during the last read is unsent; a missing picture is said before the read.

Deviations:
- **The radius was widened** (DECISIONS 2026-10-07) to `web/src/components/MediaVideo.jsx` and
  `tests/ui_smoke.py`: the full gate's intermittent console error, which the Gemini video plan had
  left open with its cause unproven, came back at 8496c15, now named by its step, and was found:
  `MediaVideo` revoked its blob while its just-removed player had yet to read it
- The real follow-up turn met Cloudflare's check at 01:54 and passed at 11:30 when run again with the
  owner's yes; the failing read itself is proven on the fake page only, as the plan said

Left open:
- Nodes an earlier turn still writes after the read before the send (one that hit the 300s ceiling,
  or a stop that did not press) can still be taken for this turn's (the plan's non-goal)
- `python acceptance.py` runs the mock provider and never loads `chatgpt.py`: its 44/44 says nothing
  about this change (the review's note)
