# Review of 2026-10-21: records-vs-code (an independent read-only reviewer, HEAD 4cd26c8)

## Audit of the project records against the code at HEAD `4cd26c8` (clean tree, `origin/master` at the same sha)

Scope and method: read in full PROJECT.md, HANDOFF.md, DECISIONS.md, LESSONS.md, ACCESS.md, the repo CLAUDE.md, docker-compose.yml, scripts/run-worker.sh, both config.py files, `.env.example`, the 18 plans from 2026-09-29 on, the residue note; then the whole api, worker and web sources, and targeted reads of acceptance.py, the tests and scripts. Read-only; nothing in the repo touched; no gate run; no provider site contacted. Local GETs to `localhost:8000/health`, `:3000/health`, `:5173/` only. `.env` was not read (its size and mtime come from `stat`).

Runtime facts at audit time (2026-10-21 ~19:00): a host worker is running in **mock** mode at `4cd26c8`, started 18:54:07 today (pid 66195), serving all three providers; the api and web containers are up ("Up 2 weeks"); no `.claude/active-plan` marker.

---

### 1. Drift list (records the code or repo no longer matches), most misleading first

1. **PROJECT.md:23 "API (Hono/TS)"**: the api is Python FastAPI (`api/src/main.py:16`), decided on 2026-09-23 (DECISIONS.md:19). The one-screen architecture is wrong on its central box.
2. **HANDOFF.md:112 "Twenty-six plans finished and one set aside"** and the list at 113-139 (27 entries): `docs/agent/plans/` holds 29 files. Missing from the list: `2026-10-08-gemini-failure-sentence.md` (closed 63ec5dd) and `2026-10-09-chatgpt-image-api.md` (closed 4cd26c8). Should read 28 finished, one set aside.
3. **HANDOFF.md:141-146 "Latest evidence"** opens with the unread-thread plan (gate 44/44, ui_smoke 57/57, composer 49/49, gemini driver 136/136) and HANDOFF.md:76-77 says "The gate has 43 checks". Current: the gate has **54** checks (`acceptance.py:39`, the `CHECKS` tuple, 54 entries), ui_smoke 59/59, composer 51/51, gemini driver 143/143 (HANDOFF.md:395-413 and the image API plan's Evidence). The two newest plans' evidence sits only in the first paragraph and under "Active plan".
4. **HANDOFF.md:17-23**: "the host worker serves chatgpt,grok,gemini in real mode at 4cd26c8 since 2026-10-09 08:55". Today it runs in mock mode (`/health`: `"mode":"mock"`), started at 18:54 today, presumably for the owner's gate. Lines 19 and 22 also name two different log files (`host-worker-real-89.log` vs `-81.log`); both are gone from `/tmp` (see section 4).
5. **HANDOFF.md:276 "`acceptance.py:1311-1316`"** for the "stack did not start" table: that line is now `acceptance.py:2104`.
6. **CLAUDE.md:15 "Run: docker compose up -d && ./scripts/run-worker.sh"** starts a worker that serves ChatGPT only: `worker/src/config.py:24` defaults `PROVIDERS` to `chatgpt`, run-worker.sh sets nothing, and `.env` (232 bytes, last modified 2026-09-23 12:18) predates `.env.example`'s `PROVIDERS`, pacing and hold lines (added 2026-10-01), consistent with the running worker reporting `min_gap 0.0` for every provider. HANDOFF.md:242 passes `PROVIDERS=chatgpt,grok,gemini` by hand for this reason. The documented Run line contradicts DECISIONS.md:53 (the host worker serves all three).
7. **CLAUDE.md:20 "Provider smoke: python acceptance.py --real"** omits `--keep`, which CLAUDE.md:60-62's own rule requires for every real gate, and `--provider` (`acceptance.py:1962-1966`); CLAUDE.md:26 "drives an actual ChatGPT session" is now any of the three. HANDOFF.md:189 has the right line.
8. **CLAUDE.md:55 "Media files go to R2-compatible storage (local in dev, Cloudflare R2 in prod)"**: no R2 code exists; media is a local directory served by `FileResponse` (`api/src/routes/media.py:48-53, 76-86`), DECISIONS.md:28 forbids a storage abstraction while there is one backend, and DECISIONS.md:97 defers R2. A working rule that describes a plan.
9. **ACCESS.md:62 "Still to ask it: 'Tôi tên gì?'"**: asked on 2026-10-02 at 02:06 on the new account, answered "Bạn tên là Keyti." (HANDOFF.md:42-43, 361-366).
10. **ACCESS.md:53 "Old state files | storage/sessions/<provider>.json | ... Grok's still holds a live login"**: `residue-left-in-accounts.md:93-95` says the three files went to the Trash on 2026-10-01 23:00. Not verifiable here (`storage/` is off limits; `~/.Trash` lists no `ai-platform-old-session*`, which is either the Trash emptied or the Trash unreadable to this process).
11. **ACCESS.md:47-53 "Where secrets live"** lacks the secret kinds added since: personal API keys (`api/src/db/schema.sql:116-125`, SHA-256 only, shown once by `api/src/routes/auth.py:82-102`), login JWTs in `sessions` (`schema.sql:15-21`), and the invite code appears only in the Quick checks (ACCESS.md:104).
12. **DECISIONS.md section 1 keeps two superseded rows unmarked**: DECISIONS.md:22 "Every job starts a fresh ChatGPT chat, our own history is replayed" is reversed by DECISIONS.md:26 (one thread per conversation; code: `worker/src/providers/chatgpt.py:825-828`, history replayed only without a thread at `:935-948`); DECISIONS.md:15 "Hybrid architecture: Cloudflare (web/API) + VPS" is undone for the API half by DECISIONS.md:19 ("the browser worker cannot run there anyway", FastAPI). The ChatGPT driver's own docstring still states the old rule (`chatgpt.py:262-266`).
13. **PROJECT.md:42 "Local | Yes | docker compose up"**: the local environment is compose plus the host worker (DECISIONS.md:20; CLAUDE.md:15).
14. **HANDOFF.md:244 "The mock one for ui_smoke serves only `chatgpt`"**: a habit, not a rule; the mock worker running now serves all three.
15. **`.env.example:29 NO_WORKER_SECONDS=180`** is below the floor the api enforces (`api/src/config.py:38-39`, 310), so the documented value is never the effective one; and none of `.env.example`'s api variables reach the Docker api at all (section 4).

Fine as written: HANDOFF's "Where we are" (86-110) matches the drivers (ChatGPT stop press `chatgpt.py:886-889`; Gemini's two switches `gemini.py:120-121, 260-287`; video wait `gemini.py:46`; the unread-thread refusal `chatgpt.py:540-564`); HANDOFF's verify commands (187-191) all exist with those flags; HANDOFF.md:280 "about 310 seconds" matches `config.py:38-39`; ACCESS.md's cookie names and proofs match `scripts/login_provider.py:31-51`; ACCESS.md:74-77 matches `chatgpt.py:195-206, 468-504`; ACCESS.md:100-101 `/admin/usage` exists (`admin.py:23`); CLAUDE.md:29-31 on the site probe matches `tests/provider_probe.py:881-890`; CLAUDE.md:34-35 matches `tests/ui_smoke.py:8`.

