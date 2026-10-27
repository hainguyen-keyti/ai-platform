# Plan: A provider its admin must fix is held out; Stop stops the turn at ChatGPT

## 1. Goal

The owner, 2026-10-01, after the acceptance walk: **"giờ làm gì tiếp theo, xử mấy mấy cái chưa
đạt hay sao"**, then **"Cả hai lỗi, một plan"**; in the interview: **"Tự thử lại sau 10 phút"**,
**"Mọi lỗi cần quản trị viên"**, **"ChatGPT dừng thật, cả ba biết huỷ trong 5 giây"**, **"Tier 2"**;
at approval: **"Duyệt"**, and the probe deletes its own threads (**"Cho tự xoá"**).

Measured 2026-10-01 (the acceptance walk `/tmp/e2e_acceptance.py`, its job records, and the code):

- Gemini's saved session was signed out (the second time in three days). Both Gemini turns failed
  before anything was sent, `error_kind` `provider_misconfigured`, credits returned. The worker kept
  pinging, so the api kept Gemini served (`_served` is a ping within the window,
  `api/src/jobs.py:194-200`), the web kept offering it, and the header showed "the gemini session
  is signed out; run scripts/login_provider.py gemini" (`web/src/lib/api.js` `waitForJob` throws
  `job.error`; `web/src/pages/Chat.jsx` `runJob` sets it as the error)
- `provider_misconfigured` is what the drivers raise for an account the platform must not speak
  into: Gemini and Grok signed out (`gemini.py:243-244`, `grok.py:240-255`), memory or personal
  context switched on (`chatgpt.py:769-770`, `gemini.py:246`, `grok.py:440`)
- A ChatGPT turn stopped 2.5s after Send still ran at ChatGPT; its result was refused afterwards
  (`results_refused` 0 -> 1). Three causes in the code: the runner asks the api whether its job is
  alive every lease/3 (`worker/src/runner.py:139`), 140s with the production lease of 420s
  (`api/src/config.py:25`), so a 30s turn ends before the worker learns of the cancel; the gate runs
  with a 2s lease (`acceptance.py:1211`) and never saw it. The driver never checks for a stop before
  typing (`chatgpt.py:763-787`). A stop seen after the send leaves the page without pressing the
  site's stop button (`chatgpt.py:808-819`)

Done means:

1. A turn that fails as `provider_misconfigured` holds its provider out for 10 minutes
   (`PROVIDER_HOLD_SECONDS`, default 600): `GET /providers` says `served: false`, a new turn is
   refused 503 and uncharged, jobs already waiting for that provider fail at once with their credit
   returned; once the hold ends, the next turn is tried again
2. The web shows such a failure as the existing "unavailable" notice in the person's language, never
   the admin's instruction
3. Every runner learns of a cancel within 5 seconds, whatever the lease
4. ChatGPT: a turn cancelled before it is typed is never sent; one cancelled while its reply runs
   gets the site's stop button pressed; `/health` says which happened (`last_stop`)

## 2. Non-goals

- Grok's and Gemini's own stop buttons: a turn already sent there still runs (parked)
- ChatGPT's logged-out classification: it stays `provider_error` with its cooldown
- The worker's `/health` `ready` flag; any periodic re-check of a held account (no extra page loads)
- The lease length, the served window, the quota rules
- Why Gemini's session dies; the "Keyti" identity finding; the e2e walk into the repo

## 3. Invariants touched and risk tier

- One credit per job: taken when the job is made, given back exactly once by every job that ends
  without a result. Touched: jobs failed because their provider is held refund once each, behind
  the same rowcount guard `_sweep_unserved` uses
- A job settles exactly once; a late result is refused with 409. Unchanged, re-checked by the gate
- No turn goes out for a job the api no longer holds live. Tightened: checked right before typing
- No turn goes into an account in a state the platform must not speak into. Unchanged, and no job
  reaches a held provider
