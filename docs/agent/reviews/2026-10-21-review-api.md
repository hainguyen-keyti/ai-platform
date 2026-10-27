# Review of 2026-10-21: api (an independent read-only reviewer, HEAD 4cd26c8)

Nothing further is needed; the in-process run settled the open questions. Report follows.

# API review: `api/src/` and `acceptance.py` (read-only, 2026-10-21)

**Verdict: nothing blocking.** No cross-user leak, no double charge or double refund, no auth bypass found. Everything below was read in the implementation and, where marked "run", confirmed in-process against a temp database (`/tmp/aip-review/check.py`, venv python with `-B`, nothing written in the repo).

## Findings, most severe first

### Should fix

**1. A `done` result with no text and no media is charged and shows nothing.** `api/src/jobs.py:571-580` only writes a message when `(text or media)`; `jobs.py:600-610` then marks the job `done` and refunds only on `failed`. Run: posted `{"status":"done","text":"","media":[]}` → job `done`, conversation holds only the user's message, quota 100 → 99. Scenario: any driver that reads a reply before it paints (the Grok "empty turn" rule lives in the driver, DECISIONS 2026-09-25; ChatGPT and Gemini have no such guard in the api). This breaks the decided invariant "a job that produced nothing must not cost the user a credit" (DECISIONS 2026-09-23). Fix: in `record_result`, treat `done` with neither text nor media as `failed` with `error_kind="empty_reply"` and the usual refund (same transaction, same rowcount guard). Gate: post such a result for a claimed job, expect `failed` and the credit back.

**2. A running job whose worker died stays `running`, credit held, until some worker claims again.** `_sweep_stranded` (`jobs.py:176-201`) runs only inside `claim_next_job` (`jobs.py:312`); `get_job` (`jobs.py:649`) sweeps `pending` only. Run: claimed attempt 1, lease and ping an hour stale, three polls answered `running`, quota still 99; one claim from a grok worker then turned it `failed/no_worker` and refunded. On a VPS with one worker process, a worker crash leaves every in-flight job spinning in the web until the user cancels or the worker returns. Fix: in `get_job`, call `_sweep_stranded(conn)` (or a per-job variant) before `_sweep_unserved(conn, job_id)`: in one poll the job goes stranded → pending → `no_worker`, refunded. Gate: the gate already has `worker_ctl["stop"]` (`acceptance.py:2058`); "a stranded job is reclaimed" (`acceptance.py:1516-1536`) covers only the restart path.

**3. The first-admin rule races.** `api/src/routes/auth.py:33-52` reads `COUNT(*)` then inserts in autocommit, with the bcrypt hash (about 250 ms) computed between them. Run: two registrations at once on an empty database → `{1: (201, 'admin'), 2: (201, 'admin')}`. Only exploitable at deploy time (an empty users table), but the invite code is shared with the team and the fix is three lines: wrap the existence check, the count and the insert in `BEGIN IMMEDIATE`. The same wrap turns the duplicate-email TOCTOU (`IntegrityError` → 500) into the intended 409.

**4. The conversation zip is built whole in memory.** `api/src/routes/conversations.py:144-170` writes every file into a `BytesIO` and returns `buffer.getvalue()`. A conversation with Gemini videos (several MB each, `ZIP_STORED`) at a few hundred MB, requested by two or three people at once, can take the api container out; compose sets no memory limit. Fix: cap the total (`sum(st_size)`, 413 past a limit) or stream with `StreamingResponse` over a generator; `ZIP_STORED` makes streaming easy.

**5. Gate gaps on security and money behaviour** (all hold in the run, none pinned): logout revokes the session (`security.py:42-44`, 61); a wrong or missing worker token is 401 on `/internal/*` (`security.py:113-116`); a non-admin on `PUT /admin/users/{id}/quota` and `GET /admin/users` (`admin.py:11-20`, `66-68`); cancel on a finished job returns 200 and does not refund (`jobs.py:491-498`); a stranded job past `JOB_MAX_ATTEMPTS` fails as `stranded` with one refund (`jobs.py:189-195`); `DELETE /media/{id}` own and another's (`media.py:89-96`); a `/v1/images` body without a content-length (`v1.py:58-64`; the gate always declares a length) and a declared body over 16 MB refused unread (`v1.py:53-54`; measured by hand in 4cd26c8, not in the gate); token expiry (`TOKEN_TTL_HOURS`, no seam). The first four are one request each in the existing flow.

