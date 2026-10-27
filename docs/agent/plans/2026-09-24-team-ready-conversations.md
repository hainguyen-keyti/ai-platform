# Plan: team-ready conversations

## 1. Goal

"được làm đi", on the next-step list the owner approved: "batch schema + giao diện (... quota tự
nạp, trash dùng lệnh xoá thread đã đo, đổi tên/tìm conversation, thông báo khi tab ẩn, chuỗi tiếng
Việt, ... render markdown trong lời model)". Standing instruction: "Tôi cho phép, bạn chỉ cần lo
việc hoàn thiện dự án cho tốt và tối ưu."

This plan is the half of that batch a team hits in its first week: conversations that can be
renamed, searched and deleted (with their media and their provider thread), a quota that refills
daily to a per-user cap, an admin view of who used what, replies rendered as the model wrote them,
the interface in Vietnamese with a switch, a heads-up when a reply lands while the tab is hidden,
and a script the owner runs to clear the test residue in the shared account.

## 2. Non-goals

- Message tree (`messages.parent_id`, edit or regenerate), media parents and kinds, thumbnails,
  PNG metadata, a byte cap, the mobile pass, the patchright fallback: the next plan
- Grok, Gemini, R2, account pool
- The agent deleting anything in the owner's ChatGPT account; the residue script is written here
  and run by the owner, dry-run by default
- Changing how a turn is sent, settled or collected; the only new provider call is the measured
  thread deletion
- English text matching on any provider element
- A second usage ledger: usage is read from the jobs table that already records every job

## 3. Invariants touched and risk tier

- **Quota conservation.** The daily refill raises `quota_remaining` to the user's cap at most once
  per calendar day (UTC) and never above the cap or below the current value; charges and refunds
  stay as they are. Deleting a conversation cancels and refunds any job still live in it (decided
  during review, DECISIONS 2026-09-24) and otherwise never touches the balance.
- **Ownership and isolation.** Rename, search and delete act only on the caller's conversations;
  search never surfaces another user's titles or message text; deleting a conversation removes
  its media rows and files and schedules deletion of its provider thread, which belongs to that
  conversation alone. A tombstone is processed at most once per attempt and retried at most 3
  times.
- **Server truth on the provider.** The thread deletion call is the one measured on 2026-09-24
  (`PATCH /backend-api/conversation/<id> {"is_visible": false}`, then GET 404).

**Risk tier: 1.** Quota logic, deletion of user data, a new api/worker contract, a new dependency
in the interface. Strong-model review with at least 3 mutants; scoped re-review after fixes.

## 4. Acceptance evidence

```bash
python acceptance.py                                  # 26/26 PASSED, exit 0
python acceptance.py --real                           # 23/23 PASSED, 3 skipped in this mode, exit 0
~/cloakbrowser-env/bin/python tests/ui_smoke.py       # 25/25 PASSED   (mock worker, MOCK_DELAY_SECONDS=4)
cd web && npm run build                               # exit 0
python scripts/purge_test_residue.py <list.json>      # dry run: prints the counts, makes no request
```

Four new acceptance checks, each watched failing on the current code first:

| check | measures |
|---|---|
| `a conversation can be renamed and found by search` | `PATCH /conversations/{id}` with a title returns it renamed; `GET /conversations?q=` finds it by the new title and by a word inside one of its messages; the other user's same search returns 0 items; renaming another user's conversation is 404 |
| `deleting a conversation removes its media files and the provider thread` | `DELETE` returns 204; the conversation, its messages and its media ids answer 404; the files are gone from the media directory; quota unchanged; the worker's `/health` `threads_deleted` rises by one within 30s (mock records the url; real sends the measured PATCH) |
| `quota refills once a day up to the cap` | after spending, restart the api with `CLOCK_OFFSET_SECONDS=86400`: `/auth/me` reads the cap; a second read does not stack; one more job reads cap minus one and stays there |
| `admin sees usage per user, others do not` | `GET /admin/usage` as the first user lists both users with `jobs_total = done + failed + cancelled + open` and `images`; as the second user it is 403 |

Six new ui_smoke checks: markdown renders (`<strong>` present, no literal `**` or `sandbox:` in the
bubble), rename from the sidebar, search filters the sidebar, delete from the sidebar removes it
and its gallery items, the Vietnamese switch changes the labels and back, a reply landing while
`document.hidden` badges the title and the badge clears on return.

Measured before writing: the thread deletion call (docs/research/2026-09-24-provider-measurements.md,
"Deleting a thread"). Not measured: `react-markdown` rendering shape (`<strong>` for `**x**`) and
its handling of `sandbox:` hrefs; the notification permission state in headless cloakbrowser
(the check reads `document.title`, not the Notification). Both become probes in T1.

## 5. Blast radius

```
acceptance.py
api/*
worker/*
web/*
tests/*
scripts/*
.env.example
docs/research/*
```

## 6. Reuse pointers

- `api/src/routes/conversations.py:11` list, `:24` get, `:63` delete: the ownership queries to
  extend; `api/src/routes/media.py:88` `delete_media`: unlink after the row is gone