- One browser session per provider: unchanged (the probe and the real gate take ChatGPT off the host
  worker while they run)

### Risk tier

**Tier 2**, the owner's choice on 2026-10-01: one code review round, then mutants, no re-review; no
design review (no new UI element, the existing notice is reused).

## 4. Acceptance evidence

```
python acceptance.py                                            # 39/39 PASSED (36 + 3 hold checks)
~/cloakbrowser-env/bin/python tests/test_runner_liveness.py     # 4/4 PASSED (3 + the cancel cadence)
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py    # 21/21 PASSED (19 + 2 stop checks)
(cd web && npm run build)                                       # exit 0
~/cloakbrowser-env/bin/python tests/ui_smoke.py                 # 53/53 PASSED (52 + the notice)
python acceptance.py --real --keep                              # real ChatGPT: every check that runs passes (30 at 3e32a12)
~/cloakbrowser-env/bin/python /tmp/stop_probe.py                # real ChatGPT, before (T1) and after (T4)
```

The new checks, each red in T1 on a8b5302 unless said otherwise:

- Gate, "an account its admin must fix holds its provider out at once": right after the mock's
  memory refusal, `GET /providers` says that provider is not served, a new turn for it is refused
  503 with the quota unchanged, the other provider is still served
- Gate, "jobs waiting for a held provider fail and refund at once": a job queued behind the refused
  one (behind a slow turn) fails within seconds without ever being claimed, its credit returned
- Gate, "a hold ends by itself": the gate's api runs with `PROVIDER_HOLD_SECONDS=5`; once it has
  passed, the provider is served again and an ordinary turn completes. Green today (no hold
  exists): a guard, proven by mutant M3. The three run right after the memory check, wait for its
  own hold to pass first, and the last one waits its hold out, so nothing after them meets one; they
  skip in real mode with the memory check
- Liveness, "a cancel reaches the driver within the cancel cadence whatever the lease": a 420s lease
  and the api answering not alive: the driver's stop flag is set within the cadence, and the
  cadence constant is at most 5s
- Composer, "a job stopped before its send types nothing and sends nothing" and "a job stopped while
  its reply runs presses the site's stop button"
- ui_smoke, "a turn its provider's account refuses shows the unavailable notice, not the admin's
  instruction", played in the browser, in English and Vietnamese
- The real gate's "a running job can be cancelled" also reads the worker's `last_stop`: the turn was
  not sent, or its stop was pressed. Red by construction today (no `last_stop`); not run red, to
  save about 15 real turns: the walk's record and the T1 probe are its real red evidence
- The real probe, ChatGPT off the host worker, two turns per run (a long text, a picture), each
  thread deleted by the driver afterwards and read back as 404: in T1 the probe itself presses the
  stop button on today's driver and measures whether the button is there while a text streams and
  while a picture is made, and what pressing it leaves on the server (the last node's status, a
  picture arriving later or not); in T4 the driver presses it through a stop hook

Mutants, each must turn its check red: M1 no hold on a misconfigured result; M2 waiting jobs not
failed at the hold; M3 the hold never ends; M4 a held provider still accepted; M5 the web shows the
error text for a misconfigured failure; M6 the heartbeat back to lease/3; M7 no stop check before
the send; M8 no stop press after the send; M9 a job failed by the hold without its refund.

## 5. Blast radius

```
api/src/jobs.py
api/src/config.py
api/src/db/schema.sql
worker/src/runner.py
worker/src/pool.py
worker/src/providers/chatgpt.py
web/src/lib/api.js
web/src/pages/Chat.jsx
acceptance.py
tests/test_runner_liveness.py
tests/test_chatgpt_composer.py
tests/ui_smoke.py
.env.example
# Widened on 2026-10-01 with the owner's yes, after the review: Grok's driver called any answer but
# 200 "signed out", which the hold would turn into ten minutes out for a passing 429 or 500.
worker/src/providers/grok.py
tests/test_grok_memory.py
# Widened again on 2026-10-01 with the owner's yes: the login script did not know ChatGPT's session
# cookie in its chunks (.0, .1), so no ChatGPT login could be saved and the plan's real runs waited.
scripts/login_provider.py
tests/test_login_provider.py
```