---

### 2. Open-items ledger

**A. Already fixed by a later commit**

- first-open plan (3e32a12), "a job cancelled during a slow open still sends": fixed by 4536183, `chatgpt.py:843` and `:856` (`_stop_unsent` before the attach and before the send). The open itself still runs to its end before noticing (time only).
- mobile-layout plan (ab8e210) left-open: phone Back (a8b5302, `Chat.jsx:189-200`), reply blank lines (bbb3924, `Chat.jsx:34`), slate-400 contrast (a8b5302, `index.css:6-11`), empty list's blank panel (a8b5302, `Chat.jsx:411-415`), gallery file card (bbb3924, `FileCard.jsx:38`).
- busy-runner plan (34b533c) note "the deletion checks read the worker's total count": fixed by 89e8beb (gate-checks plan).
- picture-wait plan (d2d346d), "`_baseline_ids` returns nothing on a failed read": fixed by 508c748, `chatgpt.py:540-564`.
- gemini-video plan (c691726), "an intermittent console error": fixed by 508c748, `MediaVideo.jsx:25-34`; "Add files" placeholder: fixed by c691726, `gemini.py:38-39, 350-367`.
- hold-and-stop plan's two real ChatGPT lines: the stop probe ran 2026-10-02 17:39 (the plan's addendum, three turns, stop pressed), and the real gate's deletion check passed on the unsent word at b589041.

**B. Closed by a decision (moot)**

- failure-sentence plan, "the cooldown after such a failure": DECISIONS.md:80 keeps it.
- image API plan, "a stolen 24 hour login can make a key": DECISIONS.md:82, as is.
- saved-info plan (7), "`goto` with its defaults": the driver already uses `domcontentloaded` and 60s (`gemini.py:231`); a test-gap note only.
- hold plan (7), the `_held` branch only changes the 503's words: by design (`jobs.py:116-126`).

**C. Still open in the code, ranked by what it can cost**

