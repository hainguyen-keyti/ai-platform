# Plan: the gate accounts for a turn that was never sent

## 1. Goal

The owner, 2026-10-01: **"được, tôi duyệt toàn bộ, bạn làm giúp tôi đi"** (the list's second item:
fix the gate's outdated check); and on 2026-10-02 at 01:43, after the report that named it as the
next piece of work: **"Làm giúp tôi đi"**.

Measured, the real ChatGPT gate at a0d04b0, 2026-10-01 20:59 to 21:19: 29/30, the one red
"deleting a conversation cancels its running job and refunds": "seen running delete 204 final
cancelled media None quota 90 -> 90 new files [] a new thread removed False". The cancel check of
the same run read the driver's own word: "cancelled while running, credit returned, at the site
{'sent': False, 'pressed': False}".

Read in the code at 302a274:
- Since 4536183 `worker/src/providers/chatgpt.py:757` `_stop_unsent` stops a job taken away before
  `_send` and records `last_stop = {"sent": False, "pressed": False, "at": <time>}` (`:755`);
  `last_cancelled_thread` is still None, so `worker/src/pool.py:175-181` reports no thread and
  `api/src/jobs.py:394-402` leaves no tombstone. Nothing exists to remove
- `acceptance.py:763-770` still passes only on `worker_removed`: a tombstone new since the delete,
  claimed and settled, and the worker's count grown. It waits 150 seconds for a thread that was
  never made, then fails
- In mock mode the check is green because the mock's slow picture cannot be interrupted and always
  reports a thread (`worker/src/providers/mock.py:103-115`): no mock turn is ever "not sent", so
  the mock gate cannot see this case at all
- The worker's health already shows a provider's `last_stop` (`worker/src/pool.py:223`); the
  cancel check reads it and trusts only a record made after its own cancel
  (`acceptance.py:877-887`)

Done means: the gate has one rule for what became, at the provider, of a turn taken away from a
running job: its thread **removed** (as today), or the turn **unsent**, by the driver's own stop
record made after the turn was taken away, with no tombstone waiting. The rule is a function with
a table the gate checks on every run. The mock provider can play a turn that is stopped before it
goes out, and a new mock check sees the real run's failure with the rule as it was and passes
with the new one. In mock mode the old check still passes only on a thread removed. The real
ChatGPT gate passes that check on either word.

## 2. Non-goals

- The real drivers, the pool, the runner, the api and the web: nothing there changes
- Grok and Gemini sending a turn stopped before its send (they still do; parked)
- A sent turn stopped at the site by its stop button: the cancel check and the stop probe cover it
- The interrupted gate's "stack did not start" table, any other check, a way to run a subset
- A new health field: the gate reads the `last_stop` that is already there

## 3. Invariants touched and risk tier

- **The ruler.** The gate passes the deletion of a running job only on the worker's own word: a
  thread removed, or a stop record made after the delete that says the turn never went out, with
  no tombstone waiting. Never on the absence of a thread alone, never on a record older than the
  delete, never on a record that says the turn was sent
- **Mock mode is not loosened.** The mock's slow picture always makes a thread, and its check
  still passes only when that thread was removed
- **Quota.** Both checks still require the refund, exactly once

### Risk tier

**Tier 1** (a gate): a strong-model review through a risk lens, at least three separate mutants,
and a scoped re-review after fixes.

## 4. Acceptance evidence

```
python acceptance.py                      # 41/41 PASSED; red first at 39/41 with the rule as it was
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: 41/41, build exit 0, 53/53
python -u acceptance.py --real --keep     # real ChatGPT, ChatGPT off the host worker: 31/31 PASSED, 10 skipped
```

Red first: with the rule as it was (a thread removed, nothing else) the two new checks are red,
the mock's unsent turn for the reason the real gate failed (no thread removed, no other word), the
table on its rows that expect "unsent".

Mutants, each on a copy. On the rule, run against its table: a stop record older than the delete
accepted; `sent` read as falsy instead of False; a waiting tombstone ignored; a sent turn accepted;
removal no longer winning. On the gate end to end, a full mock run each: the freshness rule
dropped (the mock's slow picture check must go red, it runs after the unsent turn's check); the
mock's unsent turn making a thread all the same; the mock recording no stop.

Real: one ChatGPT turn alone first (if Cloudflare's check answers it, the real line is NOT PASSED
and ChatGPT's runs stop). Then the real gate: "deleting a conversation cancels its running job and
refunds" PASSED, saying which word accounted for the turn, in seconds where it waited 150.

## 5. Blast radius

```
acceptance.py
worker/src/providers/mock.py
```

## 6. Reuse pointers

- `acceptance.py:729-779`, the check; `:651-655` `worker_removed`; `:877-887` the cancel check
  reading `last_stop` and trusting only a record made after its cancel
- `worker/src/providers/chatgpt.py:754-763` `_stopped` and `_stop_unsent`, the behaviour the mock
  is to play; `worker/src/providers/mock.py:15-20` the phrases the mock reacts to
- `tests/session_check.py`: a verdict as a function with its table
- `docs/agent/plans/2026-09-30-gate-checks-measure-the-thing.md`: the last change to these checks,
  and how a gate mutant is run on a copy

## Tasks

### T1: Red: the mock plays an unsent turn, the rule as it was fails it
`mock.py`: a phrase that makes a chat turn wait, before any thread exists, for its job to be taken
away; taken away there, it records `last_stop` with `sent` False and reports no thread.
`acceptance.py`: the rule as a function, holding the rule as it was (removed, or nothing); its
table; the old check calling it; two new checks, "a turn taken away before it was sent leaves no
thread, by the worker's own word" (mock only, placed before the old check) and "the gate's rule
for a turn taken away holds on its table".
**Files:** worker/src/providers/mock.py, acceptance.py
**Acceptance:** `python acceptance.py` 39/41, exactly the two new checks red

### T2: The rule
The function answers "unsent" on a stop record made after the turn was taken away that says
`sent` False, when no tombstone waits. The old check accepts that word in real mode only.
**Files:** acceptance.py
**Acceptance:** `python acceptance.py` 41/41

### T3: Review, mutants, re-review, the full gate, the real gate, Evidence
The tier 1 review; any fix seen red first; the mutants; a scoped re-review of the fixes; the full
gate once on a clean tree; one real ChatGPT turn alone, then the real gate with ChatGPT off the
host worker.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-10-02 at **b589041**, clean tree, four commits (2315e53, 846da86, 0a69824, b589041),
the audit clean. Every number is the command's own count line.

| Command | Result |
|---|---|
| `python acceptance.py` | **43/43 PASSED**, exit 0 (the gate has 43 checks where section 4 said 41: the review rounds added two). Red first three times: **39/41** at 2315e53 with the rule as it was (the mock's unsent turn "accounted None stop record {'sent': False, ...} new tombstones 0", the real gate's failure met in mock; the table 2 of 15 rows); **40/43** before 0a69824 (the gate believed a driver that said unsent 2.5 seconds before it reported a thread; 3 of 20 rows; the old check red as a knock-on); and before b589041 the lying check's wait for the thread was seen at one look only, by luck of timing |
| Full gate, once, at b589041, clean tree, the host worker in mock (04:29 to 04:35) | `python acceptance.py` **43/43 PASSED** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **53/53 PASSED** exit 0; tree unchanged after |
| Mutants at b589041 (`/tmp/run_gate_unsent_mutants.py`, each on a copy of HEAD) | **35 of 37 red.** The two rules against their tables: 21 of 22 (`>=` turned into `>` survives: a tie of two floats no real record meets). End to end, a full mock gate each: 14 of 15 (`/tmp/gate_unsent_mutants_g2.log`); not red: the mock's slow picture allowed to pass as unsent, which a right rule can never answer there (both reviewers call it equivalent) |
| One real ChatGPT turn alone, through the platform (02:06) | done in 22s, no Cloudflare check |
| **The real ChatGPT gate at b589041** (`python -u acceptance.py --real --keep`, 04:37 to 04:54, ChatGPT off the host worker, log `/tmp/chatgpt-real-gate-b589041.log`, workspace `$TMPDIR/ai-platform-acceptance-ou5249ge`) | **30/31 PASSED, 12 skipped, exit 1; 16 jobs, no Cloudflare check.** The plan's check: **"[PASS] deleting a conversation cancels its running job and refunds: job cancelled by the delete, credit returned, no media row or file written, its turn never sent, by the worker's stop record {'sent': False, 'pressed': False, 'at': ...}: no thread to remove"**; the driver's record was made 3.8 seconds after the delete (21:52:21 and 21:52:24.8 UTC), where the check had waited 150 seconds and failed. Also green: the table (21/21 and 10/10 rows) and "a running job can be cancelled ... at the site {'sent': False, 'pressed': False}" |

**Not passed as written: the real gate's count (section 4 said every check that runs passes).** The
one red is another check, "a conversation's media downloads as one zip": "conversation holds 1
media". The run's own record names the cause: job 7a128c65, the turn "vẽ cho tôi một hình vuông
màu xanh", failed as `provider_timeout`, "chatgpt returned nothing after 302s" (04:46:14 to
04:51:19); the next turn found the picture in the thread and zipped it (709936 bytes), so the
conversation held the zip alone where the check wants two media. ChatGPT's pictures have taken
290 to 335 seconds in every run since 2026-09-29, against the driver's 300. Nothing in this plan
touches that; it is parked. The gate was not run again: a second burst of sixteen jobs right
after the first is what drew Cloudflare's check on 2026-10-01.

Review, tier 1, two passes by a strong model, read-only, with mock gates on copies:
- **The review of 302a274..846da86** (95 tool uses): 1 blocking, 7 non-blocking, 7 of its mutants
  through. Blocking: only a table with one moment held "never on a record older than the delete";
  the order of the two checks did nothing measurable, and the plan's own end to end proof of it
  had not gone red. Fixed in 0a69824: nothing accounts for a turn while anything is still owed
  (its result not handed back, a tombstone made since and not settled, the api's record
  unreadable); a removal does not answer while another thread waits; the slack is 0.05s, the
  most a time rounded to a tenth can read below its moment; the tables carry their own moments
  and sizes; two mock checks were added (a silent driver with an older record in hand stays
  unaccounted for; a driver that says unsent of a turn that made a thread is believed only once
  it is removed)
- **The scoped re-review of 846da86..0a69824** (55 tool uses, 24 full mock gates): nothing
  blocking, B1 closed, 8 non-blocking. Fixed in b589041: a turn is unsent only when no thread at
  all was tombstoned since; a look reads the refusals before the tombstones; a count the
  worker's health could not give is None, never 0; the lying driver's thread takes 2.5s to
  remove and its check must be seen holding its answer through both waits (5 looks and 5 in the
  run), where a look that read no tombstones had passed; the second table gained a row
- No third pass: b589041 answers findings the re-review gave with repros, and those repros and
  its surviving mutants were run again (a look that reads no tombstones, the lie told with no
  delay, the last-stone-only rule: all red now)

Left open, said by the reviews and not changed:
- A healthy run cannot show that an unreadable record counts as still owed: only the forced
  failure does (the database path that is not there: 39/43, the unsent check red). The same for
  the refusal count being taken before the turn is posted: the mock's results come back 0.3s
  after the delete at the earliest
- After a failed check whose result is still out, the next check can count the late refusal as
  its own: a knock-on in a run that is already red
- Other reads of the worker's health elsewhere in the gate still raise on a failed read (the
  checks outside this plan); the four helpers these checks use do not
- The real gate's check for a turn that WAS sent and then stopped at the site (the driver
  pressing stop) was not met in this run: the stop came before the send, as on 2026-10-01. The
  stop probe is still owed for it

Deviations from the plan's words, all stricter: section 4 expected the mock's slow picture check
to go red when the freshness rule is dropped; measured, it cannot (that turn's tombstone already
waits when its loop starts), so the silent-driver check holds that end to end instead. "With no
tombstone waiting" became "with nothing still owed and no thread tombstoned since". The gate has
43 checks, the real run 31 counted and 12 skipped.

Real ChatGPT turns spent: one alone at 02:06 and the gate's sixteen jobs. The gate left ten test
threads in the account (`docs/agent/residue-to-delete-2026-10-02.json`, dry run "10 threads, 0
memories"); deleting them is the owner's to run.
