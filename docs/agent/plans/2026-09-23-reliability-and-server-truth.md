# Plan: reliability, cancel, and reading server truth

## 1. Goal

"Tôi cho phép, bạn chỉ cần lo việc hoàn thiện dự án cho tốt và tốt ưu." Scope is items 1 to 4 of
the ranked proposal in `docs/research/2026-09-23-related-projects.md`: provider errors as failures
with backoff and pacing, job leases with cancel and progress, and two measured probes that may let
the worker read structured server state instead of guessing the DOM.

## 2. Non-goals

- Open decision 0 (terms-of-service posture) is not made here; anything that needs a second
  account, including the account pool, waits for it
- Schema and interface batch (message tree, media parents, thumbnails, usage log, quota refill,
  rename, search, Vietnamese strings, mobile) is the next plan, not this one
- patchright, R2, and everything in the research note's "what not to build" list
- No English text matching on provider error banners; the banner's DOM is matched when observed

## 3. Invariants touched and risk tier

- **Quota conservation.** A job charges exactly one credit when created. A job that ends failed,
  cancelled, or as a provider error refunds exactly once. A job is never settled twice, so a worker
  that finishes a reclaimed job late cannot charge, refund, or attach media a second time.
- **Isolation.** One conversation, one thread, one owner, already covered by the two thread checks.
  The Temporary Chat probe may change how threads work and must leave those checks green or be
  dropped.

**Risk tier: 1.** Money-like accounting and a shared contract between api and worker.

## 4. Acceptance evidence

```bash
python acceptance.py          # 18/18 PASSED, exit 0
python acceptance.py --real   # 18/18 PASSED, exit 0, once the account answers at normal speed
python tests/ui_smoke.py      # 18/18 PASSED
```

Five new acceptance checks, each watched failing on the current code first:

| check | measures |
|---|---|
| `a job settles exactly once` | a second result for the same job is ignored and quota is unchanged |
| `a provider error fails the job and refunds` | the mock raises a provider error on a trigger phrase; job `failed`, error kind `provider_error`, credit back |
| `a stranded job is reclaimed` | lease 2s, mock delay 6s: the job is not left `running`; it ends `done` on a later attempt or `failed` at the cap, and quota is consistent |
| `a running job can be cancelled` | cancel during the mock delay; status `cancelled`, credit back, no media attached |
| `health shows code version and pacing` | worker `/health` carries a code sha and the per-provider cooldown and budget state |

One new ui_smoke check: Send becomes Stop while a job runs and pressing it cancels.

Probes, recorded as measurements in Evidence whatever they show:
- shape of `/backend-api/conversation/<id>` as fetched from inside our page, and whether the last
  assistant node exposes `finished_successfully`
- which endpoint the file button hits, seen through `page.on("response")`
- Temporary Chat: does a thread url persist, does file download work, do the isolation checks
  hold

Measured before writing: none of the three probes; all are written as unknown.

## 5. Blast radius

```
acceptance.py
api/*
worker/*
web/*
tests/*
.env.example
docs/research/*
```

## 6. Reuse pointers

- `api/src/jobs.py` `claim_next_job` and `record_result`: the `BEGIN IMMEDIATE` claim and the
  transaction that already refunds on failure; leases and the guard extend them
- `worker/src/runner.py`: the poll loop is where a heartbeat and a cancel check belong
- `worker/src/providers/chatgpt.py` `_await_result`: the once-a-second loop is the cancel and
  progress checkpoint; its stop-button logic becomes the fallback when server truth is available
- `worker/src/providers/mock.py`: trigger-phrase pattern for making a failure mode testable
- `web/src/components/TypingBubble.jsx`: already shows elapsed time; phases go beside it

## Tasks

### T1: Failing checks first
Five acceptance checks and one ui_smoke check, run against current code.
**Files:** acceptance.py, tests/ui_smoke.py
**Acceptance:** 13/18 and 17/18, the new ones red for the right reason

### T2: Leases, guarded settle, cancel in the api
`jobs.lease_expires_at`, `attempts`, `cancel_requested`, `error_kind`; claim sets lease and bumps
attempts and returns them; `record_result` accepts only the claimed attempt and refunds once;
janitor reclaims expired running rows; `POST /jobs/{id}/cancel`; `POST /internal/jobs/{id}/progress`
and `.../heartbeat`.
**Files:** api/src/db/schema.sql, api/src/db/client.py, api/src/jobs.py, api/src/models.py, api/src/routes/chat.py, api/src/routes/internal.py
**Acceptance:** settle-once, reclaim and cancel checks green in mock mode

### T3: Worker heartbeat, cancel checkpoint, phases, provider errors
Renew the lease from the runner; poll the cancel flag inside `_await_result`; post phases
("waiting", "reply started", "picture appeared", "file appeared"); classify provider errors as
`provider_error`; mock gains a trigger phrase for it.
**Files:** worker/src/runner.py, worker/src/pool.py, worker/src/providers/base.py, worker/src/providers/chatgpt.py, worker/src/providers/mock.py
**Acceptance:** provider-error check green; cancel check green end to end

### T4: Cooldown, pacing, budget, code sha in health
Per-provider exponential cooldown after provider errors, minimum gap between turns, rolling image
budget, latency tracking; all in `/health` with the running code's sha.
**Files:** worker/src/pool.py, worker/src/main.py, worker/src/config.py, .env.example
**Acceptance:** health check green; a forced provider error visibly opens a cooldown