Tier 1, a wrong answer or one user's data reaching another:
1. **A picture attached in ChatGPT's shared composer survives a job taken away after the attach** (image API plan; HANDOFF.md:304-306; hold plan (3)): `chatgpt.py:844` attaches, `:856` is the last `_stop_unsent`, and no path clears the composer on the unsent or raised path; the next turn's `_open` reloads the page (`:349, :382`), whether ChatGPT keeps a draft attachment across that is the unmeasured half. Offline: the fake page can show it stays attached; whether the real site re-sends it needs a read-only probe with ChatGPT off the worker. Highest cost: one person's upload in another person's turn, now a routine path through `/v1/images`.
2. **Nodes an earlier ChatGPT turn still writes after the read before the send** (one that hit the 300s ceiling, a stop that did not press) are taken for this turn's (unread-thread plan; picture-wait plan; HANDOFF.md:310-313): `chatgpt.py:625-628` filters by baseline ids only; the clock guard at `:637` covers pictures, not words. A previous answer returned and charged. Measurable offline on the fake page in `tests/test_chatgpt_composer.py`.
3. **"Tôi tên gì?" answers "Bạn tên là Keyti."** on the shared ChatGPT account (HANDOFF.md:361-366; ACCESS.md:62 stale): the account's identity reaches every user. Owner's call; real site only.
4. **Gemini guard fails open on the driver's own errors** (saved-info plan (1), (2)): `gemini.py:257-258` turns any exception into `unknown`, which does not block; `self.memory` is reset only inside `_guard` (`:265`), so a turn that dies in `_open` (`:413`) leaves the earlier look in health. Low probability, cross-user cost. Measurable offline (unit tests).
5. **`provider_error` texts reach the person verbatim**, including admin instructions and the machine's path (hold plan (5); one-profile (5)): `Chat.jsx:315-317` shows `err.message` for anything but 503 or `provider_misconfigured`; the texts come from `chatgpt.py:483-484, 494-495` and `pool.py:148-153` with `session.py:18` (`no saved session at <host path>`). Measurable offline (ui_smoke can play the job). Cost: confusion and a filesystem path shown to team users.

Tier 2, lost credits or a broken feature:
6. **The web offers "Video script" under a Grok picture and the api accepts it**: `Chat.jsx:40-55, 351-354` send `/video/script` for any provider, `jobs.py:70-173` checks no feature per provider, the worker refuses it as `worker_error` (`pool.py:154-158`, `grok.py:538-540`) after the charge, then refunds (`jobs.py:472-473`); the English internal text shows in the header. Not in any left-open list; the served-providers plan deferred "features per provider". Offline.
7. **Grok and Gemini send a turn stopped before its send and never press their stop** (hold plan (6); HANDOFF.md:341-343): `grok.py:452` and `gemini.py:472, 600` check for a stop only after the send. A cancelled turn still spends the account's turn and lands a thread. Offline (fake pages).
8. **A picture sent with a `/v1` request that fails or is cancelled stays kept on the person's message** (image API plan): `jobs.py:143-150` inserts it before the job; nothing removes it on failure. Low, storage and gallery clutter.
9. **A stranded job requeued while its provider is held is claimed once** (hold plan (1)): `jobs.py:301-342` never reads `provider_holds`; `_hold` (`:220-240`) fails only jobs pending at that instant. Credits stay right; the hold is pushed out again. Low.
10. **`PROVIDER_HOLD_SECONDS=0` sets no hold yet fails the waiting jobs; a negative value makes `record_result` raise** (hold plan (2)): `config.py:42` validates nothing; `jobs.py:226-240`. Low (defaults only, and the variable never reaches the Docker api anyway).

