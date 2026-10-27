# Plan: safety of data and credits after the review of 2026-10-21

Approved by the owner on 2026-10-21: **"Duyệt, làm ngay (Recommended)"**, offered as the first of the
three plans the owner ordered ("Làm cả ba theo thứ tự đó": safety first, then the web, then the
docs and configuration), with "lúc đo ở bước 1, ChatGPT tắt khỏi worker khoảng 10 phút; một ảnh nhỏ
được tải lên kho file của tài khoản ChatGPT dùng chung (không gửi tin nhắn nào); tốn 2 lượt thật ở
cuối (1 Grok, 1 ChatGPT); worker tắt vài phút cho gate, 1 đến 2 lần".

## 1. Goal

The owner, 2026-10-21: **"Hiện tại dự án này làm tới đâu rồi, đã lâu rồi chưa đụng lại cần bạn
review plan và source thật kỹ trước khi tiếp tục làm tiếp"**, then, of the review's ranked list,
**"Làm cả ba theo thứ tự đó"** with the first group "An toàn dữ liệu và lượt": items 1 to 5.

The review (`docs/agent/reviews/2026-10-21-review-worker.md`, `-api.md`; the agent's own
measurements in `2026-10-21-session-and-gate.md`) found, read in the code and measured offline:

1. **A picture attached in ChatGPT's shared composer stays when the turn is taken away after the
   attach.** `worker/src/providers/chatgpt.py` attaches at `page.locator(UPLOAD_INPUT).first.set_input_files`
   (about line 843) between two `_stop_unsent` checks (842, 856); a `JobCancelled` at the second, the
   thread check raising (854) or any exception there leaves the chip; `_clear_composer` (405-411)
   clears text only. The next turn's `_open` loads the thread or the home page with `page.goto`
   (349, 382). Whether chatgpt.com keeps a draft attachment across that load is **not measured**:
   the fake `Attachments` (`tests/test_chatgpt_composer.py:108-119`) never keeps a chip. If it
   survives, the next person's turn sends this person's picture, now a routine path through
   `/v1/images`.
2. **A Grok follow-up returns the earlier turn's answer when the read before the send fails.**
   `worker/src/providers/grok.py` `_baseline_ids` answers an empty set on any status but 200 or a
   body that is not JSON (about 361-371) and `_run` sends anyway (441-445); every earlier response
   then counts as new and the first poll after `START_FLOOR` settles on the previous answer. Measured
   on the reviewer's stub page (`/tmp/rv_worker/grok_baseline_trap.py`, a copy in
   `docs/agent/reviews/2026-10-21-grok-baseline-trap.py`), rerun by the agent: the read answering
   200 runs to the ceiling (the stub never adds the new row); **429 or 500: success after 4 s with
   "The capital of France is Paris.", the earlier answer, sent 1**. The class fixed for ChatGPT on
   2026-10-07 (DECISIONS), unfixed here.
3. **A `done` result with neither words nor media is charged and shows nothing.**
   `api/src/jobs.py` `record_result` writes a message only when `(text or media)` and refunds only
   `failed`; the reviewer posted `{"status":"done","text":"","media":[]}` in-process: job `done`, no
   assistant message, quota 100 to 99. Against DECISIONS 2026-09-23, "a job that produced nothing
   must not cost the user a credit".
4. **A running job whose worker died stays `running`, its credit held, until some worker claims
   again.** `_sweep_stranded` runs only inside `claim_next_job` (`jobs.py` about 312); `get_job`
   sweeps unserved only (about 505-515). The reviewer measured: a claimed job with its lease and
   ping an hour stale read `running` over three polls, quota still 99; one claim from another
   worker then failed it as `no_worker` and refunded.
5. **A dead browser turns a runner into a fast-fail loop.** `_ensure_page` hands back the cached
   page forever (`chatgpt.py` 301-306, `grok.py` 132-137, `gemini.py` 194-199); Playwright's
   `TargetClosedError` is a plain `Error(Exception)` (`playwright/_impl/_errors.py:52`), so
   `pool.execute` maps it to `worker_error` (`worker/src/pool.py` about 184-186), which
   `ProviderHealth.note` neither counts nor cools down (48-55); with `min_gap` 0 the runner claims
   the next job a second later and fails it the same way, every one refunded with
   "TargetClosedError" as the person's error, health still `ready: true`, until the Terminal tab is
   restarted by hand (DECISIONS 2026-10-06).