## 6. Reuse pointers

- `api/src/jobs.py`: `_sweep_unserved` (fail and refund behind a rowcount guard), `_served`,
  `worker_pings`
- `acceptance.py`: "memory on refuses the turn and refunds" (`MEMORY_PHRASE`), "a turn nobody serves
  is refused at once and uncharged", "a job queued behind a long turn is not failed as unserved"
  (`SLOW_PHRASE`)
- `tests/test_runner_liveness.py`: the fake `Client`
- `tests/test_chatgpt_composer.py`: the fake `Page` (`has`, `token_after`)
- `tests/ui_smoke.py`: `answer_served` and `refuse_chat` (answers played in the browser)
- `/tmp/cold_delete_probe.py`: the driver driven from a script, ChatGPT off the host worker

## Tasks

### T1: Red checks and the real measurement
The seven checks above in the gate, the two tests and ui_smoke; the real probe on today's driver.
**Files:** acceptance.py, tests/test_runner_liveness.py, tests/test_chatgpt_composer.py,
tests/ui_smoke.py
**Acceptance:** `python acceptance.py` 37/39 (the first two hold checks red, the third green as a
guard); liveness 3/4; composer 19/21; ui_smoke 52/53; the probe's measurements recorded

### T2: The hold
The api holds a provider whose turn failed as `provider_misconfigured`: a hold table, set with the
failure, waiting jobs failed and refunded, not served while held, `PROVIDER_HOLD_SECONDS`; the web
shows the unavailable notice for such a failure.
**Files:** api/src/jobs.py, api/src/config.py, api/src/db/schema.sql, web/src/lib/api.js,
web/src/pages/Chat.jsx, .env.example
**Acceptance:** `python acceptance.py` 39/39; ui_smoke 53/53; `(cd web && npm run build)` exit 0

### T3: Stop
The runner's heartbeat at most every 5s; ChatGPT checks for a stop right before typing and presses
the site's stop button when a stop comes after the send; `last_stop` in `/health`; the real gate's
cancel check reads it.
**Files:** worker/src/runner.py, worker/src/pool.py, worker/src/providers/chatgpt.py, acceptance.py
**Acceptance:** liveness 4/4; composer 21/21; `python acceptance.py` 39/39

### T4: Review, mutants, full gate, real gate, real probe, Evidence
**Files:** none new (review fixes stay inside the radius)
**Acceptance:** section 4; the host worker back to real (Gemini too once the owner has logged in;
while it is still signed out, one Gemini turn through the web shows the real hold)

## Evidence