Tier 3, a stuck worker:
11. **A driver never recovers from a dead browser until the worker restarts** (one-profile (3)): `chatgpt.py:301-306`, `gemini.py:194-199`, `grok.py:132-137` hand the cached page back forever; every job then fails as `worker_error` (refunded) while heartbeats and pings keep the provider served. `pool.stop()` closes browsers from the lifespan thread, not the runner's (`pool.py:111-117`, one-profile (2)). Offline-measurable (the reviewer's repro is gone, see section 4).
12. **A heartbeat answered with anything but 200 neither pings nor sets lost, and a driver hung inside Playwright keeps its lease renewed and its provider served** (busy-runner notes; HANDOFF.md:377-378): `runner.py:141-154`; `jobs.py:362-384`. Offline.
13. **Every JSON route reads its whole body before the login is checked** (image API plan; HANDOFF.md:307-309): `main.py:31` adds `RequestLimit`, which guards `/v1/images` only (`v1.py:45`); a 200 MB POST to `/chat` took the api to 580 MB (the plan's measurement). Offline. Team-only today.
14. **The served window is pinned only against a wider one; a turn in the first second after a worker's start is refused until its first claim; the 60s refresh is unpinned** (served-providers plan; HANDOFF.md:367-370): `jobs.py:243-251`; `runner.py:85`; `Chat.jsx:161-172`. Low; a throwaway-database test would close the first.
15. **The whole archive is built in memory** (HANDOFF.md:329): `conversations.py:144-170`. Fine for a team.
16. **A refused result's files are removed, measured in mock only** (HANDOFF.md:330): `runner.py:216-226`.

Tier 4, UI polish, all offline-measurable with ui_smoke:
17. Reload with the phone's list open leaves a dead Back step: `Chat.jsx:198` pops only in the effect's cleanup, nothing at mount reads `history.state`. Forward after Back, and a reopen within 100ms, same root (ui-polish (1)-(3)).
18. The list can answer an older search than the box shows: `Chat.jsx:273-282` has no sequencing (ui-polish (4)).
19. The gallery says "Nothing generated yet." before it has loaded: `Gallery.jsx:41` tests `items.length` with no loaded flag.
20. Back leaves the app while the Lightbox is open: `Lightbox.jsx:7-13`, no history step.
21. Phone nav tap targets small (`App.jsx:34-39`), 26px targets app-wide; the composer placeholder cut at 390px (`Chat.jsx:539`); the header title squeezed while unserved (`Chat.jsx:459-461`); nav breakpoint 640 (`App.jsx:33, 42`) against the chat's 768 (`Chat.jsx:393`); gallery tiles' footers; a video fetched whole before its player shows (`MediaVideo.jsx:15`, `api.js:65-71`).
22. `tests/test_runner_tombstones.py:73` still carries the stale "No join()" comment (`runner.py:36-37` names the event `_halt`).
23. `tests/gemini_probe.py:515` still opens a row's menu by `hover` (HANDOFF.md:373-374); fails safe.
24. Session plan's small ones: `session.py:50` `int()` outside the `try` (a 4301-digit seed raises its own error); `login_provider.py:106` matches a cookie's domain by substring; the `create=True` source check is a text match (`tests/test_session_profile.py:408`); lock wording measured on macOS only (`session.py:74`).

**D. Open, not knowable without the real site**

- Whether the three profiles still answer after twelve idle days, and why sessions died before (one-profile plan "Left open", the lead unproven). ChatGPT's Cloudflare state (it came on the pinned device, 2026-10-01 21:51 and 2026-10-07 01:54). Google's unusual-traffic state. Grok's free-tier wall (`/rest/rate-limits` never decrements; the page is the only reading) and whether a paid tier is wanted (owner's call). Grok's upload flow (why video script is unsupported, `grok.py:106-108`).
- Gemini: the pending state's own markup, the daily video allowance's wording, a turn that writes and makes a video at once, a Vietnamese failure sentence (only one English sentence is known, `gemini.py:118`), two Google accounts in one profile (`/u/1/` reads `unknown`), the stray "JPG" and "2" lines after a video script, the 2026-09-27 plan's points (row label on an empty title, first stream only, a quota wall as a reply, multi-picture turns).
- ChatGPT: a caption more than 10s after its picture with no stop button; a picture node without `create_time` (`chatgpt.py:637`, runs to the ceiling); why the picture of 04:46 was not on the page at 300s; whether a turn stopped before any word leaves a conversation in the account.
- The Grok real gate rerun (HANDOFF next step 5) and the real `/tmp/cold_delete_probe.py` after-count (delete-token plan, declined).

---

### 3. Decisions compliance (DECISIONS.md section 1, checkable rows)