### Nice to have

**6. Tombstone claim fails open.** `api/src/tombstones.py:40-54`: an empty `providers` list drops the provider filter. Run: `POST /internal/tombstones/claim {}` → 200 with chatgpt's thread, while `POST /internal/jobs/claim {}` → 204 (`jobs.py:303-307` fails closed). Make it `if not serves: return None`.

**7. Dead columns.** `jobs.cancel_requested` is written (`jobs.py:42`, `493`) and never read anywhere (worker and web included; the heartbeat reads `status`). `sessions.expires_at` is written (`security.py:36`) and never read (expiry lives in the JWT); session rows are never purged, one per login forever. Drop `cancel_requested`; purge sessions on login or drop the column (note its format is `isoformat()` with `T`, not SQLite's).

**8. `client.py:33-49` migration loop is dead under the pre-launch stage** ("no migration ceremony"), and drifts from `schema.sql`: it adds `media.message_id` without the `REFERENCES ... ON DELETE SET NULL` (`schema.sql:51`) and `users.quota_daily DEFAULT 100` whatever `DEFAULT_QUOTA` is. Delete it or keep it in step.

**9. Indexes.** `idx_sessions_token` (`schema.sql:129`) duplicates the UNIQUE autoindex on `sessions.token` (`schema.sql:18`). Missing: `jobs(conversation_id)` for `cancel_open_jobs` (`jobs.py:35-39`) and `media(conversation_id)` for `get_conversation`, the zip and the delete (`conversations.py:70-75`, `136-142`, `192-198`): full scans, harmless at team size.

**10. Session tokens stored in plaintext** (`security.py:36`, lookup `:61`) while api keys are hashed (`:92`). A copy of `app.db` is a set of live logins for up to 24 h. Store `sha256(token)` and look up by hash.

**11. Orphan thread on a stale attempt's late result.** `jobs.py:543-558` (the cancelled/failed branch) ignores `attempt` and, when the conversation already holds a different thread, drops the reported one with no tombstone. Scenario: attempt 1 reclaimed, attempt 2 opens thread T2 and the job is cancelled, attempt 1 then reports T1: T1 stays in the shared account's library untracked. Add `elif conv["provider_thread_url"] != thread_url: leave_tombstone(...)`.

**12. `get_job` sweeps before it checks ownership** (`jobs.py:649` vs `:653`): any user polling another's job id runs its sweep under a write lock. Benign outcome, wrong order.

**13. `require_admin` after body validation** (`admin.py:67-68`): a non-admin gets 422 on a malformed body before 403. Make it a dependency.

**14. `/conversations` has no offset** (`conversations.py:26-29`): the list stops at 200 and `rename` does not bump `updated_at`. Fine for a team; say so in the docs.

**15. Weaker than its name:** "a job settles exactly once" (`acceptance.py:1473-1492`) posts only a forged attempt number on a running job. A repeat of the same attempt after settlement and a second `failed` (the double refund path) are never posted. Run: second post 409, quota unchanged. Add the two posts or rename the check.

## Gate coverage, briefly

Pinned well: register/invite, login, bad token, all three job kinds, media and conversation ownership (list, get, rename, search, zip, delete, all 404 for a stranger), thread reuse and isolation, delete cancels and refunds with the thread accounted for, tombstones (unit test, 5 checks), stale attempt 409, provider error refund, stranded reclaim after a restart, running cancel refund, daily refill, admin usage and 403, no-worker fail/refund, 503 uncharged with 404/409 ordered first, one provider per conversation, hold start/propagation/end, memory-on refund, api keys (shown once, hash, scope, revoke, cap of ten), every `/v1` refusal with files and credits unchanged, `/v1` ownership, `/v1` refund once, the example script.

Not pinned: items 5 and 15 above, plus duplicate email 409 and wrong password 401 (run: both hold), `phase` ever appearing in `/jobs/{id}`, `/conversations` and `/media` pagination bounds.

## Deployment readiness (what breaks first on a small VPS)

1. `docker-compose.yml:26` bakes `VITE_API_URL: http://localhost:3000` into the browser bundle: every teammate's browser would call its own machine. Needs the domain (open decision 2) and a reverse proxy with TLS; `docker-compose.yml:8` and `:24` publish the api and web on all interfaces in plain HTTP.
2. `docker-compose.yml:6` runs uvicorn with `--reload` on a bind mount; production should use the image's own CMD (`api/Dockerfile:11`). Keep one process: SQLite plus `BEGIN IMMEDIATE` is right single-process, and `init_db`'s ALTER loop would race under `--workers`.
3. No rate limit anywhere: `/auth/login` (`auth.py:56-63`) runs bcrypt per attempt on a 40-thread pool, so one client can pin the CPU; limit at the proxy.
4. Register the owner before sharing the invite code (finding 3).
5. No backup of `storage/db/app.db` (WAL: use `sqlite3 .backup`), and media grows without bound (uploads up to 10 MB per credit, generated pictures never expire).
6. Knobs (`TOKEN_TTL_HOURS`, `NO_WORKER_SECONDS`, ...) are not passed by compose (`docker-compose.yml:9-14`): defaults apply, which is fine, but nothing in the file says so.

## Known-open items, confirmed

JSON routes still read the whole body before login: `RequestLimit` matches only `/v1/images` (`v1.py:45`), nothing else caps a body. A picture sent with a `/v1` request that later fails stays on the message: the media row is written in `create_job` (`jobs.py:280-287`) and `record_result` never removes it. A stolen login can mint a key: by decision (DECISIONS 2026-10-09).

## What holds

- Credits: charged once under `BEGIN IMMEDIATE` with the balance re-read (`jobs.py:82-86`, `155-158`); every refund path is guarded by a status check or a rowcount (`jobs.py:189-195`, `233-240`, `277-284`, `463-473`, `491-498`); `_hold` runs after the job's own update so it never refunds that job again (`jobs.py:600-612`). Run: failed result twice → 200 then 409, cancel after → 200, balance back exactly +1.
- Settle once: `_live_attempt` (`jobs.py:345-359`) plus `AND status='running' AND attempts=?` on the update (`:466`).
- Ownership: every user route filters by `user_id` in SQL and answers 404 for another's resource (`conversations.py:59`, `101`, `131-138`, `187`; `media.py:42`; `jobs.py:488`, `516`, `625`; `auth.py:88`, `108`, `118`; `v1.py:113-118`, `165`, `194-197`); admin routes 403. A key opens only `/v1` (`security.py:89`) and a JWT never passes there; a request's files are limited to its own result list (`v1.py:194`).
- Auth: HS256 pinned (`security.py:57`), `exp` verified by PyJWT, session row required (`:61`), logout deletes it (run: 401 "session revoked"), worker token and invite code compared in constant time (`security.py:114`, `auth.py:29`), bcrypt's 72-byte cap enforced by the model (`models.py:10`).
- Paths: `_safe_path` (`media.py:48-53`) accepts only a bare name; the worker prefixes every provider-offered name with its own uuid (`worker/src/providers/chatgpt.py:685`, `771`); `_entry_name` (`conversations.py:109-116`) keeps `..`, backslashes and control characters out of zip entries.
- `/v1/images` limit: declared over 16 MB refused unread, 10.25 MB drained then 413, a chunked body with no length 413 (run), and the 413 carries CORS headers because the exception is converted inside the CORS layer (run: `ACAO *`).
- Transactions: every multi-statement write is under `BEGIN IMMEDIATE` with a rollback path (`jobs.py`, `tombstones.py`, `conversations.py:182-209`, `auth.py:86-101`); `foreign_keys=ON` per connection (`client.py:16`) so the cascades run; `get_job`'s sweep failure is swallowed on purpose and the read still answers.
- Time: every stamp is SQLite UTC `datetime('now')` compared in one format; `CLOCK_OFFSET_SECONDS` touches only the refill day (`quota.py:8`); the worker heartbeats every 5 s against a 420 s lease (`worker/src/runner.py:16`, `103`).
- SQL: all parameterised; the only formatted fragments are column lists and `?` placeholders; LIKE terms escaped (`conversations.py:21-23`). Error details carry no paths or SQL; FastAPI's default 500 is bare.