- `api/src/jobs.py:46` `create_job`: the quota check the refill must run before; `:115`
  `_sweep_stranded`: the sweep pattern for tombstones
- `api/src/security.py:51` `current_user`: one choke point for the daily refill
- `api/src/db/client.py:36`: the idempotent ALTER list; `api/src/db/schema.sql:60` the jobs table
  as the shape for `thread_tombstones`
- `api/src/routes/admin.py:10` admin guard and listing; `api/src/routes/internal.py:10` claim
- `worker/src/runner.py:31` the poll loop; `worker/src/pool.py:117` `execute` under the lock;
  `worker/src/providers/chatgpt.py:301` `_thread_nodes` token pattern, `FETCH_INTERPRETER_FILE`
  at `:130` for a fetch that carries a body; `worker/src/providers/mock.py:66` `_thread`
- `web/src/pages/Chat.jsx:150` sidebar, `:189` reply bubble; `web/src/App.jsx:27` nav;
  `web/src/lib/api.js:41` request helpers; `web/src/components/FileCard.jsx` string surface
- `acceptance.py:627` `restart_worker` as the model for `restart_api`; `tests/ui_smoke.py:175`
- `tests/provider_probe.py` `FETCH_JSON` and `Probe` for the owner's script

## Tasks

### T1: Dependency, probes, failing checks
`npm install react-markdown` in web (lockfile committed); a 20-line probe that renders `**x**` and
a `sandbox:` link through react-markdown in the dev server and prints the resulting tags; four
acceptance checks and six ui_smoke checks written and run red.
**Files:** web/package.json, web/package-lock.json, acceptance.py, tests/ui_smoke.py
**Acceptance:** 22/26 and 19/25, the new ones red for the right reason

### T2: The api
`users.quota_daily` and `users.last_refill_day`; `thread_tombstones` table; refill in
`current_user` with `CLOCK_OFFSET_SECONDS`; `PATCH /conversations/{id}`, `?q=` on the list,
`DELETE` purging media rows and files and inserting a tombstone; `POST /internal/tombstones/claim`
and `/internal/tombstones/{id}/result` with a sweep; `GET /admin/usage`; `quota_daily` on the admin
quota route; models and `.env.example`.
**Files:** api/src/db/schema.sql, api/src/db/client.py, api/src/config.py, api/src/security.py, api/src/jobs.py, api/src/models.py, api/src/routes/conversations.py, api/src/routes/internal.py, api/src/routes/admin.py, .env.example
**Acceptance:** rename/search, refill and usage checks green in mock; delete check green except the health counter

### T3: The worker
`BaseProvider.delete_thread(url) -> bool`; ChatGPT sends the measured PATCH from inside the page
and treats 404 as done; the mock records the url; the pool runs it under the provider lock; the
runner claims a tombstone when no job is waiting, at most every 10s; health shows
`threads_deleted` and `thread_deletions_failed`.
**Files:** worker/src/providers/base.py, worker/src/providers/chatgpt.py, worker/src/providers/mock.py, worker/src/pool.py, worker/src/runner.py, worker/src/main.py
**Acceptance:** delete check fully green in mock