- 2026-09-23 cloakbrowser, no provider API keys: **holds** (`session.py:62, 71`; the three drivers import nothing else).
- Platform credentials, shared accounts, per-user quota: **holds** (`auth.py:40-50`, `quota.py`).
- Hybrid Cloudflare + VPS: **superseded** for the API by the FastAPI row; not checkable beyond that (no staging or production exists, PROJECT.md:40-44).
- Docker Compose: **holds**.
- SQLite + local storage: **holds** (`db/client.py:12`).
- Monolith + plugin mindset: **not checkable**.
- API in Python (FastAPI): **holds**; PROJECT.md:23 violates the doc, not the code.
- Worker on the host, api and web in Docker: **holds** (compose has two services; `run-worker.sh`).
- Worker holds no database handle: **holds** (no `sqlite` in `worker/src`; `runner.py` speaks HTTP only).
- Every job a fresh ChatGPT chat with replayed history: **superseded** by the one-thread row; code follows the later row (`chatgpt.py:828, 940-948`).
- Acceptance fakes only the provider boundary: **holds** (`pool.py:14-16`; the gate starts a real api and worker, `acceptance.py:1997-2031`).
- Quota refunded on failure: **holds** (`jobs.py:472-473`, `:195`, `:240`, `:284`, `:498`).
- Full gate includes a real-browser UI test: **holds** (CLAUDE.md:19).
- One ChatGPT thread per conversation: **holds** (`schema.sql:23-34`; `jobs.py:426-430`; `chatgpt.py:345-378`).
- Media bytes downloaded inside the session, never links: **holds** (`chatgpt.py:783-801`; `gemini.py:544, 633`; `grok.py:405`).
- No storage abstraction: **holds**.
- A turn is over when the server says so: **holds** (`chatgpt.py:572-647`; `grok.py:333-359`; `gemini.py:470-512`).
- Leases, settle once per attempt, cancellable, one charge one refund: **holds** (`jobs.py:301-342, 345-359, 396-480`; `models.py:46-55`).
- Exponential cooldown, minimum gap, rolling image budget: **holds in code** (`pool.py:45-74`; `config.py:19-22`) but **the minimum gap is off in the running configuration**: `/health` reports `min_gap 0.0` for all three providers and the per-provider table; `.env.example:39` documents 3 and `:47` Grok's 150, and `.env` predates both lines. The decision's "minimum gap" is not in effect.
- A stored thread that fails to open is a provider error unless 404: **holds** (`chatgpt.py:360-378`; `grok.py:240-252`; `gemini.py:306-310`).
- ToS posture; "owner's call" items; Grok's "Improve the Model"; Gemini on the owner's account with retention on; Gemini and Grok account switches; the Grok plan's closing order; the composer plan widened; one plan for Gemini's two faults; the saved-info switch on for ten seconds: **not checkable in code** (account state or process).
- Memory guard: refuse while on, `provider_misconfigured` refunded, unknown does not block, missing token blocks, 401 replaced once: **holds** (`chatgpt.py:468-504, 832-833`).
- Packaging media is the platform's job: **holds** (`conversations.py:119-170`).
- react-markdown with `sandbox:` as text: **holds** (`Chat.jsx:2, 19-29, 35`).
- Daily refill to a cap, usage from the jobs table: **holds** (`quota.py:12-26`; `security.py:67`; `admin.py:23-63`).
- Delete removes media rows and files at once, thread through a tombstone: **holds** (`conversations.py:173-215`).
- Vietnamese and English, default from the browser, stored locally: **holds** (`strings.jsx:147-164`).
- Delete cancels and refunds live jobs; a failed deletion rests 10 minutes, three attempts: **holds** (`jobs.py:28-48`; `tombstones.py:8-9, 74-96`).
- One runner, browser and pacing per provider; claims and tombstones filtered; a foreign job refused: **holds** (`worker/src/main.py:32`; `runner.py:164-175`; `jobs.py:314-316`; `tombstones.py:52-54`).
- `no_worker` floored at two heartbeat intervals plus 30s; busy workers ping: **holds** (`config.py:38-39`; `runner.py:67-75, 156-162`; `jobs.py:376-379`).
- One conversation one provider, 409, selector locked: **holds** (`jobs.py:99-104`; `Chat.jsx:463`).
- Grok typed and Enter, settled by `/responses` with words or a picture: **holds** (`grok.py:281-322, 333-359, 501-505`).
- Grok chat and image only, video script refused: **holds at the worker** (`grok.py:108, 538-540`) but refused after the charge, and the web offers the button (ledger C6): **partial**.
- Thread deletion in a pacing gap, never in an error cooldown: **holds** (`runner.py:76-79`).
- Gemini reads personal context before every turn: **holds** (`gemini.py:120-121, 269`).
- Grok's memory read before every turn: **holds** (`grok.py:149-166, 436-437`).
- Host worker serves Gemini (`PROVIDERS=chatgpt,grok,gemini`): **holds only by the start line**; nothing in code or `.env` names the three (drift 6).
- Reply line breaks, 8px blocks, file card up to 256px: **holds** (`Chat.jsx:34`; `FileCard.jsx:38`).
- Chat view follows the tail by intent: **holds** (`Chat.jsx:145-153, 265-271`).
- Phone layout round: 16px fields, brand hidden below 640, "còn N", the group wraps: **holds** (`Chat.jsx:407, 429, 465, 540`; `App.jsx:33, 40`; `strings.jsx:81`).
- UI polish: history step, empty notes, select named, WCAG AA: **holds** (`Chat.jsx:189-200, 411-415, 463`; `index.css:6-11`); contrast not re-measured here.
- 2026-10-01 hold for 10 minutes, 503 uncharged, waiting jobs refunded, notice not admin text, ChatGPT logged-out stays `provider_error`, cancel within 5s, ChatGPT stop: **holds** (`config.py:42`; `jobs.py:116-126, 213-251, 474-475`; `Chat.jsx:315-317`; `runner.py:16, 142`; `chatgpt.py:483-484, 856, 886-889`), with the known gap that `provider_error` texts show (ledger C5).
- Grok signed out only on 401 or 403: **holds** (`grok.py:209-220`).
- Login script takes a chunked cookie: **holds** (`login_provider.py:83-89`).
- One profile and one seed per provider; only the login creates; drivers refuse a missing one; ChatGPT's proof: **holds** (`session.py:23-78`; `chatgpt.py:287-291`; `login_provider.py:35`).
- Private repo, branch master, pushed: **holds** (`origin/master` = HEAD); note the agent layer is excluded from git (section 4).
- Saved-info guard: both pages, on at once, off after two polls, site host only, signed-out rule, `memory` off only when both off, nothing kept between turns: **holds** (`gemini.py:220-287`) with the fail-open `except` (ledger C4).
- Push on its own after a green full gate: **holds** (CLAUDE.md:40-41; the tree and origin agree).
- The gate's rule for a turn taken away: **holds** (`acceptance.py:219-245`, `ACCOUNTED_ROWS` 21, `OWED_ROWS` 10).
- ChatGPT picture rule, 10s quiet, server clock, 30s paint, ceiling 300: **holds** (`chatgpt.py:31, 55-61, 566-570, 637-641, 876-881`).
- Host worker in a Terminal tab, no launchd: **not checkable in code**; a worker is running.
- Gemini video: note without `message-content` waited up to 300s, https from `contribution.usercontent.google.com`, `ftyp`, type `video`, served `video/mp4`, played with Download, real upload button waited 15s, "Add files" never pressed: **holds** (`gemini.py:38-46, 350-367, 561-569, 590-644`; `media.py:18`; `MediaVideo.jsx:52-62`).
- The replaced "Add files" check: **holds per the plan's Evidence**; `tests/test_gemini_driver.py` not re-read.
- Follow-up thread read until 200, three tries, before the attach, fails refunded: **holds** (`chatgpt.py:69-70, 540-564, 837-838`).
- Player released before its blob is revoked: **holds** (`MediaVideo.jsx:25-34`).
- Failure sentence fails as `provider_error` with its thread; one English sentence: **holds** (`gemini.py:117-118, 576-580`).
- `SLOW_SMOOTH` holds its progress at 0 or above: **holds** (`tests/ui_smoke.py:82`).
- The pause after a failure-sentence failure stays: **holds** (`pool.py:48-55`, no exemption).
- Image API: `/v1/images`, id at once, prompt required, one PNG/JPEG/WEBP, personal key, key only on `/v1/images`, JWT refused there: **holds** (`v1.py:16, 122-202`; `security.py:85-104`; `auth.py:81-121`; `main.py:28-31`).
- No password to make a key: **holds** (`auth.py:82-102`).