Set aside 2026-10-01 at **db429a1**, clean tree, by the owner's choice ("Dùng profile cố định của
nó"): the code, its review, its mutants and the full gate are done; **its two real ChatGPT lines are
NOT PASSED** and become acceptance lines of the session plan
(`2026-10-01-one-profile-per-provider.md`). Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once at the last commit: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **39/39 PASSED** exit 0, build exit 0, **53/53 PASSED** exit 0, at db429a1 with the host worker in mock (`MOCK_DELAY_SECONDS=4`), the tree clean before and after. The same once at 482413e, before the login script fix: 39/39, build exit 0, 53/53 |
| Offline suites at db429a1 | composer **22/22**, runner liveness **4/4**, grok memory **20/20**, grok settle 8/8, login provider **5/5**, gemini driver 62/62, runner health 4/4, runner tombstones 3/3, tombstones 5/5, DOM signatures 10/10, each exit 0 |
| T1 on a8b5302 (6bc040d), red first | `python acceptance.py` **37/39**: a held provider still served, a new turn 202 and charged, the job behind it done with attempts 1 ("a hold ends by itself" green as a guard, proven by mutant M3); liveness **3/4** (a 420s lease: the driver never told within a 3s turn, no cadence constant); composer **19/21** (a stopped job's turn sent; the stop button never pressed); ui_smoke **52/53** (no notice, the admin's English text in the header in both languages) |
| T2 (fcf1a06) | `python acceptance.py` **39/39**: not served right after the refusal, grok still served, a new turn 503 and uncharged; the job behind it failed at once, never claimed, quota 95 -> 94; served again 4.2s later, an ordinary turn done. ui_smoke **53/53** (the notice in English and Vietnamese, no header error, no admin text); `npm run build` exit 0 |
| T3 (4536183) | liveness **4/4** (cadence 5.0s; with a 420s lease the driver told to stop 0.52s into a 3s turn); composer **21/21** (stopped before the send: nothing typed, `last_stop` sent false; stopped while writing: the stop button pressed once, `last_stop` pressed true); `python acceptance.py` 39/39 |
| Code review (tier 2) | 0 blocking, 10 non-blocking. Fixed in 482413e, each seen red first: a stopped job attaches no picture (composer 22/22); Grok signed out only on 401 or 403, and its stop waits for the new chat's address (grok memory 20/20, 17/20 red first; the radius widened to `worker/src/providers/grok.py` and `tests/test_grok_memory.py` on the owner's yes); the gate's hold checks tightened. The rest is under "Left open" at the end of this file |
| Mutants on copies (`/tmp/run_hold_stop_mutants.py`, on 482413e) | **15 of 15 red**, each on its own check (logs `/tmp/hold_stop_gate_mutants.log`). M4 as first written (only `create_job`'s held branch removed) was an equivalent mutant, `_served` refusing already; it was redefined as "`_served` ignores the hold" |
| The real probe on the driver before the change (T1, `/tmp/stop_probe.py before`, ChatGPT off the host worker) | the site's stop button is there at once after the send, for a text and for a picture; pressed at 5.8s the text stopped at 792 chars (none added in 10s; the server calls the node finished_successfully, 841 chars); pressed at 9.9s no picture arrived in 120s; both threads deleted by the driver (True) |
| The real Grok check (`/tmp/grok_stop_check.py`, two turns through the platform, 482413e) | a plain turn done in 25s ("Paris"); a turn stopped 8s after its send: the worker's result refused 4.1s after the stop, the new chat's thread stored for its conversation |
| The login script (db429a1; the radius widened to `scripts/login_provider.py` and `tests/test_login_provider.py` on the owner's yes) | `tests/test_login_provider.py` **5/5**, the chunked cookie case red on the old matcher; on the real site the owner's login of 16:34 printed "signed in (__Secure-next-auth.session-token.0 cookie present)" and "session saved", where the login before it had waited until Ctrl+C |
| `python acceptance.py --real --keep` | **NOT PASSED, twice.** At 482413e (14:57): the first three turns failed "the provider rejected a fresh session token; the session is logged out or expired" (the run's own job records, `$TMPDIR/ai-platform-acceptance-snmfc5q1`), interrupted by the agent. At db429a1 on the owner's new login (16:35 to 16:48, `$TMPDIR/ai-platform-acceptance-4e01f7i4`): memory read `off`; 10 jobs, 7 done (pong 22s; a word recalled in its thread and not in another conversation; two zips; a picture asked for in a chat turn after 317s), 2 failed (a picture job, `worker_error`, "Locator.inner_text: Timeout 30000ms exceeded" on the composer; a follow-up turn, `provider_error`, "the provider showed its error banner: cloudflare_challengeRetry", after which a thread deletion answered 403), 1 cancelled by the gate's own check; interrupted by the agent, who does not push on a bot check. "a running job can be cancelled" never ran, so `last_stop` was never read on the real site |
| `/tmp/stop_probe.py after` | **NOT RUN**: three more real turns into a session Cloudflare was refusing |
| The real Gemini hold through the web | **NOT RUN**: the owner declined the call |

Tier 2: one code review round, mutants after the fixes, no re-review. Proven: the hold and its
notice (the mock gate, ui_smoke); the cancel cadence (the unit test, and the real Grok turn refused
4.1s after its stop); a ChatGPT turn stopped before its send is not typed and one stopped after it
gets the stop button pressed (a fake page); what the site's stop button does when pressed (the T1
probe). **Not proven: the driver pressing that button on the real site**, which the two real lines
would have shown. Deviations: (widening, each approved by the owner) the radius, twice; (narrowing)
the real Gemini hold not run. The host worker serves only Grok: ChatGPT's session is behind
Cloudflare's check and Gemini's is signed out (HANDOFF).

## Left open (moved from HANDOFF on 2026-10-02)

What the review left open (non-blocking, not fixed):

- From the hold-and-stop review (2026-10-01, non-blocking, the reviewer's probes on copies):
  (1) a stranded job requeued while its provider is held is still claimed once (`api/src/jobs.py`,
  `claim_next_job` never reads `provider_holds`): the driver refuses it before sending, credits
  stay right, the hold is pushed out once more; the plan's "no job reaches a held provider" is
  false in that corner; (2) `PROVIDER_HOLD_SECONDS=0` sets no hold but still fails the waiting
  jobs, a negative value makes `record_result` raise and leaves the refused job running; and
  `docker-compose.yml` passes the api only five variables, so the `.env` value never reaches it
  (the default 600 applies, as for the lease settings); (3) a picture attached less than 3s before
  a stop stays in the composer until the next page load (not proven to survive it); (4) a cancel
  heard as the reply ends reads `last_stop` sent true, pressed false, and one heard while files
  are collected is not heard at all; the real gate's cancel check stops before the send, so only
  the probe exercises the press; (5) the web still shows admin text for `provider_error`
  failures: ChatGPT logged out or its token rejected (`chatgpt.py` `_read_memory`, `_open`), and
  a missing session file with its host path (`worker/src/pool.py:148-153`); with today's rejected
  token this is what a person would have read; (6) Grok and Gemini still send a turn cancelled
  before their send, and never press their own stop (non-goals of the plan); Gemini calls a
  session signed out when its settings tab is off Gemini's host after 15s, not probed for misreads;
  (7) the create_job `_held` branch only changes the 503's words, `_served` refuses already

## The stop probe, run at last (2026-10-02, after the plan was set aside)

`~/cloakbrowser-env/bin/python /tmp/stop_probe.py after --keep` at b589041, 17:39 to 17:44, ChatGPT
off the host worker, three real turns, no Cloudflare check, the threads kept (the agent may not
delete account data for good). The driver pressed the site's stop button through its stop hook in
all three (`last_stop` sent true, pressed true):

| Turn | What the run printed |
|---|---|
| A long essay, stopped 4s after the stop button showed (9.9s after the send) | "outcome cancelled"; the button gone at once; 0 characters 2s later and 0 ten seconds later; no thread address (the page stayed on `/c/local-chatgpt:<uuid>`, the placeholder of a chat the server has not named), so no thread was reported |
| A picture, stopped 8s after the button showed (10.0s after the send) | "outcome cancelled"; the button gone 3.1s later; no picture in the next 120s; the thread reported (6abf8a46) and, by the server, its last node a finished text of 347 characters |
| The essay again, stopped the moment the button showed (13.6s after the send) | "outcome cancelled"; 0 characters; no thread address (the same placeholder) |

So Stop stops a ChatGPT turn at the site: nothing more is written and no picture is drawn. Not
known: whether a turn stopped before the model wrote anything leaves a conversation in the
account (the page shows only a placeholder address, which the driver rightly does not report).