### T4: The interface
Replies through react-markdown with `sandbox:` links rendered as text and other links opening in a
new tab; rename, search and delete in the sidebar (confirm before delete); `web/src/lib/strings.js`
with `vi` and `en`, a switch in the nav stored in localStorage, default from the browser language;
title badge and a Notification when a reply lands while the tab is hidden.
**Files:** web/src/pages/Chat.jsx, web/src/App.jsx, web/src/pages/Login.jsx, web/src/pages/Gallery.jsx, web/src/components/*.jsx, web/src/lib/api.js, web/src/lib/strings.js
**Acceptance:** ui_smoke 25/25

### T5: The owner's residue script
`scripts/purge_test_residue.py <list.json> [--yes]`: dry run prints the counts and exits; `--yes`
deletes the listed threads with the measured PATCH and the listed memories with
`DELETE /backend-api/memories/<id>`, one request per second, printing each status, and stops on
the first 401. Never run by the agent with `--yes`.
**Files:** scripts/purge_test_residue.py
**Acceptance:** dry run on docs/agent/residue-to-delete-2026-09-24.json prints `127 threads, 2 memories, no request made`

### T6: Tier 1 review
Mutants: refill stacking (a second read on the same day raises quota again), delete without the
ownership clause, tombstone claimed twice, search without the user clause. Fixes, scoped re-review.
**Files:** whatever the review names, inside the radius
**Acceptance:** 0 blocking findings; every mutant went red

### T7: Full gate, real gate, evidence
**Files:** none new
**Acceptance:** the numbers in section 4; the real gate deletes one real thread and the worker
reports it

## Evidence

Accepted 2026-09-24 at HEAD 09d447c, clean tree. Fence audit: "base 0a229e9, 8 commit(s) from
base to HEAD, all changes since base are inside the blast radius". Commits: bbb40c0 (api: rename,
search, delete with media and tombstone, daily refill, admin usage), 56387b4 (worker: thread
deletion through tombstones), a27b5d1 (owner's residue script), 432aa07 (web: markdown, sidebar,
two languages, title badge), d6e8a8a (review fixes), ad70b18 (a cancelled turn's thread kept or
removed, a refused result's files dropped), a0eaee6 (Stop honoured before the job id is known,
the mock's slow picture), 09d447c (wait for a cancelled turn's address).

Full gate:

```
python acceptance.py                                28/28 PASSED, EXIT=0   health sha 09d447c
python acceptance.py --real                         25/25 PASSED, 3 skipped in this mode, EXIT=0   health sha 09d447c
~/cloakbrowser-env/bin/python tests/ui_smoke.py     25/25 PASSED, EXIT=0   (on the tree committed as a0eaee6; no web change since)
cd web && npm run build                             built in 1.22s, EXIT=0  (at a0eaee6; no web change since)
python scripts/purge_test_residue.py docs/agent/residue-to-delete-2026-09-24.json
                                                    127 threads, 2 memories / dry run: no request made
```

Section 4 promised 26/26 and 23/23 with 3 skips; the plan grew two checks during review (a live
job is cancelled and refunded when its conversation is deleted; a tombstone is handed out once per
attempt), so the final counts are 28/28 and 25/25 with the same 3 mock-only skips. ui_smoke 25/25
and the dry run line are as promised.

Red first: T1 acceptance 22/26 (`rename 405` and `q` ignored; `2 media gone False, files gone
False`, `threads deleted 0 -> 0`; `quota 88 -> 88` after the day change; `/admin/usage` 404) and
ui_smoke 18/25 (no switch, no `<strong>`, title unchanged, no rename, search or delete controls).
Every later clause was also watched red: the tombstone test read 2/5 before the rest between
attempts; the delete check stayed 26/26 under the ownership mutant until the other user's DELETE
was added (then `other user 204 still mine False`, 27/28); the file clause was vacuous until the
mock's slow picture (then the unlink mutant went red on `new files ['mock-ae669dfb...png']`); the
thread clause of the delete-while-running check read `threads deleted 1 -> 1` on the real provider
until the worker waited for the thread's address (a one-turn probe cancelled 1s after sending then
reported `https://chatgpt.com/c/6ab4c995-...` and deleted it).

Lines worth keeping from the real gate at 09d447c:

```
a conversation can be renamed and found by search       renamed, found by title and by 'Remember', other user sees 0 and gets 404
deleting a conversation removes its media files and the provider thread   other user 404 and nothing moved; owner 204; 3 media rows and files gone; provider threads deleted 0 -> 1; quota unchanged
deleting a conversation cancels its running job and refunds   job cancelled by the delete, credit returned, no media row or file written, the turn's own thread deleted 1 -> 2
quota refills once a day up to the cap                  89 -> 100 after the day changed, held at 100, 99 after one job
admin sees usage per user, others do not                14 jobs (12 done, 0 failed, 2 cancelled) and 1 images for the admin, other user 403
```

ui_smoke: markdown renders with `<strong>` and no raw `**` or `sandbox:`; the switch turns Send
into Gửi and New chat into Trò chuyện mới and back; `stop cancels a running job: bubble gone
within 6s, 0 reply bubble(s) appeared afterwards`; rename shows in the sidebar; search returns 1
hit for the title and 0 for nonsense; delete empties the sidebar and the gallery reads `Gallery (0)`;
a reply landing while `document.hidden` puts `(1)` in the title and the badge clears on return.

Review (tier 1): round 1 at 432aa07, 1 blocking (the delete check never tried the other user's
token) and 10 non-blocking; mutants M1 refill, M3 search, M5 admin red on the predicted checks, M2
delete ownership and M4 tombstone claimed twice stayed green (test gaps, both closed). Scoped
re-review at d6e8a8a: 0 blocking, M2 red (`other user 204 ... 27/28`), M4 red (`exit 1 2/5 PASSED`),
12 probe cases as expected, control 28/28. Light re-review at ad70b18: 0 blocking, the tombstone
mutant red (`threads deleted 1 -> 1`), control 28/28; its N1 and N2 closed in a0eaee6 with the
coordinator's own unlink mutant red; its N3 closed in 09d447c and proven by the real gate.

Deviations: two checks added during review (widening inside the radius, reported above); the
invariant in section 3 was changed by decision from "never refunds" to "cancels and refunds live
jobs"; the strings file is `web/src/lib/strings.jsx` (JSX needs the extension); ui_journey was not
rerun in this plan (the flows it covers changed only in the Stop path, which ui_smoke pins); the
real gate ran four times today (432aa07, d6e8a8a, ad70b18, 09d447c) and the first three each
found one thing the next commit fixed. The Stop defect it surfaced was real: the api log showed
zero cancel requests for a Stop pressed before the job id had arrived.

Left open, in HANDOFF: a cancel that lands while a brand new thread still has no address after
15s leaves that thread untracked; English error strings and worker phase names inside the
Vietnamese interface; `images` in usage counts pictures kept, not made; the unlink branch is
measured in mock mode only; the archive is built in memory; the owner's residue purge is the
owner's to run (in progress as this was written).