---

### 4. Environment drift

1. **Every record the plans and HANDOFF point to outside the repo is gone.** All 14 `/tmp` paths checked are missing (`stop_probe.py`, `picture_settle_probe.py`, `gemini_video_watch.py`, `real_video_walk.py`, `manual-test-account.json`, both host worker logs, `run_api_mutants.py`, `earlier_answer_repro.py`, `gemini_guard_probe.py`, `cold_delete_probe.py`, `/tmp/e2e_acceptance`, `/tmp/rv_gsi`, `/tmp/rv_exp`); only five scripts written today remain. The seven kept gate workspaces under `$TMPDIR` (`ai-platform-acceptance-ou5249ge` and the rest) are empty shells: 0 files each, only `db/` and `media/` left; their mtimes (03:35 on 10-05, 10-06, 10-12) are the OS temp cleaner, which removes files unused for three days. So the real gate's own records (HANDOFF.md:172, the b589041 log and db) no longer exist; the plans' Evidence text is the only evidence. The repo rule "run real gates with `--keep` and read the worker's error" (CLAUDE.md:60-62) keeps records for at most three days unless they are copied out of `$TMPDIR`. Lesson-grade; not yet in LESSONS.md.
2. **Python venv** (`~/cloakbrowser-env`, Python 3.10.14): every pin matches what is installed: fastapi 0.115.6, uvicorn 0.34.0, httpx 0.28.1 (`worker/requirements.txt`), pydantic 2.10.4, PyJWT 2.10.1, bcrypt 4.2.1, python-multipart 0.0.20 (`api/requirements.txt`, the gate runs the api under this venv), starlette 0.41.3 inside fastapi's range. `run-worker.sh:28` reinstalls the worker pins at every start. Fine.
3. **cloakbrowser 0.5.10** (installed 2026-09-20) with playwright 1.63.0, **not pinned** anywhere (`worker/requirements.txt:2` says so on purpose; the one-profile plan assumed 0.5.10 stays). Its Chromium is `~/.cloakbrowser/chromium-145.0.7632.109.2` (cached 2026-09-08). At every launch it checks GitHub for a newer Chromium and downloads it in the background unless `CLOAKBROWSER_AUTO_UPDATE=false` (`cloakbrowser/download.py:1152, 1251-1270`), and warns about a newer wrapper from PyPI (`:1230-1248`). The repo sets neither (git grep: none); `.last_update_check` was rewritten today 18:54; one chromium dir exists, so no new build has been pulled yet, but the device seed pins the fingerprint, not the browser build (one-profile left-open 6). A build change under the pinned seed is the one thing that can silently change what the sites see.
4. **Node**: host node v22.23.0, npm 10.9.8; `web/package-lock.json` (lockfileVersion 3) resolves react 18.3.1, react-dom 18.3.1, react-markdown 10.1.0, vite 6.4.3, @vitejs/plugin-react 4.7.0, tailwindcss 3.4.19, postcss 8.5.28, autoprefixer 10.6.1; the host `node_modules` (2026-09-24) match the lockfile, which is what the full gate's `npm run build` uses. **`web/Dockerfile:5-6` copies `package.json` only and runs `npm install`, never the lockfile**, so the container resolves its own versions; and the web image was built 2026-09-23 05:31 UTC, before `package.json` and the lock changed on 2026-09-24 (432aa07, react-markdown), so the image lacks react-markdown: the running container works only through the hand-run `npm install` in its anonymous volume (HANDOFF.md:281-282). `docker compose build`, `down -v` or a new machine loses that. The api image (2026-09-23) still matches `api/requirements.txt` (last changed 2026-09-23, e67b9dc); containers created 2026-09-25, started 2026-10-02 10:36 UTC; the api serves the current source through the bind mount with `--reload` (`docker-compose.yml:6, 16`).
5. **Compose variables**: the api reads twelve (`api/src/config.py:15-42`); compose passes five (`docker-compose.yml:10-14`: DB_PATH, MEDIA_PATH, JWT_SECRET, INVITE_CODE, WORKER_TOKEN). `TOKEN_TTL_HOURS`, `DEFAULT_QUOTA`, `JOB_LEASE_SECONDS`, `JOB_MAX_ATTEMPTS`, `CLOCK_OFFSET_SECONDS`, `NO_WORKER_SECONDS`, `PROVIDER_HOLD_SECONDS` never reach the Docker api, although `.env.example:29, 34, 53-54, 59-60` documents them as if they did (the known `PROVIDER_HOLD_SECONDS` point, wider than recorded). Harmless today because the defaults equal the documented values (24, 100, 420, 3, 0, 310, 600); a future edit of `.env` would silently not apply. The worker gets all of its variables through `run-worker.sh:20-26` sourcing `.env`; the web gets `VITE_API_URL` only (`api.js:1`).
6. **`.env` itself**: 232 bytes, last modified 2026-09-23 12:18, before `.env.example` gained `PROVIDERS`, the pacing block and the hold (2026-10-01); the running worker reports `min_gap 0.0`, `image_budget 40`, `cooldown 30/900` for every provider (the code defaults). Inferred, not read: `.env` holds the three secrets and little else, so no minimum gap and no Grok override are configured (section 3, pacing row).
7. **Provider sessions after twelve idle days**: by their own expiries the cookies are far from expiring (ChatGPT 90 days from 2026-10-01, Grok 177, Google 365-400, per the one-profile plan's reading), but sessions were ended server-side before (ChatGPT's token rejected after 4.5 days, Gemini after 1.5 days twice), the worker has been in mock mode since at least today, and nothing has opened the profiles from the platform. Whether each profile still answers is **not knowable without opening it** (the login script's proof is a read without a turn, but it contacts the site; `tests/session_check.py` costs a turn each). ChatGPT's Cloudflare state, Google's unusual-traffic state, Grok's free-tier wall, and any page change on the three sites over twelve days are likewise unknowable offline; the last page change came overnight once (2026-09-27).
8. **Tokens**: login JWTs live 24h (`config.py:20`), all expired, trivial; API keys never expire (`schema.sql:116-125`); the plan's test key was revoked. `sessions` rows are never pruned (`security.py:34-38, 42-44`), trivial.
9. **The agent layer is not in git**: `.git/info/exclude:9-12` excludes `CLAUDE.md`, `.claude/`, `docs/agent/`; `git ls-files docs/agent` is empty. "Everything is pushed" (HANDOFF.md:13-14) is true of the code only; the 29 plans, HANDOFF, DECISIONS, ACCESS and LESSONS exist on this disk alone (plus whatever `/kt:save` backs up, not verified). By the kt rules' design, but worth knowing after a gap.
10. Docker Desktop up, api and web answer 200, host worker answers on 8000: fine.

---

### 5. HANDOFF "Next steps" (HANDOFF.md:207-240)

- 1 (the real gate's outdated check): **done** at b589041, as written.
- 2 (ChatGPT and Cloudflare's check): **a standing rule, not a task**; still the right rule; last seen 2026-10-07 01:54, lifted by 11:30. Nothing to close.
- 3 (stop probe, picture turn, earlier nodes on a failed read): **done** (2026-10-02; d2d346d; 508c748), as written.
- 4 (Gemini's failure sentence): **done** at 63ec5dd, as written.
- 5 (rerun the Grok real gate): **not done**; no record since 2026-09-29; the first-open plan's Evidence still says NOT RUN. Needs the real site and Grok's seven daily turns.
- 6 (the owner's own: empty the Trash; delete the listed test conversations): the ten ChatGPT threads of 2026-10-02 are **done**; the rest of `residue-left-in-accounts.md` (ChatGPT's later kept threads, Gemini's, both Grok accounts') is **not knowable offline**; `~/.Trash` shows no `ai-platform-old-session*` names, which is either emptied or unreadable from here.
- 7 (next plan candidates, the UI polish list): **not done**; every listed point is still open (ledger C17-C21).

Not in the list but due by DECISIONS.md's own rule: section 3 "Cloudflare deployment, after MVP works locally, **Q4 2026**" (DECISIONS.md:96) is due now (2026-10-21), and it conflicts with DECISIONS.md:19 (FastAPI cannot run on Workers; the hybrid row is superseded); its prerequisites are open decisions 1 and 2 (server provider, domain). The file says an item due and unpaid must be raised.

What I would put first, in order, with reasons:

1. **Re-establish the ruler before any real run.** Every probe script, worker log, reviewer repro and kept gate record is gone (section 4.1); the host worker is in mock. Record that fact and the three-day rule in LESSONS.md, and make `--keep` (or a copy step) put real-gate records somewhere outside `$TMPDIR` (one small change in `acceptance.py`), so the next real failure can be named from its own record as CLAUDE.md:60-62 demands. Cheap, offline, and everything else that touches the sites depends on it.
2. **Find out whether the three sessions are alive, one provider at a time, ChatGPT with one turn alone first** (the standing Cloudflare rule). This is the gating unknown for every real item (ledger D) and the twelve idle days are themselves a measurement for the "sessions that die" lead: three profiles alive after twelve days with no login strengthens it; a dead one weakens it. Needs the owner's go, costs one turn per provider.
3. **The composer-attachment probe on ChatGPT** (ledger C1): the only open item where one person's data can reach another's turn, and the image API has made uploads routine. Read-only on the real page with ChatGPT off the worker; the offline half (the fake page) first.
4. **The earlier-turn-nodes gap** (ledger C2): a wrong answer charged; measurable on the fake page in `tests/test_chatgpt_composer.py`, no real turn needed; a plan of its own, as the picture-wait review said.
5. **Two cheap user-facing fixes in one small plan**: `provider_error` texts with admin instructions and the host path shown to users (C5), and the Grok "Video script" button that charges, fails and refunds (C6). Both pinned by ui_smoke, offline.
6. **Configuration truth**: decide with the owner whether `.env` should carry `MIN_GAP_SECONDS` and the Grok override (the decided pacing is off today, section 3), whether `CLOAKBROWSER_AUTO_UPDATE=false` goes into `run-worker.sh` or `.env.example` (section 4.3), and fix `web/Dockerfile` to use the lockfile (`npm ci`) and `docker-compose.yml` to pass the api its documented variables (section 4.4-4.5). Each is one or two lines; the first two change behaviour and are the owner's call.
7. **Record hygiene** (section 1): PROJECT.md's architecture line, HANDOFF's plan count and latest evidence, ACCESS.md:53 and :62, the two superseded DECISIONS rows marked as such, CLAUDE.md's Run and smoke lines. Half an hour, no code.
8. **Raise the due deferred item** (Cloudflare deployment, Q4 2026) together with open decisions 1-2, since DECISIONS.md:4 says the agent must; no work until the owner answers.
9. Then the Grok real gate (next step 5) and the UI polish plan (next step 7), in that order, as the HANDOFF already lists them.