Done means: a turn taken away after its picture was attached leaves nothing in the shared composer
for the next turn (measured on the real page first, then pinned); a Grok follow-up whose thread
cannot be read before the send is refused unsent and refunded, never answered with an earlier turn;
a `done` with nothing in it is a failed, refunded job; a job whose worker died is failed and
refunded by its owner's next poll, no worker needed; a browser that died costs its provider a
cooldown and is opened again on the next turn, the other providers untouched.

## 2. Non-goals

- Grok and Gemini sending a turn stopped before its send, and their stop button (the review's item
  7, the next worker plan)
- The web's should-fix list (plan 2) and the docs and configuration (plan 3); the first-admin race
  (plan 3)
- Nodes an earlier ChatGPT turn still writes after the read before the send (a plan of its own)
- ChatGPT's text draft, the picture rule, the 300 s ceiling, pacing values, Cloudflare's check
- The zip in memory, the JSON body cap, the upload kept on a failed `/v1` request

## 3. Invariants touched and risk tier

- **Nothing of one user reaches another.** No attachment of a turn taken away rides along with the
  next turn on the shared ChatGPT page
- **One job, one turn's answer.** A Grok answer is taken only from rows the thread did not hold
  before the send; when those cannot be known, nothing is sent
- **Quota.** A job that produced nothing is refunded exactly once: an empty `done`, a job whose
  worker died; nothing is charged twice, nothing refunded twice (the existing rowcount guards)
- **Liveness.** A dead browser costs its provider a cooldown, not the queue; the next turn opens
  the profile again; health reflects it

### Risk tier