### T5: Stop button and phases in the interface
Send swaps to Stop during a job; Stop calls cancel; the typing bubble shows the phase.
**Files:** web/src/pages/Chat.jsx, web/src/components/TypingBubble.jsx, web/src/lib/api.js
**Acceptance:** ui_smoke 18/18

### T6: Probe server truth, then adopt if it holds
Measure the conversation JSON and the download endpoints from inside the page. If the last
assistant node exposes a finished status, settle on it with the DOM loop as fallback; if downloads
are observable on the network, capture there with the button click as fallback.
**Files:** worker/src/providers/chatgpt.py, docs/research/*
**Acceptance:** measurements recorded; `acceptance.py --real` still 18/18

### T7: Probe Temporary Chat
Measure thread persistence, file download, and the two isolation checks under it. Adopt only if all
three hold; otherwise record why not.
**Files:** worker/src/providers/chatgpt.py, docs/research/*
**Acceptance:** measurements recorded; isolation checks green either way

### T8: Full gate and evidence
**Files:** none new
**Acceptance:** the three commands in section 4

## Evidence

Accepted 2026-09-24 at HEAD 8533270, clean tree. Code last changed in 5d618df; 8533270 adds five
lines to the research note (`git diff --stat 5d618df 8533270`: 1 file, docs/research). Fence audit:
"base 6960c2c, 5 commit(s) from base to HEAD, all changes since base are inside the blast radius".

Full gate at HEAD 8533270:

```
python acceptance.py             18/18 PASSED, EXIT=0   health shows sha 8533270
cd web && npm run build          built in 776ms, EXIT=0
python tests/ui_smoke.py         18/18 PASSED, EXIT=0   cloakbrowser venv python, worker PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4
python acceptance.py --real      16/16 PASSED, 2 skipped in this mode, EXIT=0
```

The real run was made on the tree that became 5d618df, just before the commit, so its worker
reported sha 055c250; the files under test were those of 5d618df, and nothing in api/, worker/,
web/ or acceptance.py changed after it.

Section 4 promised `--real` 18/18; measured 16/16 with 2 skips. The two fault-injection checks
(a provider error on a trigger phrase, a worker killed mid-turn) need the mock and are skipped by
name in real mode, each printing its reason. Narrowing deviation: both checks are
provider-agnostic and green in mock mode.

The new checks were watched red first on the base code (T1: acceptance 13/18, ui_smoke 17/18: a
stale result accepted with 200, a provider error stored as done, cancel 404, no code_sha, no Stop
control). Lines worth keeping from the real run:

```
thread reused within a conversation                 the model recalled teal-57651
threads never cross conversations                   a new conversation does not know teal-57651
image job produces file                             811070 bytes at chatgpt-88f4379c6ce44548b983b7717e2f0fe6.png
non image deliverable is kept when asked in vietnamese  198 bytes, type file, entries ['a.txt', 'b.txt']
a follow-up turn packages what the first one made   752996 bytes, type file, entries ['a_minimalist_clean_flat_graphic_image_a_plain_w.png']
a job settles exactly once                          stale attempt refused with 409, real result kept, charged once
a running job can be cancelled                      cancelled while running, credit returned
```

Mock-only lines: `a provider error fails the job and refunds: failed as provider_error, credit
returned`; `a stranded job is reclaimed: finished on attempt 2 after the first worker was killed`.
ui_smoke: `stop cancels a running job: bubble gone within 2.5s, 0 reply bubble(s) appeared
afterwards`.

Probes, measured from inside the page:

- `/backend-api/conversation/<id>`: 404 with cookies alone, 200 with the bearer token from
  `/api/auth/session`. The body carries `mapping` nodes with `message.status`
  (`finished_successfully`), `message.end_turn`, `message.content.parts` or `.text`, plus
  `current_node`, `is_temporary_chat`, `memory_scope`. A file turn is: user text, assistant `code`
  (end_turn false), tool `execution_output` ("Created /mnt/data/x.zip"), assistant text (end_turn
  true). Adopted in 83b3cda: settle on the final assistant node, DOM loop as fallback, a few
  server reads per turn with 429 backoff.
- Files: `/backend-api/conversation/<id>/interpreter/download?message_id=<final
  assistant>&sandbox_path=/mnt/data/<name>` returns `{status: "success", download_url, file_name,
  mime_type}`; `download_url` is a signed estuary link that answers 403 without the session and
  expires within the hour, so the bytes are fetched inside the page. Adopted, the button click
  stays as fallback.
- Temporary Chat: after sending, the url keeps `?temporary-chat=true` and never gains `/c/<id>`,
  so there is no thread to return to and no server view. Rejected; recorded in DECISIONS.
- Throttling: thirteen real turns back to back drew a 429, and the site then bounced stored thread
  pages to the root, where a fresh composer waited. The first real gate at 055c250 read 13/16 with
  `thread ... did not open: landed on https://chatgpt.com/, server status 429`. Fixed in 5d618df:
  verify the url after opening, retry on 429/5xx, fresh chat only on 404, and pace the gate 6s
  apart like the worker.

Left open, parked in HANDOFF: the error banner's DOM signature, a health flag when the provider's
memory is on, Library clutter from one thread per conversation, and the one-turn "10 pictures plus
a zip" variability.