**Tier 1** (a shared account's data between users, credits, the worker's liveness): reviewed by a
strong model through a risk lens with at least 3 separate mutants; after fixes, a scoped re-review
of the fixed parts and the old repros.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py   # N/N PASSED (51 before); the attachment checks red first
~/cloakbrowser-env/bin/python tests/test_grok_settle.py        # N/N PASSED (8 before); the read-before-send checks red first
~/cloakbrowser-env/bin/python tests/test_pool_dead_browser.py  # N/N PASSED; red first (a closed target read as worker_error)
python acceptance.py                                            # N/N PASSED (54 before); the empty done and dead worker checks red first
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end
```

Mutants on copies, each red: Grok's empty set back on a failed read; no retry; an endless retry;
the refusal after the send; the empty `done` charged (the refund dropped); the stranded sweep taken
out of `get_job`; the closed-target mapping removed from the pool; the provider's `stop()` not
called; and, if T1 finds the chip survives, the cleanup removed from the cancel path and from the
look before the send.

Real, the host worker on the new code, spaced out: one Grok follow-up turn through the web in a
conversation that already has an answer comes back with its own words (the read answers 200, as
almost always; the failing read is proven on the stub only, and said so); one ChatGPT request
through `/v1/images` with a picture is done with a picture (the attach path intact). T1's record of
the real page (survives or not, the remove control's attributes) is pasted into the Evidence.

The host worker runs in the desktop app's Terminal panel; ChatGPT is taken off it for T1 (about
ten minutes), and it is stopped for the full gate, a few minutes, then started again.

## 5. Blast radius

```
worker/src/providers/chatgpt.py
worker/src/providers/grok.py
worker/src/providers/mock.py
worker/src/pool.py
api/src/jobs.py
acceptance.py
tests/test_chatgpt_composer.py
tests/test_grok_settle.py
tests/test_pool_dead_browser.py
tests/provider_probe.py
docs/agent/reviews/*
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py`: `_baseline_ids` with `BASELINE_TRIES` and
  `BASELINE_PAUSE_SECONDS` (the shape for Grok), `_stop_unsent`, `_clear_composer`, `_run`'s attach
  and cancel paths, `_open`
- `worker/src/providers/grok.py`: `_api`, `_baseline_ids`, `_server_turn`, `_run`, `_check_stop`
- `worker/src/pool.py`: `execute` (the `except` ladder), `ProviderHealth.note`; `playwright._impl._errors.is_target_closed_error`
- `api/src/jobs.py`: `record_result`, `get_job`, `_sweep_stranded`, `_sweep_unserved`, `_refund`
- `tests/test_grok_settle.py`: `StubPage`, `state_for`; the stub of `_open` and `_send` in
  `docs/agent/reviews/2026-10-21-grok-baseline-trap.py`
- `tests/test_chatgpt_composer.py`: `Attachments`, `DrawingPage`, `provider_on`, `follow_up`,
  `page.attached`
- `acceptance.py`: `worker_ctl["stop"]` and `["start"]`, `start_job`, `wait_state`, `quota_now`,
  the mock phrases (`SILENT_PHRASE`), the lease of 2 s and `NO_WORKER_SECONDS` of 20 in the gate's env
- `tests/provider_probe.py`: its subcommands and how they open the ChatGPT profile read-only

## Tasks

### T1: Measure the real composer (ChatGPT off the host worker)
A subcommand `attachment` of `tests/provider_probe.py`: open the profile, the home page, attach a
1 KB PNG through `UPLOAD_INPUT` and wait; record the chip (the elements that show the attachment and
the control that removes it, by tag, `data-testid` and `aria-label`); `page.goto(HOME)` and look
again; open a thread of the probe's own if one exists, else the home page once more, and look
again; if the chip survives, press its remove control and confirm it is gone. No message is sent.
The record goes into `docs/agent/reviews/2026-10-21-attachment-probe.md` and the plan's Evidence.
**Files:** tests/provider_probe.py, docs/agent/reviews/*
**Acceptance:** the probe's own printed record: survives or not, and the remove control's attributes

### T2: Red checks
`tests/test_chatgpt_composer.py`: the fake `Attachments` keeps a chip as T1 measured (across `goto`
or not); a job taken away between the attach and the send leaves nothing attached for the next turn
sent on the same page; if the chip survives on the real page, a leftover chip is removed before any
send. `tests/test_grok_settle.py`: a follow-up whose read before the send answers 429 then 200
returns this turn's words, never the earlier answer; 500 then 200 likewise; a read that stays
unreadable refuses the turn as a provider error within about 20 s with nothing sent; a new
conversation (no thread id) still sends without reading. `tests/test_pool_dead_browser.py`:
`pool.execute` on a provider whose turn raises `TargetClosedError` answers `provider_error` and the
provider's `stop()` has run (its page and context dropped); a plain exception still answers
`worker_error`. `acceptance.py`: "a done result with nothing in it fails and refunds" (a mock
phrase that answers success with no words and no media); "a running job whose worker died is failed
and refunded by its owner's next poll" (a slow job, the worker killed, polls for up to 30 s with no
worker: `failed`, `no_worker`, the credit back; then the worker started again).
**Files:** tests/test_chatgpt_composer.py, tests/test_grok_settle.py, tests/test_pool_dead_browser.py, acceptance.py, worker/src/providers/mock.py
**Acceptance:** each new check red on the code as it stands for its reason, every other check green

### T3: The drivers and the pool
`chatgpt.py`: as T1 says, the chip removed on the cancel and exception paths between the attach and
the send, and a leftover chip removed before any send (or, if nothing survives a load, the check
that nothing is left after `_open`). `grok.py`: `_baseline_ids` retries up to three times with a
growing pause, `_check_stop` between tries, and a thread that stays unreadable raises a provider
error with nothing sent. `pool.py`: an exception that says the target, page, context or browser is
closed runs the provider's `stop()` and answers `provider_error`.
**Files:** worker/src/providers/chatgpt.py, worker/src/providers/grok.py, worker/src/pool.py
**Acceptance:** the three offline suites N/N

### T4: The api
`record_result`: a `done` with neither words nor media is stored as `failed`, `error_kind`
`empty_reply`, refunded in the same transaction under the same rowcount guard. `get_job`: the
stranded sweep runs before the unserved sweep, so the owner's own poll frees a dead worker's job.
**Files:** api/src/jobs.py
**Acceptance:** `python acceptance.py` N/N

### T5: Review, mutants, re-review, the full gate, two real turns, Evidence
**Files:** whatever the review names inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-10-22 at **1a5e7aa**, clean tree, eight commits from 4cd26c8, the audit clean (no
widening). Every number is the command's own count line. Records kept in `docs/agent/reviews/`
(`2026-10-21-attachment-probe.md`, `-run-safety-mutants.py`, `-safety-mutants-*.txt`,
`-real-safety-runs.py`/`.txt`, `grok-look-*.out`, `grok-thread-look-*.out`), since `/tmp` is emptied
after three days.

| Command | Result |
|---|---|
| **Full gate, once on the final tree, at 1a5e7aa, a mock host worker** | `python acceptance.py` **56/56** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **59/59** exit 0; tree unchanged after |
| Offline suites at 1a5e7aa | composer **56/56**, grok settle **17/17**, pool dead browser **6/6**, gemini driver 143/143, grok memory 20/20, tombstones 5/5, runner health 4/4, liveness 4/4, runner tombstones 3/3, login provider 10/10, session profile 12/12, dom signatures 10/10 |
| Red first (4bde6fa) | composer 52/54 (a kept chip sent along; an unremovable one sent), grok settle 10/14 (the earlier answer "Paris" after 4s on 429 and 500; unreadable sent anyway; a stop between tries sent), pool 2/4 (worker_error, no cooldown, no stop), the gate 53/56 (an empty done charged 88 to 87; a dead worker's job still running after 45s) |
| Review rounds, red first each | tier 1 review (c29d970): grok 16/17, pool 4/5, composer 54/55, the gate 54/56; re-review (1a5e7aa): composer 54/56 (a plain click takes no chip); the per-conversation draft pinned (d7e4555) |
| **Mutants, each on a copy (`docs/agent/reviews/2026-10-21-run-safety-mutants.py`)** | **16 of 16 red**, each on its own check: Grok's empty set back, no retry, endless retry, no stop between tries, an empty 200 taken, a raising read escaping the retry; the empty done charged, whitespace counted as words, the stranded sweep out of `get_job`; the pool's closed-target mapping removed, the provider not stopped, the deletion path keeping a dead browser; the ChatGPT look removed, an unremovable chip sent, a preview with no readable control sent, the remove control clicked without a hover. Two (no stop between tries, an empty 200) survived the first run and went red once the Grok checks were tightened (063dc83) |
| **T1, the real composer** (`tests/provider_probe.py attachment`, three passes, ChatGPT off the worker) | a chip is an `img[src^=data:]` beside `button[aria-label="Remove <name>"]` in the form; select-all and Backspace leave it; **attached on the home page it is gone at any load; attached on a thread's own page it is there again at that thread's next load** (a per-conversation draft), gone at any other; seen by the driver's own look at once after the open (no late hydration); **a plain click takes nothing, a hover on the preview then the click takes it in 1.7s**; the probe's chips cleared; seven uploads of a 1 KB picture left in the account's file store (residue noted) |
| **Real, Grok (2026-10-22 08:00, the host worker on 1a5e7aa, `docs/agent/reviews/2026-10-21-real-safety-runs.py grok`)** | **PASSED**: the first turn "Thủ đô của Pháp là Paris." in 18s, the follow-up in the same conversation "Thủ đô của Đức là Berlin." in 14s, its own words; credits 100 to 98. An earlier try at 03:28 was refused by Grok itself: an empty answer under "High Demand: Grok is under heavy usage right now" (the thread's own page); the driver quoted the new cookie banner instead (parked) |
| **Real, ChatGPT through /v1 with a picture (2026-10-22 03:34)** | **NOT PASSED: the shared account's file storage is full.** The attach brought up "File added to chat only. You don't have enough storage space left to save this file. Remove files to create space." and the send timed out on the composer (job d8c60b81, `worker_error`, refunded), reproduced read-only up to the attach; at 09:59 `chatgpt.com/library` still read "Your storage is full". The owner chose to free the storage by hand (DECISIONS 2026-10-22); the line is to be run again once it is free (`real-safety-runs.py chatgpt`) |

Reviews:
- Tier 1 review: nothing blocking, seven points; fixed in c29d970 (a Grok read that raises is a
  failed try; a preview with no readable remove control refuses; the pool's deletion path drops a dead
  browser; whitespace is no words) and 063dc83 (two checks tightened)
- Scoped re-review: nothing blocking, six points; the third real pass answered the two unmeasured
  ones (no late hydration; the remove press needs a hover); fixed in 1a5e7aa (hover then click, a
  refused look refuses the turn, the deletion check's claim and its twin, the Grok Playwright error,
  the probe's press and summary)

Deviations:
- T1 was the plan's "measure first": its first answer (nothing survives a load) was changed by the
  second pass the review asked for (a thread's draft survives that thread's load), so the driver's
  look is a real defence, not a guard for a hypothetical site
- The dead-worker check waits 45s, not 30s: the api's served window has a floor of 30s
- The real ChatGPT line is NOT PASSED for a cause outside the code (the account's storage)

Left open:
- The ChatGPT real line, once the storage is free
- The account's file store fills with every reference picture; a plan to remove the driver's own
  upload after a turn, or to warn when it is near full
- Grok's refusal quote reads the site's new cookie banner, and `_dismiss_overlays` knows only the
  OneTrust ids
- A turn taken away between ChatGPT's attach and its send still leaves the upload in the account's
  file store (with no thread); a failed first Grok turn leaves its thread with no url on the platform
- The deletion path's provider error is not noted by the runner, so no cooldown follows it (the stop
  is what matters; a browser that dies again under a turn gets `execute`'s cooldown)
