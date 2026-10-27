# HANDOFF.md: live state (updated at the end of every session)

This file is a handoff note, not a diary; delete stale items, history already lives in git log;
write feature or task ids IN FULL (M3-F9, not F9: short ids collide across milestones and grep
returns the wrong one).

Last updated: 2026-10-02 01:40, HEAD 302a274, clean tree, **no plan is armed, everything is
pushed** (`origin/master` is 302a274). **The owner's standing yes of 2026-10-02: the agent pushes
`master` to the private `origin` on its own once a plan has closed with its full gate green**
(DECISIONS, the repo's CLAUDE.md); any other push is still asked first. **The saved-info guard plan
closed at e64575a** (`docs/agent/plans/2026-10-01-gemini-saved-info-guard.md`, tier 2, its
Evidence written; 302a274 adds one measurement to the research note). **The driver was then
seen refusing on the real account** (01:26, the owner's yes): the saved-info switch on for about
10 seconds, the look refused in 2.9s naming saved info, the switch off again and read back off.
Since the plan: before every Gemini turn the driver reads both of the account's memory
switches, personal context and then saved info, each on its own page in one tab, only on
`gemini.google.com`, `off` believed on two polls in a row; either one on refuses the turn as
`provider_misconfigured`, naming it; health's `memory` says `off` only when both read off.
`tests/test_gemini_driver.py` 111/111, 59 of 61 mutants red, one review round with nothing
blocking, the full gate once at e64575a (39/39, build exit 0, ui_smoke 53/53), the guard alone on
the real profile (both off, 3.5 to 4.5s a look), one real turn through the platform ("pong" in
18s, memory off); the full gate once more at 302a274 (39/39, build exit 0, ui_smoke 53/53).
**The host worker serves `chatgpt,grok,gemini` in real mode at 302a274 since 01:36.** **The
owner deleted the 16 ChatGPT test threads at about 00:06** (each 200), so
ChatGPT's server lets that session through again; no ChatGPT turn has been sent since 21:51.
Before it, **the session
plan closed at a0d04b0** (`docs/agent/plans/2026-10-01-one-profile-per-provider.md`, tier 1, its
Evidence written): each provider's session is a browser profile `storage/sessions/<provider>/`
with one device seed, opened by the login script, the drivers, the probes and the gate; three
review passes, 55 of 55 mutants red, the full gate once at a0d04b0 (39/39, build exit 0, ui_smoke
53/53). **The owner logged in to all three profiles at 20:13 to 20:16.** Real runs since:
**Gemini answered at every worker start through 22:31, its profile opened seven times in 2h15
and still signed in** (the afternoon's login died after four launches in 47 minutes); its
saved-info switch was turned off with the owner's yes; **ChatGPT passed two session checks and
its real gate 29/30** (the one red is the gate's own outdated check), **then met Cloudflare's
check again at 21:51** (the stop probe's first turn), so no more ChatGPT turns were sent;
**Grok's session lives and its memory reads off; its turns failed three ways around the free
tier's wall of 21:27 and pass since 23:06** ("pong" in 44s, the stop check green, nothing in the
driver changed) on a brand-new Grok account. The owner approved the rest of the list at 22:50
(Next steps 0). The
hold-and-stop plan (set aside at db429a1) had two real lines carried into the session plan: the
cancel at the site PASSED ("sent: False"), the stop probe NOT PASSED (Cloudflare).
The owner's acceptance walk, run by the agent on 2026-10-01 against the real providers: **33/36
checks, 12 of 13 items**, the only red Gemini's then signed-out session, green in the rerun (Latest
evidence). The UI polish plan closed at a8b5302 (Back closes the phone's list, notes in an empty
list, the select named, every text at WCAG AA). Real gates at HEAD's fixes: ChatGPT 30/30
(3e32a12), Gemini 25/25 (34b533c), Grok 19/20 at bbb3924 (its one red, the gate's own probe, is
fixed and passed in the Gemini run). Gemini ran on another account of the owner's from 2026-09-29
(its personal context turned off); the login of 2026-10-01 read that switch on again.
The web works on a phone since
ab8e210 (the mobile plan), the chat view keeps its tail since 9d3a60b (pictures included), and
replies show no blank lines between blocks since bbb3924, all closed the same day. Three plans closed on
2026-09-27: the Gemini provider (bbeb471), the Google-block fix (743a586) and the Grok memory guard
(20f1aad). The owner's standing order is done: Grok closed, Gemini built and served, Grok's memory
measured, turned off and read before every turn, and the real grok gate green on it (18/18,
2026-09-28). On 2026-09-28 the runner fix closed (26dc5fc): an ended runner no longer takes
`/health` down. On 2026-09-29 the served-providers plan closed (a4a36f3): the api lists and only
accepts the providers a worker serves, and the web greys the others out.

Gemini's test threads on its first account: 23 of 30 deleted, the rest left by the owner's choice (Next steps 1); Google's
unusual-traffic check (`www.google.com/sorry/`, by IP) stopped the first cleanup, so never bulk
delete from this machine again, and never solve or bypass the check.

## Where we are

Three providers are built and the host worker serves all three. API (FastAPI, Docker, port 3000), browser
worker (FastAPI on the host, port 8000, cloakbrowser venv) and web UI (React, Docker, port 5173).
The worker holds no database handle: it polls the API and posts results back.

Each provider gets **its own runner thread and its own browser**, because two stealth browsers
cannot be launched from one thread (measured), and its own pacing, so a provider sitting out a
cooldown never parks the others. Claims and tombstones are filtered by provider, a runner refuses a
job that is not its own, and a job whose provider nobody serves is failed as `no_worker` and
refunded rather than waiting forever. A conversation belongs to one provider: the api refuses a
turn from another with 409 and the interface locks the selector to the open conversation.

ChatGPT does chat, image and video script, with one thread per conversation, files, zips, delete.
Grok does **chat and image** (a video script uploads a reference picture and grok's upload flow is
unmeasured). Both settle on their own server's word, keep `/c/<uuid>` as the thread, and delete the
thread when the conversation is deleted. Gemini does **chat, image and video script** on the
owner's own Google account: it settles when its `StreamGenerate` request finishes, keeps
`/app/<16 hex>` as the thread, reads the account's two memory switches before every turn
(personal context, then saved info, since e64575a) and refuses while either is on, and deletes
the thread when the conversation is deleted. The host worker serves
it since 2026-09-27 (DECISIONS 2026-09-27, the owner's choice).

Twenty-two plans finished and one set aside, each with its measurements in its own Evidence section:
- `2026-09-23-ai-platform-mvp.md`, the platform itself
- `2026-09-23-threads-and-files.md`, threads and generic deliverables
- `2026-09-23-reliability-and-server-truth.md`, leases, cancel, pacing, server truth
- `2026-09-24-close-open-measurements.md`, the memory guard, the banner by shape, one zip
- `2026-09-24-team-ready-conversations.md`, rename, search, delete, daily quota, markdown, two languages
- `2026-09-25-grok-provider.md`, grok chat and image, closed 2026-09-27 at 72ca6ed
- `2026-09-27-chatgpt-composer.md`, chatgpt.com's new page, closed 2026-09-27 at 280cbfe
- `2026-09-27-gemini-provider.md`, gemini chat, image and video script, closed 2026-09-27 at bbeb471
- `2026-09-27-gemini-google-block.md`, Google's unusual-traffic block named, closed 2026-09-27 at 743a586
- `2026-09-27-grok-memory-guard.md`, Grok's memory read before every turn, closed 2026-09-27 at 20f1aad
- `2026-09-28-runner-stop-event.md`, an ended runner no longer takes `/health` down, closed 2026-09-28 at 26dc5fc
- `2026-09-29-served-providers.md`, only providers a worker serves are offered and accepted, closed 2026-09-29 at a4a36f3
- `2026-09-29-mobile-layout.md`, the web on a phone, closed 2026-09-29 at ab8e210
- `2026-09-29-view-follows-tail.md`, the chat view keeps its tail, closed 2026-09-29 at 9d3a60b
- `2026-09-29-reply-blocks-and-file-card.md`, replies without blank lines, file cards in their tiles, closed 2026-09-29 at bbb3924
- `2026-09-29-first-open-and-refusal-probe.md`, ChatGPT's late composer gets a second load, closed 2026-09-29 at 3e32a12
- `2026-09-29-busy-runner-keeps-alive.md`, a busy runner keeps pinging, closed 2026-09-29 at 34b533c
- `2026-09-30-gate-checks-measure-the-thing.md`, the gate's deletion and cross-conversation checks, closed 2026-09-30 at 89e8beb
- `2026-09-30-chatgpt-delete-token-wait.md`, ChatGPT's thread deletion waits for the session read, closed 2026-09-30 at 94efd1f
- `2026-10-01-hold-misconfigured-and-real-stop.md`, a provider its admin must fix is held out, Stop stops at ChatGPT, set aside 2026-10-01 at db429a1 (its two real lines carried into the next)
- `2026-10-01-one-profile-per-provider.md`, one browser profile and one device per provider, closed 2026-10-01 at a0d04b0
- `2026-10-01-gemini-saved-info-guard.md`, Gemini's saved-info switch read before every turn, closed 2026-10-02 at e64575a
- `2026-09-30-ui-polish.md`, Back closes the phone's list, the empty list's notes, the select named, every text at WCAG AA, closed 2026-09-30 at a8b5302

Latest evidence, each on a clean tree:
- The saved-info guard at e64575a, 2026-10-02: full gate once (00:54 to 01:01, the host worker in
  mock) `python acceptance.py` **39/39** exit 0, `npm run build` exit 0, `tests/ui_smoke.py`
  **53/53** exit 0; every offline test: gemini driver **111/111**, composer 22/22, grok memory
  20/20, grok settle 8/8, liveness 4/4, login provider 10/10, runner health 4/4, runner
  tombstones 3/3, tombstones 5/5, session profile 12/12, the session check's table 23/23; the
  guard alone on the real profile (`/tmp/gemini_guard_probe.py 2`, 00:53, no turn): both pages
  off, 4.5s and 3.5s a look, one tab left open each time; one real turn
  (`python tests/session_check.py gemini --keep`, 01:02): "[PASS] gemini answers  done in 18s,
  reply 'pong', worker mode real, memory off", 1/1, exit 0; **the refusal on the real account**
  (`/tmp/gemini_saved_info_on_check.py`, 01:26, the worker stopped, no turn): saved info pressed
  on, the look "REFUSED (provider_misconfigured) ... saved info switched on ..." in 2.9s, pressed
  off after about 10s, read back `false`, the next look "would send"; full gate once more at
  302a274 (01:27 to 01:34): 39/39, build exit 0, ui_smoke 53/53
- The owner's acceptance checklist (13 items), walked by the agent through the web on 2026-10-01
  at a8b5302 with the host worker real (`/tmp/e2e_acceptance.py`, not in the repo; its dry run on
  the mock worker first): **33/36 PASSED**. ChatGPT: a formatted answer in 34s, a name remembered
  inside a conversation and not in a new one, a picture in 335s (1254px, the one-minute hint
  seen), a video script, a zip card, Download all (2 entries), Stop (bubble gone in 1.9s, 94 -> 93
  -> 94), all green. Grok answered ("Tokyo", 32s). Rename, search by name and by a word inside,
  the no-hit note, a gallery delete, a conversation delete (the api's tombstone claimed and settled
  in 6s, no error), Vietnamese, the phone (list behind its button, Back closes it, nothing
  sideways, 69 texts at AA), sign out and in again: green. **Red: Gemini, 3 checks**, both turns
  failed before anything was sent with the job's own error "the gemini session is signed out; run
  scripts/login_provider.py gemini" (`provider_misconfigured`), both credits returned (91 stayed
  91). Pictures, downloads and `results.json` in `/tmp/e2e_acceptance`; the test account's email
  and password in `/tmp/e2e_acceptance/test-account.json` (three conversations left for the owner
  to look at: the ChatGPT one with the cat, the zip and the script; the Grok one; Gemini's empty one)
- Full gate at a8b5302: `python acceptance.py` **36/36** exit 0, `npm run build` exit 0,
  `tests/ui_smoke.py` **52/52** exit 0 (45/45 at 94efd1f); every offline test at bbb3924: composer 12/12 (17/17 at
  3e32a12, 19/19 at 94efd1f), DOM signatures 10/10, gemini driver 62/62, grok memory 17/17, grok settle 8/8, runner
  health 4/4, runner tombstones 3/3, tombstones 5/5
- ChatGPT real gate at 3e32a12 (after the first-open fix): **30/30**, 6 skipped, exit 0
- Gemini real gate at 34b533c (after the busy-runner fix): **25/25**, 11 skipped, exit 0
- Real runs at bbb3924, 2026-09-29, the owner's yes, host worker stopped during the gates:
  ChatGPT `--real --keep` **29/30**, 6 skipped: only "chat job completes" red, the first turn of a
  freshly launched browser saw no composer within the 45s wait although signed in (every later
  turn fine; three cold opens measured after, no turn sent: composer at 7.8s, 13.7s, 34.9s). Grok
  `--real --keep --provider grok` **19/20**, 16 skipped: only the refusal check red, a gate defect
  (its video probe used the run's one picture, which the deletion check had removed: 404 before
  503, as designed). Gemini `--real --keep --provider gemini` **15/25**, 11 skipped: **the saved
  Gemini session is signed out** (settings land on `/saved-info`, the app shows sign-in links; no
  `/sorry/` block), so every turn was refused and refunded. The owner logged in again with another
Google account; its personal context read on and every turn was refused again (15/25); turned off
with the owner's permission, the third run was **20/25**: every Gemini turn done (chat, picture,
video script, thread recall, no cross-talk, memory off), the reds are the gate's refusal probe,
its too-short wait for a 64s Gemini deletion, a turn refused while the runner was deleting a thread
without pinging, and two not yet traced (Parked questions). Web journey `tests/ui_journey.py`
  **8/8** (ChatGPT: a real picture in 316s, the model's zip, download all, quota 100 -> 98).
  Before: ChatGPT 28/28 at 280cbfe, Grok 18/18 at 20f1aad, Gemini 23/23 at 68958de

## Verify commands

```
Quick gate: python acceptance.py
Full gate: python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py
Provider smoke: python acceptance.py --real --keep [--provider grok|gemini]
```

acceptance.py is standard library and starts its own api and worker on free ports. `--provider`
picks who the job checks speak to; in mock mode the worker always serves `chatgpt,grok,gemini` so
the multi-provider machinery is exercised every run. `--keep` keeps the run's workspace, logs and
database: the api's `thread_tombstones.error` holds the worker's own reason a deletion failed.
ui_smoke and ui_journey import cloakbrowser, so they run under the venv python against the running
stack, with the host worker in `PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4`. `tests/grok_probe.py`,
`tests/gemini_probe.py` and `tests/provider_probe.py` measure the real sites (`gemini_probe.py all`
spends no turn and changes nothing, but its `list` prints the owner's own conversation titles);
`tests/test_gemini_driver.py`, `tests/test_grok_settle.py` and `tests/test_tombstones.py` need no
account.

## Next steps

0. **The owner approved the whole list on 2026-10-01 ("được, tôi duyệt toàn bộ, bạn làm giúp tôi
   đi"). Done since: the three old state files moved to the Trash (recoverable until the owner
   empties it; `ai-platform-old-session-<provider>-20261001.json`); "Gemini Notebook" turned off
   at 23:00 (read back off; on now: YouTube, Google Flights, Google Hotels, Verify AI); the whole
   history scanned for secrets (`/tmp/secret_scan.py`: 114 commits, 23256 added lines, no key,
   token, cookie, bearer or private key; `.env`, `storage/` and the agent layer never committed;
   two throwaway test passwords in `tests/ui_journey.py` and `tests/ui_smoke.py`; one author
   identity); the ChatGPT cleanup list written (`docs/agent/residue-to-delete-2026-10-01.json`,
   16 threads, dry run "16 threads, 0 memories").** **The owner ran that list on 2026-10-02 at
   about 00:06 (`scripts/purge_test_residue.py ... --yes`, in the terminal): "done: 16 removed, 0
   failed", every thread answered 200**, the six of the interrupted gate among them. So
   ChatGPT's server let that session through again 2h15 after Cloudflare's check of 21:51 (a
   deletion is a plain backend call; a turn has not been tried since). The host worker was up in
   real mode, but its ChatGPT runner had not opened the profile (no ChatGPT job since its start
   at 00:04), so the script's browser was the only one; no browser and no lock file were left.
   **Permanent deletions stay the owner's to
   run** (the agent's rules forbid it to delete account data for good, whatever the yes): still
   to do by hand in Gemini (the test conversations of
   2026-10-01: a word to remember and its question, "Thủ đô của Việt Nam", "Tôi tên gì?") and in
   Grok ("pong", "Thủ đô của Pháp", the stopped essay). **Pushed at 23:18 to the private repo
   github.com/hainguyen-keyti/ai-platform** (the owner's yes).
   **What remains of the list, in order:** (a) **Grok: nothing to fix, measured 23:05 to 23:12**:
   the driver's open and typing on the new page worked three times without sending, then a turn
   through the platform answered "pong" in 44s and the stop check passed (a plain turn 206s, a
   stopped turn refused 4.1s after its stop); the failures of 21:21 to 21:52 sat around the free
   tier's wall. Grok is back on the host worker; its free tier is slow and walls, a paid tier is
   the owner's call. (b) **The real gate's outdated check** (`acceptance.py:763-770`):
   "deleting a conversation cancels its running job" still wants a thread removed from a turn the
   driver no longer sends; it should pass on the worker's `last_stop` saying the turn was not
   sent. **This is the next piece of work: it needs one real ChatGPT gate (twenty minutes,
   sixteen jobs) to prove it, so not before the daytime of 2026-10-02, hours after the owner's
   16 deletions of 00:06.** (c) **Done on 2026-10-02 at e64575a: the Gemini driver reads the
   saved-info switch too** (the plan's Evidence; what it left open is in Parked questions).
   (d) **ChatGPT's Cloudflare check**: it came at 16:45 (the old state file)
   and at 21:51 (the pinned profile), each time after a burst (a real gate's twenty minutes, the
   driver polling the server through picture waits); the server answered 16 deletions at 00:06,
   a turn has not been tried; before the next real ChatGPT run send one turn alone
   (`python tests/session_check.py chatgpt --keep`), space real runs hours apart, never pass it. The stop probe (`/tmp/stop_probe.py
   after`) is still owed for the driver pressing the site's stop button. (e) Gemini's own error
   sentence passes for a reply (Parked questions). Still to ask the new ChatGPT account: "Tôi tên
   gì?" in a new conversation (the old one answered "Keyti"). **The old state files
   `storage/sessions/<provider>.json` are no longer read and still hold credentials** (the old
   Grok account's login is live in its file): they are in the Trash since 23:00, for the owner
   to empty. **The code is pushed since 2026-10-01 23:18: `origin` is the private repo
   github.com/hainguyen-keyti/ai-platform** (created by the agent with the owner's yes, "Tạo repo
   private và push"; visibility PRIVATE, branch `master`, 114 commits at a0d04b0 then, 119 at
   302a274 now, the history scanned for secrets first; the agent layer is excluded by
   .git/info/exclude, and storage/ and .env are ignored). Since the owner's standing yes of
   2026-10-02 a plan that closes with its full gate green ends with `git pull --rebase` and
   `git push` without asking; any other push is asked first. From the real runs
   of 2026-09-29 (Latest evidence): rerun the Grok real gate when its daily
   turns allow (`python acceptance.py --real --keep --provider grok`), the one line of the
   first-open plan not yet run; the refusal probe's fix already passed in the Gemini real run
   ("video None"), the same path. Tried at 94efd1f on 2026-09-30 03:19 (+0700), 8 hours after the
   last Grok turn: the first turn was walled ("grok answered with nothing: Please try again soon,
   or upgrade for higher priority access", the run's own job record), so the agent interrupted the
   gate after it rather than send more walled turns; its two conversations recorded no thread
   (a walled turn can still leave one in the account, not checked); workspace
   `$TMPDIR/ai-platform-acceptance-oxn_cmz3`. The UI polish plan closed at a8b5302; the next plan
   candidates are in Parked questions (the UI polish reviews' list, above all a reload with the
   phone's list open leaving a dead Back step). With the owner's permission
   of 2026-09-30, every test thread the real runs of 2026-09-29 left was deleted through the
   drivers: ChatGPT 22 of 22 (both gates and the journey's, 30s apart, each reading back 404), Grok
   3 of 3 (gone from the account's list, 49 conversations, one page), and the new Gemini account's
   14 of 14 (2 minutes apart, 8 to 40s each, each confirmed no longer opening, no block page). The
   scripts are `/tmp/delete_test_threads.py` and `/tmp/delete_test_threads2.py` (the second warms
   the ChatGPT page first; the driver waits for the session token itself since 94efd1f)
1. Test threads left on purpose (the owner's choice, 2026-09-27; they hold only test prompts and the
   owner may delete them by hand). Gemini: 23 of the 30 approved were deleted, a delete that "still
   opens" was not done (Google refuses deletes after a burst and then blocks the address). Grok: the
   memory leak test's two threads, ae9f4f6b-60f5-46ce-a9e9-c4f25ddcedd5 and
   7b95db0b-abc7-44ea-a15a-a9decde76645, beside the older ones in Parked questions
2. The real grok gate, run on 2026-09-28 at 20f1aad at the owner's word: **18/18 PASSED, 16
   skipped, exit 0**, including the check it no longer skips, "health reports the provider's memory
   setting: memory off" (17/17 with 17 skipped before the guard). It left four Grok test threads,
   like the others: 17ad1091-ee8b-4d7d-8fff-90ac375eda6d, 7b58be36-393b-4c21-81cb-6bdd8a739d4e,
   7be18593-1502-4934-8a9b-158bb7691982, e2560047-c0fa-40f4-afa0-5fed01e22a59
3. Candidates for the next plan, from Parked questions: the UI polish reviews' non-blocking list
   (a reload with the phone's list open, Forward, the list answering an older search, the row's
   hierarchy and icon hover), and the older gallery items the design review saw
4. Restart the host worker after any worker change: uvicorn does not reload there, the api does.
   `PROVIDERS=chatgpt,grok,gemini ./scripts/run-worker.sh` (call it by its full path: a `cd` into
   `web/` earlier in a shell once made `./scripts/...` miss). It runs from the agent's session
   (since 2026-10-02 01:36 with `PROVIDERS=chatgpt,grok,gemini`, at 302a274) and dies with it: on
   2026-10-01 the app had quit and Docker Desktop was off too, so api, web and worker were all
   down until restarted. The mock one for ui_smoke serves only `chatgpt` (`PROVIDERS` defaults to it)
5. Media created before 8acdaa7 has no message_id; it is merged into the thread by timestamp
6. The gallery has no way to filter or group

ChatGPT test threads the interrupted real gate of 2026-10-01 left in the owner's new account,
**all six deleted by the owner on 2026-10-02 (the purge above, each 200)**:
6abe29a5-6cf0-83ec-b8f5-330cde9febee (pong), 6abe29e4-398c-83ec-a73c-48756bff254c (the
remembered word), 6abe2a12-421c-83ec-a7a5-7ed1e6478a85, 6abe2a28-d20c-83ec-a642-81949983ebdd and
6abe2a4a-cd24-83ec-b927-fefe9951e12b (two zips), 6abe2a6d-f470-83ec-bb82-a09c99c8201f (the blue
square and its refused follow-up; its deletion answered 403), and perhaps one never recorded (the
failed picture job, "a plain red circle on white", if its prompt went out). On the new Gemini
account, from the rerun of item 8 and the name question (through the platform, test user
`e2e-gemini-...`, `/tmp/e2e_acceptance/test-account-gemini.json`): two threads.

Gemini test threads left in the owner's account on purpose (the `/app/<id>` tail): 61a5e2def2f117e6,
a85fb82fb7d62799, 27074bd3946fcf57, 239f0ba819d9963c, 1fff9e0d40c1495a, ea936f95c9f0eefe,
969da7f941ec9cc3, plus those never printed (the `settle-picture` probe's, the driver runs between
76a1e1f and 47cd59b, the real gate at d121414). The two kept gate workspaces
`$TMPDIR/ai-platform-acceptance-f69ugegc` and `...-t2_wyf_a` are no longer needed.

## Known traps

- cloakbrowser needs shm_size: '2gb' inside Docker; the worker avoids this by running on the host
- Playwright's sync driver belongs to the thread that created it: a provider's browser must be
  created on its own runner thread, never in pool start
- **`page.keyboard.type()` presses a key per character and maps a newline to Enter.** On grok.com
  Enter sends, so a multi-line prompt goes out as several turns. Use `insert_text`
- Grok's ProseMirror ignores `fill()` (ChatGPT's new one takes it, measured 2026-09-27), and no
  ProseMirror's `innerText` equals the prompt character for character: flatten both sides before
  comparing, and check both ends, or a prompt left over from a failed attempt goes out twice
- ChatGPT's composer since 2026-09-27 is `div.ProseMirror[contenteditable="true"]` mounted about
  ten seconds after a placeholder `textarea#pending-home-input`, the picture input is
  `input[type="file"][accept="image/*"]`, a generated picture is a `blob:` img inside
  `[data-testid="generated-image-gallery"]`, and the error banner is `aside[role="alert"]`;
  docs/research/2026-09-27-chatgpt-composer.md has the rest. Grok's is
  `[data-testid="chat-input"] .ProseMirror[contenteditable="true"]` for this account and a plain
  `textarea[aria-label="Ask Grok anything"]` anonymously, both cohorts live at once
- Gemini's page is not settled when its composer shows: the conversation list paints its rows up
  to 2.4s later, the address of a thread that does not exist goes back to `/app` only 0.5 to 0.9s
  later, and a row's menu button shows only under the pointer. Wait for the sign itself;
  docs/research/2026-09-27-gemini.md has every measurement
- Real turns fired with no gap draw a 429 from ChatGPT and bounce a stored thread to the root;
  verify the url after opening, retry on 429, keep a gap
- Google answers too much automated Gemini traffic from one IP with `www.google.com/sorry/index`
  (an unusual-traffic CAPTCHA) for every Gemini page: on 2026-09-27 a day of probes and three real
  gates, then deletions one after another, tripped it. Pace Gemini page loads, deletions above all
- A real gate run without `--keep` deletes its workspace on exit, and with it the worker's own
  error: the first red Gemini gate could only be diagnosed by guessing, and the guess was incomplete
- The web container keeps its own node_modules volume: after adding a dependency run
  `docker compose exec web npm install`
- Docker Desktop being off looks exactly like a broken platform: the host worker still answers on
  8000 while web and api are silent
- A stale host worker has twice been mistaken for a broken feature: compare the process start time
  with the file mtime before believing a symptom
- The Docker api's database cannot be opened read-only from the host (`mode=ro` fails: Linux
  SQLite in the container removes the WAL and SHM files on the last close); read a copy of
  `storage/db/app.db` instead. The gate's own api runs on macOS, where they stay, so its reads work

## Parked questions

- Grok's free tier answers a short burst and then asks for about nine minutes; fully spent it says
  22 hours. Nothing but the page says so: `/rest/rate-limits` reports 7 of 7 for grok-4 and never
  decrements. The driver treats a turn that finishes carrying neither words nor a picture as a
  refusal, quotes the page, refunds and cools down. A paid tier is the only way to make Grok useful
  for a team; that is the owner's call
- Grok's upload flow (base64 to `/rest/app-chat/upload-file`, then `fileAttachments`) is unmeasured,
  which is why video script is unsupported there
- `tests/grok_probe.py` and the gate both create threads in the shared Grok account. The probes
  delete their own; the gate's are deleted by the conversation delete, but a failed run can leave
  some behind. The Gemini gate leaves its non-deleted conversations' threads too (eight per run)
- The whole archive is built in memory; fine for a team, a spooled file before SaaS
- A refused result's files are removed by the worker, measured in mock mode only
- **The shared Grok account holds 39 older conversations**, most of them made by gates and probes
  before 72ca6ed stopped tombstones from starving, many with an empty title because the turn never
  completed. With the owner's yes, the two from 2026-09-25 and the eight made on 2026-09-26 were
  removed (`DELETE /rest/app-chat/conversations/soft/<id>` answered 200 each, a full list read back
  without them: 47 became 39). The rest wait for a list the owner approves: a title does not say
  which are the owner's own. `scripts/purge_test_residue.py` speaks only ChatGPT's `/backend-api`
- `tests/test_runner_tombstones.py:73` still says "No join(): Runner names its Event _stop, which
  shadows Thread._stop"; since 26dc5fc the Event is `_halt` and `join()` works, so that comment is
  out of date (outside the runner plan's radius, parked 2026-09-28)
- A Grok turn that the free tier walls **still creates a thread**: the 11:53 attempt on 2026-09-25
  came back empty with the upgrade sentence and left conversation cf2eac51 behind. A failed turn is
  not a free turn as far as the account's clutter goes
- The Gemini plan left seven points open, non-blocking, listed at the end of its Evidence: the row
  label check skipped on an empty title, a second switch reading `unknown`, only the first stream
  counted, a quota wall painted as an ordinary reply, multi-picture turns, a thread still opening
  right after its delete, and how soon a sent turn's address becomes the thread's
- `tests/gemini_probe.py purge` still opens a row's menu by hovering a visible button, the flow the
  real page defeats; it fails safe (deletes nothing). Delete through the driver instead, or bring
  purge in line with the driver when a plan touches the probe again
- The served window is pinned only against a wider one: a window a third as long would refuse a
  runner in the middle of a long turn in production, and nothing catches it (the gate's 2s lease
  never leaves a provider between the two). A throwaway-database test of `_served` against
  `_sweep_unserved` at W-1, W and W+1 would; it needs a new file under `tests/`
- From the first-open review (2026-09-29): a job cancelled while ChatGPT's page is still opening
  still sends its prompt (`_open` never checks for a stop, pre-existing; the second load widens the
  window); a kept picture under `storage/diagnostics` can show the shared account's sidebar and
  another user's thread, and nothing removes old ones
- Seen in the Gemini rerun (2026-10-01, `/tmp/e2e_acceptance/shots/08c-rerun-gemini-video-script.png`):
  the video script's reply ends with two stray lines, "JPG" and a bullet "2", after the script
  itself; they look like the attached picture's chip, not traced
- **Sessions that die: a lead, stronger since 2026-10-01, still not proven.** The records: ChatGPT's
  token was rejected 4.5 days after its login ("the provider rejected a fresh session token", three
  turns, 2026-10-01 14:57 to 14:58); Gemini died after about 1.5 days twice; and the Gemini login
  saved on 2026-10-01 at 15:18:40 read "Signed out" at 16:05 (`tests/gemini_probe.py
  open,settings-read`: sign-in wording, 0 threads, the two switches of `/saved-info`; at 16:12
  Google's account chooser beside the account: "Signed out"). Between the two, four launches used
  that file: the probe at 15:21 (signed in, 3 threads), the switch at 15:49, the host worker from
  15:49 to 16:04 (four turns done, the last at 15:56), and the sweep at 16:04 that found it dead.
  Whether the worker's own browser was still signed in when it was stopped is not on record. A
  third record the same day: the ChatGPT login saved at 16:34 was opened by the real gate's
  browser at 16:35, and from 16:45 Cloudflare refused that browser ("cloudflare_challenge", then
  403), which it had not done in any earlier gate; whether that session still answers is not
  known, nothing was sent after the interrupt. Two
  facts measured beside it, neither shown to be the cause (Grok's file of 2026-09-27 still works
  under both): (a) no saved session is ever written back: `gemini.json` kept its login time
  through that worker run, the driver's own save runs at shutdown on another thread than the
  browser's, so every launch starts from the login-day cookies; (b) every `cloakbrowser.launch()`
  draws a random `--fingerprint` seed (`cloakbrowser/config.py:55-65`, version 0.5.10) and a site
  reads another device each time (`/tmp/fingerprint_churn.py`, no account: the GPU read "Apple
  M3", then "Apple M1 Pro", 1 of 16 signals; with `--fingerprint=24680` twice "Apple M2", 0 of 16).
  The owner did nothing to that account in that window (asked 2026-10-01: no alert answered, no
  password change), so nothing on the owner's side explains it.
  **A way out measured without any account** (`/tmp/persistent_profile_probe.py` 5/5,
  `/tmp/profile_lock_probe.py`): `cloakbrowser.launch_persistent_context(dir, headless=True,
  args=["--fingerprint=N"])` keeps a cookie with an expiry, a cookie added from outside and
  localStorage across launches (a cookie without an expiry is gone), shows the same device in
  both launches, still exports a storage state, and Chromium refuses a second browser process on
  that profile ("Failed to create a ProcessSingleton for your profile directory"; asked from the
  same thread, Playwright's own refusal answered first and proved nothing), which would make
  one session per provider mechanical. More, the same day, still without an account: killing
  the browser's owner (SIGTERM, SIGKILL, 2s or 40s after a cookie was set) leaves no browser and
  no lock file, and the next launch opens with the cookie kept (`/tmp/profile_kill_probe.py`); a
  windowed launch and a windowless one on one profile and seed agree on 20 of 23 signals and
  differ in the screen's depth and pixel ratio, the window's size and the client rects that
  follow (`/tmp/headed_headless_probe.py`; the owner keeps the worker windowless); a cookie
  without an expiry is gone at a restart and `session.restore_on_startup` in the profile's
  Preferences did not keep it (`/tmp/session_cookie_restore_probe.py`); `context.request.get`, a
  second tab and `expect_download` work on a persistent context (`/tmp/persistent_api_probe.py`).
  From the saved files, names, domains and expiry only (the owner's yes): every login cookie has
  an expiry (ChatGPT's session token 90 days, Grok's `sso` 177, Google's 365 to 400,
  `__Secure-1PSIDTS` included, so the Gemini session did not run out by its own dates: Google
  ended it); without one are ChatGPT's csrf token, callback url and four small ones, and Grok's
  `x-userid`, whose loss at a restart is the one thing still to see on a real login. One profile and one seed per provider, used by the login
  script, the drivers, the probes and the gate, is a plan of its own (it touches sessions: tier 1),
  chosen by the owner for after T4 (DECISIONS 2026-10-01). Where a saved session is opened today:
  the three drivers' `_ensure_page` (`worker/src/providers/chatgpt.py:297`, `grok.py:145`,
  `gemini.py:167`, each `cloakbrowser.launch(headless=True)` then `new_context(storage_state=...)`,
  and a `stop` that tries to save), `scripts/login_provider.py:139` (saves at :181),
  `tests/grok_probe.py:86`, `tests/gemini_probe.py:64,177,254,279,298`, and through the ChatGPT
  driver `tests/provider_probe.py:157` and `scripts/purge_test_residue.py:57`; the gate hands its
  own worker the same directory (`acceptance.py:1303,1348`). The unit tests replace `_ensure_page`
  with a fake page (`test_chatgpt_composer.py:238`, `test_grok_memory.py:206`,
  `test_gemini_driver.py:662`), so they cannot see a change inside it. `storage/` is git-ignored
- Not measured for the Gemini guard: the saved-info page with entries saved (an entry that brought
  a switch of its own would make the page read `unknown`, which does not block), both pages in a
  Vietnamese interface, and the new guard meeting personal context on (the reader before it did,
  in the real gate of 2026-09-29). Saved info on was met for real on 2026-10-02 at 01:26 (the
  plan's Evidence, its last paragraph): refused in 2.9s, the switch on for about 10 seconds with
  the owner's yes, read back off
- From the saved-info guard's tier 2 review (2026-10-02, non-blocking, not fixed; the reviewer's
  repros are in `/tmp/rv_gsi/`): (1) `_switch` turns any exception into `unknown`, so a bug of
  the driver's own inside the read fails open and only `memory: unknown` shows it (the old
  reader did the same); (2) `memory` keeps the earlier turn's reading when a turn stops before
  the look (`_open` refusing on Google's block page): not new, and `acceptance.py:1151-1153,
  1265-1267` reads `memory` without asking that its turn be done, relying on a fresh worker;
  (3) a profile holding two Google accounts may land under `/u/1/...`: both pages then read
  `unknown` after 30s and nothing blocks, even with both switches on (not measured; the login
  script signs in one account); (4) the look's worst case is about 151s where it was 75s (a
  load may take 60s and the wait 15s, per page), and nothing bounds it; (5) a switch painted
  off that turns on later than a poll after its first paint (the reviewer's 2s case) still
  reads `off`: the two polls close what is shorter than 0.5s, and the first sightings on the
  real site (saved info `true` at 21:08, personal context `on` at every look of the real gate
  of 2026-09-29) speak against anything longer, but the driver has never met either switch on
  since this guard; (6) `scripts/login_provider.py:51` proves a login on the settings page
  only: if Google ever asked for a sign-in on `/saved-info` alone, the worker would say
  "signed out" while the login script calls the session good; (7) `page.goto` with its
  defaults instead of `domcontentloaded` and 60s passes every test (the fake does not model
  load events)
- A Gemini turn stopped before its send still goes out: `gemini.py` `_run` checks for a stop only
  in the wait after `_send` (ChatGPT has not sent such a turn since 4536183). The look before
  speaking takes 2.6 to 4.4s since c1da860 (two settings pages), which is that much more time for
  a stop to arrive too early to be seen (read in the code on 2026-10-02, not measured)
- Gemini's own failure sentence passes for a reply: on 2026-10-01 a video script turn came back
  "I encountered an error doing what you asked. Could you try again?" in 70s, was shown as the
  answer and charged; asked again it wrote the script (same class as "a quota wall painted as an
  ordinary reply" in the Gemini plan's open points)
- From the session plan's tier 1 review (2026-10-01, non-blocking, not fixed, each with the
  reviewer's repro in `/tmp/rv_exp/`): (1) the profile's lock holds only while its holder answers:
  a holder frozen for 20s is killed by the next opener, which then opens (`e3_lock.py frozen`:
  "second: OPENED after 21.0s"); never two browsers at once, but not a loud refusal; and the lock
  is per host; (2) `pool.stop()` calls a driver's `stop` from another thread than the browser's
  (`worker/src/pool.py:111-117`): the close raises inside and is swallowed, an idle runner's
  browser lives until the process ends, a busy one loses its browser under the turn and its thread
  never returns (`e2_outer.py idle busy`); the next opener still opens and the cookie is kept, so
  shutdown loses nothing; the test's stop check is same-thread only; (3) a driver never recovers
  from a dead browser: `_ensure_page` hands the same dead page back and every job raises
  TargetClosedError until the worker restarts (`e13_dead_browser.py`; the same before the plan,
  but (1) is a new way to get there); (4) an aborted login leaves a profile with a seed and no
  session: `start` passes and only the per-turn guards refuse (ChatGPT "no session token", Grok
  401 or 403, Gemini signed-out), not checked on the real sites; a marker written once the login
  is real would close it; (5) "no saved session at <host path>" reaches the platform user as the
  job's error, as before the plan; (6) cloakbrowser updates its binary by itself
  (`CLOAKBROWSER_AUTO_UPDATE`, on by default), so the seed pins the device, not the browser
  build; (7) the in-use detection reads Chromium's "ProcessSingleton" wording, measured on macOS
  only; (8) `profile_of` does not confine a name (every caller passes a constant or a
  whitelisted argument); (9) the login script matches a cookie's domain by substring. From its
  two re-reviews (`/tmp/rv2_work/`, `/tmp/rv3_probe/`): (10) a seed of 4301 or more digits raises
  a ValueError of its own (`worker/src/providers/session.py:50`, `int()` outside the `try`);
  (11) two first logins of one provider started together: the loser reads the seed file before
  it is written and is told to move the profile away (293 of 1200 dead heats; never two
  devices); (12) a never-used profile directory holding a stray file other than `.DS_Store` is
  refused as "seed cannot be read", a seed unreadable by permissions is told the same, and "move
  the profile away" names no place (inside `storage/` is the safe one: only `storage/` is
  git-ignored); the login prints a traceback when the profile path is a file; `start()` passes
  on a seed that is no seed (the refusal comes at the first open); (13) with two matching
  cookies the throttle's mark is the oldest one's: a login that renews only the other was
  noticed 55s later on made-up domains, real Google behaviour unmeasured; (14) the source check
  for `create=True` is a text match (`create` as a keyword-only argument would close the other
  spellings); (15) the session check's word rule lets "pong 2026" or "好的：pong" pass and fails
  "pong pong" or "Pong! How can I help you today?" (a rerun, a real turn), and nothing runs its
  `--self-test` by itself; (16) survivors worth a test case: `.DS_Store` not exempt, `mkdir`
  without parents, `.strip()` removed, `startswith("pong")`, memory as a deny-list ("blocked"
  would pass)
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
- From the acceptance walk (2026-10-01), for the owner to decide: (1) **a new ChatGPT conversation
  asked "Tôi tên gì?" answered "Bạn tên là Keyti."**: the made-up name told in another conversation
  did not cross (memory read `off`), but the shared account's own identity reaches every platform
  user; where ChatGPT takes it from (the account's name, its personalization) is not traced;
  (2) Gemini's saved session was signed out twice in three days (2026-09-29, 2026-10-01; the file
  dates from 2026-09-29 21:28), and while it is, `/health` still says `ready: true` (`memory:
  signed-out`), so the web offers Gemini and every turn fails with an English admin instruction
  in the header ("run scripts/login_provider.py gemini"); credits come back; (3) the turn stopped
  2.5s after Send still ran at ChatGPT: the worker's result was refused afterwards
  (`results_refused` 0 -> 1), the known "a cancelled job still sends its prompt"
- From the UI polish reviews (2026-09-30, non-blocking, each reproduced by the reviewer's probe in
  `/tmp/rv_polish_*.py`): (1) the list's history step goes dead after a reload with the list open
  (pull-to-refresh on a phone): the reloaded entry keeps `{conversationList: true}`, the list comes
  back closed, and the first Back does nothing visible (`web/src/pages/Chat.jsx:187-198`); the
  design review's fix is one module-scope line, `if (window.history.state?.conversationList)
  window.history.back()`, not measured (the probe was declined); (2) Forward after Back re-enters
  that step with the list closed, same dead Back; (3) a list reopened within about 100ms of a close
  is closed again by the late popstate of the close's `history.back()` (`Chat.jsx:196`); (4) the list
  can answer an older search than the box shows, with "No conversation matches." under an empty
  box: nothing makes the latest answer win (`Chat.jsx:271-280`), and the refresh after a job uses
  the search of the moment of Send (`Chat.jsx:305`); both older than the note, which now says it
  aloud; (5) check 7 cannot see a form field's typed text, the select's shown option, the Lightbox,
  error texts or hovers other than a row's ✎ and × (all measured passing by the reviewers);
  (6) design: slate-600 gives the provider name, ✎ and × the same weight in a row, and the icons'
  hover steps shrank (✎ to slate-900 2.35:1, × to red-700 mostly hue): the reviewer suggests the
  provider name `text-xs` and `rounded hover:bg-slate-200` on the icons (`Chat.jsx:430-441`);
  (7) design: the active row and a hovered row share slate-100 (`Chat.jsx:416`); (8) design: the
  Vietnamese no-hit note leaves "nào." alone on a second line in the 256px sidebar (`text-balance`)
- Older, seen by the design review (2026-09-30): the gallery says "Gallery (0) / Nothing generated
  yet." before it has loaded (`web/src/pages/Gallery.jsx:40`); a long file name with no break
  point is cut at a phone's tile edge (`Gallery.jsx:51`, `[overflow-wrap:anywhere]`); Back leaves
  the app while a picture is open in the Lightbox (`web/src/components/Lightbox.jsx:7-13`); the
  phone nav's tap targets are small ("chat" 70x20, "gallery" 52x20, VI 34x22, `App.jsx:34`)
- A gate interrupted after its stack started prints every check as "stack did not start"
  (`acceptance.py:1311-1316`: `checks` stays empty when the interrupt lands inside `run_checks`),
  so its table misnames what happened; seen 2026-09-30 on the interrupted Grok run, where the
  stack was up and one job had run
- From the busy-runner review (2026-09-29): a heartbeat answered with anything but 200 neither
  pings nor sets lost, and a stuck driver keeps its provider looking served
- The composer's placeholder at 16px on a phone (measured 2026-09-29, `/tmp/nav_measure.py`): the
  English one needs 275px and has 267 at 390px, the Vietnamese one needs 317 and has 278 (it needed
  283 at 14px, so it was cut before too)
- On a phone the header's title gives way to the select: while a provider is unserved its
  "(unavailable)" labels widen the select to about 182px at 390px, leaving the title about 112px
  (about 42 at 320)
- From 640px the nav shows the brand and the email while the chat keeps its phone layout up to
  767px; in Vietnamese with a long email the nav wraps at 768-800px, and a header error takes its
  own row at 768px (code review, 2026-09-29)

## Active plan

**None armed.** The last one, `docs/agent/plans/2026-10-01-gemini-saved-info-guard.md` (base
a0d04b0), closed on 2026-10-02 at e64575a, the marker removed after a clean audit (4 commits
inside the radius), its Evidence written. Task log, kept below.
Tier 2, three tasks, approved by the owner on 2026-10-01 ("Duyệt, làm ngay, tier 2"): before
every Gemini turn the driver reads both of the account's memory switches, personal context on
`/personalization-settings` and saved info on `/saved-info`, in one tab of its own; saved info on
refuses the turn as `provider_misconfigured`, naming it; a saved-info page that cannot be read
reads `unknown` and does not block; health's `memory` says `off` only when both read off. A
switch is told by its page and by being the only one there, never by its words (the labels follow
the interface's language). Radius: `worker/src/providers/gemini.py`,
`tests/test_gemini_driver.py`, `docs/research/2026-09-27-gemini.md`.

- [x] T1 red checks, the fake's second page, the research note |
  `~/cloakbrowser-env/bin/python tests/test_gemini_driver.py`: **66/83** on a0d04b0's driver, exit
  1 (`/tmp/gemini_driver_t1_red.log`): the 62 existing checks green (two of them now ask through
  `_guard()` and `memory`, green before anything else changed), 17 of the 21 new ones red, each
  because `/saved-info` is never loaded ("loaded ['personalization-settings']", memory `off`, the
  turn sent), 4 green as guards (a first page that refuses loads nothing more, three ways; the
  tab closed whatever was found); the research note has the page's measurements
- [x] T2 the guard reads both switches | `tests/test_gemini_driver.py` **83/83** exit 0;
  `python acceptance.py` **39/39** exit 0; `tests/test_session_profile.py` 12/12; c1da860.
  `_read_personal_context` is gone: `_switch(page, url, own)` reads one page's one switch and
  `_guard` loops over `MEMORY_SWITCHES` in one tab (the host worker was restarted on the new
  code in T3)
- [x] T3 review, mutants, the full gate, the real turn, Evidence | **done 2026-10-02 01:10.** In
  order:
  **20 of 20 mutants red at ce82755**, each on its own check (`/tmp/run_gemini_saved_info_mutants.py`,
  log `/tmp/gemini_saved_info_mutants.log`: the plan's eight and twelve more; the first run had
  one mutant stop the test run instead of failing a check, so two checks now catch a refusal and
  report it, ce82755, `tests/test_gemini_driver.py` 83/83). **The guard alone on the real profile
  at ce82755, 00:02 on 2026-10-02, the host worker stopped, no turn sent
  (`/tmp/gemini_guard_probe.py 2`): look 1 "would send in 4.4s, memory 'off'"
  (`/personalization-settings` off in 2.6s, `/saved-info` off in 1.5s), look 2 in 2.6s (1.1s and
  1.4s), one tab open after each look (the settings tab closed), exit 0**; the profile was still
  signed in 3h46 after its login. **The host worker runs in real mode on ce82755 since 00:04**
  (`PROVIDERS=chatgpt,grok,gemini`, all three ready). **The tier 2 review (one round, a separate
  reviewer, 80 tool uses, read-only, pages on 127.0.0.1 only): nothing blocking, 8 non-blocking
  points, 26 of its 36 mutants through the tests.** **Fixed in e64575a, red first (97/110 on
  ce82755's driver, 13 checks, `/tmp/gemini_driver_fix_red.log`):** a switch is read only on
  `gemini.google.com` itself (a page on another host with the same path read `off` before);
  `off` is believed only when two polls in a row say so, `on` at once (one first sighting cannot
  rule out a default shorter than a poll; costs 0.5s a page); a value that is neither keeps the
  look waiting. The tests gained the reviewer's holes: late paint (7s, 10s each page), the first
  page unreadable in five ways, the tab (a closed one loads nothing, one that will not close, a
  browser that opens none), the call site (a reopened thread, a picture not handed over before
  the look), redirects that come back on either load, a slash or a query after an address, the
  refusal's words; the fake answers only `button[role="switch"]`. `tests/test_gemini_driver.py`
  **111/111**. **59 of 61 mutants red at e64575a** (`/tmp/run_gemini_saved_info_mutants.py`, log
  `/tmp/gemini_saved_info_mutants.log`): the plan's 20, the reviewer's 36 carried over, 5 for the
  round's own fixes; not red: S02 (`goto` with its defaults: the fake does not model load
  events, left as it is) and T03 (a wait that never ends hangs the run, no named check). Parked
  from the review: Parked questions. **The guard alone on the real profile at e64575a, 00:53
  (the worker stopped, no turn): look 1 "would send in 4.5s, memory 'off'" (2.2s and 1.8s),
  look 2 in 3.5s (1.7s and 1.5s), one tab open after each, exit 0.** **Full gate once at
  e64575a, clean tree, the host worker in mock (00:54 to 01:01): `python acceptance.py` 39/39
  exit 0, build exit 0, ui_smoke 53/53 exit 0.** **The host worker back in real mode at e64575a
  (01:02), then one real turn: `python tests/session_check.py gemini --keep`: "[PASS] gemini
  answers  done in 18s, reply 'pong', worker mode real, memory off", 1/1, exit 0** (its
  conversation kept: one more "pong" in the Gemini account). The audit clean, the marker
  removed, the Evidence written. **Pushed at 01:12 with the owner's yes.** Afterwards, with the
  owner's "Cho làm": the saved-info switch on for about 10 seconds, the worker stopped
  (`/tmp/gemini_saved_info_on_check.py`, 01:26): the driver's look "REFUSED
  (provider_misconfigured): the shared Gemini account has saved info switched on ..." in 2.9s,
  memory 'on'; off again, a fresh load `false`, the next look "would send", memory 'off'. The
  research note records it (302a274); full gate once more at 302a274 (39/39, build exit 0,
  ui_smoke 53/53); pushed at 01:36; the host worker back in real mode

The one before, `docs/agent/plans/2026-10-01-one-profile-per-provider.md` (base
db429a1), closed on 2026-10-01 at a0d04b0, the marker removed after a clean audit (7 commits
inside the radius), its Evidence written: the full gate once at a0d04b0 39/39, build exit 0,
ui_smoke 53/53; three of its real lines NOT PASSED as written (the survival check's "3/3 every
time": Gemini passed every time, ChatGPT until Cloudflare's check, Grok never; the real gate
29/30 on an outdated check; the stop probe, Cloudflare). Task log, kept below:
Tier 1, five tasks, approved by the owner on 2026-10-01 ("Duyệt, check tự xoá"): a provider's
session is a browser profile `<sessions>/<provider>/` with a device seed drawn once and kept in
it, opened by the login script, the three drivers and the two probes through one function; a
second browser on an open profile is refused in words; what a browser learned outlives a killed
worker; after the owner's logins each provider still answers after four launches over two hours.
The real runs are the owner's "Vừa đủ" set, and they carry the hold-and-stop plan's two lines.
`tests/session_check.py` deletes the conversations it made (the owner's yes).

- [x] T1 red tests and the check script | `tests/test_session_profile.py` **1/8** on db429a1
  (checks 1 to 7 red: no launch names a seed and three launches read the GPU as M1, M4 Pro, M1
  for chatgpt, M4, M4 Pro, M4 for grok, M1, M1, M1 Pro for gemini; no seed file; the killed
  worker's cookie lost; the second browser opened; `start` passed on the old state file; check 8
  green as a guard); `tests/test_login_provider.py` **5/7** (opened by its own launch,
  `grok.json` written; no refusal); `tests/session_check.py` on the mock worker: `chatgpt grok`
  1/2 exit 1 ("no worker serves it"; while the api still counted the stopped Grok worker inside
  its 310s window, "pending in 241s"), `chatgpt` 1/1 exit 0, no invite code exit 1; the probe
  without an account (`/tmp/browser_kill_probe.py`): the browser's own six processes killed
  leave three stale lock files, the next launch opens in 3.3s, and a cookie set 3s before that
  kill is lost (the worker's own death, measured before, loses nothing); 5d6f532
- [x] T2 the profile and the seed in the drivers | `tests/test_session_profile.py` **8/8** (each
  driver named its own seed at three launches, 18417, 71385 and 54730 in that run, and read one
  GPU each, M2, M4 Max, M2 Max; a seed written before the first launch used; the killed
  worker's cookie there at the next open; the second browser refused, "the chatgpt session is
  open in another browser (a worker, a gate, a probe or the login script); stop that one
  first"; no profile says so at start); composer 22/22, grok memory 20/20, grok settle 8/8,
  gemini driver 62/62, liveness 4/4; `python acceptance.py` 39/39; d30caa0. **The host worker
  still runs the code it loaded before (Grok from its state file); started again on this code
  it serves nothing until the owner has logged in to each profile**
- [x] T3 the login script and the probes on the same profile | `tests/test_login_provider.py`
  **8/8** (5/8 red first: opened by its own launch and `grok.json` written; no refusal; a
  ChatGPT cookie answered 401 taken for a sign-in), one check more than planned: a profile keeps
  the cookie of a session its site has ended, so the script now asks ChatGPT's account
  (`/backend-api/settings/user`, with the session's token, inside the page) before it calls a
  login real (DECISIONS 2026-10-01); both probes compile and, before any login, end with "no
  session at .../storage/sessions/<provider>; run scripts/login_provider.py <provider>", exit
  1; 5ac5ebe. Their no-turn modes on a real profile wait for T5
- [x] T4 review (tier 1), mutants, re-review, full gate | **0 blocking after three review passes
  (db429a1..3b6db80: 1 blocking, fixed in 8e0d55a; 8e0d55a: none; 171b7b7: none, "the first
  login still works", a race of two draws 0 of 1200 at 171b7b7 against 13 at 8e0d55a); 50 of 50
  mutants red at 171b7b7; full gate once at 171b7b7: 39/39, build exit 0, ui_smoke 53/53.** The
  last pass's non-blocking points are in Parked questions; five of its surviving mutants got a
  test case in a0d04b0 (tests only: session profile 12/12, the verdict table 23/23; R1 to R5
  red, `/tmp/session_mutants_r.log`). In order: one check added first, "a
  driver does not make a profile that is not there" (session profile **9/9**; today's tests on a
  copy of db429a1's code: 1/9 and 5/8, every new check red, `/tmp/run_session_mutants.py --old
  db429a1`), 3b6db80; **14 of 14 mutants red on 3b6db80**, each on its own check
  (`/tmp/run_session_mutants.py`, log `/tmp/session_mutants.log`: M1, M1b, M2 to M13). **The tier
  1 review (a strong model, risk lens, 99 tool uses): 1 blocking, 9 non-blocking, and 13 of its
  15 mutants went through the tests.** Blocking: `tests/session_check.py` passed on a mock worker
  (its echo holds the word, health's mode never read), so the instrument of "Done 4" could lie.
  **Fixed in 8e0d55a, each seen red first:** the check passes only on a worker in real mode that
  read the account's memory as off and got the word alone (on the mock worker: FAIL 1/2 exit 1,
  `--mock` 2/2 exit 0; PASS before); only a login draws a seed: a profile whose seed is missing,
  empty, words, negative, zero, underscored or thirty digits long is refused in words, no launch,
  the file untouched (before: a new device drawn silently, or a ValueError), and an empty
  directory is no session at `start`; the login script asks Google's settings page for one cookie
  at most once a minute (a profile keeps an ended session's cookie: the tab opened 34 times in
  five minutes before, 5 now, and a proof that missed is asked again 66s later); the Gemini
  probe's look without an account runs on a thread of its own (on a local stub, `/tmp/probes_on_stub.py`:
  "5 probe(s) ran, 1 crashed: session" before, 0 crashed now; the Grok probe 0 crashed). Session
  profile **11/11**, login provider **10/10**, composer 22/22, grok memory 20/20, grok settle
  8/8, gemini driver 62/62. **34 of 34 mutants red on 8e0d55a**, each on its own check: the 10
  of the login script and the 24 that need the browser (`/tmp/session_mutants_profile.log`), the
  plan's M1 to M13, the reviewer's fifteen (the 13 that had gone through among them) and six for
  the round's own fixes (MN1 to MN6). **The scoped re-review of 8e0d55a (88 tool uses): nothing
  blocking; the blocking finding, the probe and the throttle closed** (the check's verdict over 39
  scripted rows, 0 wrong; the throttle on a real headless browser: one settings tab in 16s of
  polling an ended session, cookie order stable over 15 reads), one part open (a seed that is
  not plain text raised an error of its own), a new non-blocking one (a login drew a new seed
  into a used profile whose seed file was gone: 10971 in place of 34073, the cookies kept) and
  ten more mutants through the tests. **Fixed in 171b7b7, red first** (session profile 11/12 on
  8e0d55a, exactly those three cases: UnicodeDecodeError, ValueError, "OPENED, seed file None
  then 88212"): a login draws only into a profile no browser has used, with an exclusive write;
  a seed must be plain digits in range. The session check carries its verdict's table
  (`--self-test` **21/21**). Session profile **12/12**, login provider **10/10**. **Full gate
  once at 171b7b7, clean tree: `python acceptance.py` 39/39 exit 0, build exit 0, ui_smoke 53/53
  exit 0.** **50 of 50 mutants red at 171b7b7**, each on its own check: the 15 that need no
  browser (the login script's ten, five of the verdict) and the 35 that do
  (`/tmp/session_mutants_a.log` 17 of 17, `/tmp/session_mutants_b.log` 18 of 18): the plan's
  thirteen, the first reviewer's fifteen, the re-reviewer's eight that needed a test, and nine
  for the two rounds' own fixes. A short re-review of 171b7b7's own diff is running. **No worker
  runs now**: the mock one was stopped after the gate. **The owner logged in to all three
  profiles on 2026-10-01: Grok 20:13 ("sso-rw and /rest/app-chat/conversations answered"),
  ChatGPT 20:14 ("session-token.0 and /backend-api/settings/user answered", the new proof's
  first real run; the profile holds a `cf_clearance`), Gemini 20:16 ("__Secure-1PSID and
  .../personalization-settings stayed put")**; no real turn has been sent since
- [x] T5 the owner's logins and the real runs, Evidence | **done 2026-10-01 22:45** (the
  survival's last check at 22:31: gemini PASS 36s, its profile's seventh launch, 2h15 after its
  login; the final full gate at a0d04b0 39/39, build exit 0, ui_smoke 53/53; the host worker
  left on `chatgpt,gemini`). Logins
  20:13 Grok, 20:14 ChatGPT, 20:16 Gemini. **Gemini's settings, read only, 20:25 (the profile's
  first launch after the login, `/tmp/gemini_settings_sweep.py`)**: signed in, account
  `ke***2@gmail.com`, plan PRO (usage 0%), personal context `false` (the switch turned off at
  15:49 held through the sign-out and the new login), activity retention "On", the Google
  Workspace app `false`, 5 of the 23 other apps on (names not read: every switch carries the
  same label), **the saved-info switch `true`** with no entry saved (only "Add"), the sidebar
  0 rows (not traced; the activity page lists today's turns). **Worker start 1 at 20:27, all
  three; `tests/session_check.py chatgpt grok gemini` 3/4, exit 1**: chatgpt PASS (26s, "pong",
  memory off, no bot check), gemini PASS (14s, "pong", memory off), **grok FAIL: "the shared
  Grok account has memory switched on, so this turn was not sent", memory on** (the new Grok
  login's account; the guard's own refusal), the deletion row PASS. **The hold, seen on a real
  account for the first time**: 30s later `GET /providers` said grok `served: false`, a new Grok
  turn answered 503, quota 100 -> 100. **Gemini recall (`/tmp/recall_check.py gemini --keep`,
  three turns)**: told "violet-61338" (19s), a new conversation answered "Unknown" (39s), its own
  thread "The word is violet-61338." (17s): no leak, the thread reopened. **Item 8
  (`/tmp/e2e_gemini_item8.py`)**: chat 18s "Hà Nội", a picture 44s 1024x559, quota 100 -> 97, no
  console error; **its video script check passed on Gemini's own error sentence** ("I
  encountered an error doing what you asked. Could you try again?", 70s, charged): the check
  asked for 40 characters, now 200 and not that sentence; asked again through the api the same
  picture gave a script of 661 characters in 60s. **Gemini's apps by name, read at 20:58 with
  the worker stopped (`/tmp/gemini_apps_read.py`, the profile's third launch, 42 minutes after
  the login, still signed in)**: on are YouTube, Gemini Notebook, Google Flights, Google Hotels
  and Verify AI; off are Google Workspace, Search services, Google Photos, a second YouTube
  entry, YouTube Music, Google Ads, Google Business Profile, Google Play, GitHub, Adobe, Canva,
  Dropbox, Granola, Monday.com, Wispr, Wix, Contacts, Apartments.com and Fever; the saved-info
  page shows its switch on and no entry with controls of its own after the recall test. **The
  real ChatGPT gate started at 20:59 at a0d04b0 with the host worker stopped**
  (`/tmp/chatgpt-real-gate-a0d04b0.log`, workspace `$TMPDIR/ai-platform-acceptance-hye7088z`).
  **The gate's result, 20:59 to 21:19: 29/30 PASSED, 9 skipped, exit 1, no bot check in twenty
  minutes and sixteen jobs.** Green on the real account: the chat job, the picture job that
  failed at 16:37 (823709 bytes, 5m12s), the video script (807 chars), a thread reused and not
  crossing conversations, two zips, the follow-up that failed on Cloudflare at 16:45 (a zip of
  the picture, 51s), the thread deletion that answered 403 then ("its own thread deleted"),
  memory off, the code version a0d04b0, and **"a running job can be cancelled": "cancelled
  while running, credit returned, at the site {'sent': False, 'pressed': False}"**, the
  hold-and-stop plan's line: the cancel reached the driver before the send. **The one red:
  "deleting a conversation cancels its running job and refunds": "seen running delete 204
  final cancelled media None quota 90 -> 90 new files [] a new thread removed False"**. The
  check still asks for a thread to be removed from a turn deleted while running
  (`acceptance.py:763-770`); since 4536183 the driver does not send such a turn, so the worker
  reported no thread (no new tombstone in the run's database) and there was nothing to remove.
  That the turn was not sent is read from the cancel check of the same run (`sent: False`),
  not from that job's own record, which the gate does not keep. The gate is outside this
  plan's radius: the line stays NOT PASSED as written, the check's fix is parked.
  **Worker start 2 at 21:21, all three; the session check 3/4, exit 1**: chatgpt PASS (20s),
  gemini PASS (34s, the profile's fourth launch, 65 minutes after its login: past the 47
  minutes the afternoon's login lived), **grok FAIL: "grok never opened a thread for this turn"
  after 56s**, memory off this time (`last_open`: composer true, landed on https://grok.com/).
  **Grok, looked at without sending (`/tmp/grok_look.py`, 21:24, picture `/tmp/grok_look.png`)**:
  a brand-new account ("key ti", 0 conversations, the free tier's "Upgrade"), another page than
  the old account's: the composer's placeholder reads "Type @ to search your apps (AI Agent)", a
  "Meet Grok Bot" popover and a cookie banner are up, the composer is the ProseMirror the
  driver knows. **The probe's own turn (`tests/grok_probe.py turn`, 21:25, its first run on a
  profile)**: the thread's address after 3s (`/c/64e4a6f6-6ead-412a-816f-f8e2b186af50?rid=...`),
  the server's word after 85s, "pong", the thread there after a reload, a websocket
  `wss://grok.com/ws/mgw/` open during the turn, quota 7 of 7 before and after. **A second
  turn through the platform at 21:27 (the worker's third start): "grok answered with nothing:
  Please try again soon, or upgrade for higher priority access"**, the free tier's wall. So
  Grok's session lives in its profile through every restart (its endpoints answered at 21:07,
  21:08, 21:24, 21:25, without the `x-userid` cookie that a restart drops) and its memory is
  off, but no Grok turn has finished through the platform on the new account: one never opened
  a thread (not traced: the record names nothing more), one was walled. The stopped-turn check
  was not run. Grok threads left in the new account: 64e4a6f6-... (the probe's "pong") and
  whatever the walled turn left.
  **The stop probe (`/tmp/stop_probe.py after`, 21:50, the worker stopped): NOT PASSED. Its
  first turn, the long text, failed in 15s with "the provider showed its error banner:
  cloudflare_challengeRetry"**, Cloudflare's check again, now on the pinned device: after the
  first session check (20:27), the twenty minute gate (16 jobs) and the second check (21:21)
  had all gone through. Its report is empty (`/tmp/stop_probe_after.json` `{}`), so whether that
  first turn left a thread is not known. By the plan's rule ChatGPT's runs stopped there.
  **Worker start at 21:52 (the evening's fourth), the session check for gemini and grok only
  (ChatGPT left alone after its bot check): 2/3, exit 1**: gemini PASS (23s, the profile's
  fifth launch, 1h36m after its login), **grok FAIL: "the turn never reached grok's composer"
  after 238s**, memory off: a third failure on the new Grok account's page (the driver reads the
  composer back before it sends and found the turn missing), where the probe's own plainer send
  had worked once. Grok's runs stopped there as well.
  **The two switches, with the owner's "Cho tắt" for each (21:06):** Gemini's saved info
  turned off at 21:08 (`/tmp/gemini_saved_info_off.py`: `true`, pressed, no dialog, `false`
  after a fresh load); Grok's memory read `false` already at 21:07 (`/tmp/grok_memory_off.py
  --read`: `enableMemory` false, `allowXPersonalization` false), so nothing was changed there;
  the driver had read it on at 20:27, and who turned it off is not on record. (The script's
  first read took a body cut at 600 characters for no settings at all and so pressed nothing:
  the reader now takes the whole answer.) The driver does not read Gemini's saved-info switch:
  parked. Still to do: ChatGPT's real gate and stop probe, the
  Grok checks once its memory is off, starts 2 to 4 with the session check, the end's full gate,
  Evidence. Prepared: ACCESS.md says where a
  session lives; `/tmp/gemini_settings_sweep.py`, `/tmp/stop_probe.py` and
  `/tmp/picture_send_probe.py` open the profile; `/tmp/recall_check.py` written (three turns
  through the platform). The repo's CLAUDE.md line on sessions is outside the radius (the fence
  refused it): to be written once the marker is removed

Set aside on 2026-10-01 at db429a1, the marker removed with the owner's yes, its Evidence written
(full gate once at db429a1: 39/39, build exit 0, ui_smoke 53/53; every offline suite green; the
audit clean, 5 commits inside the radius; the two real ChatGPT lines NOT PASSED and carried to
the session plan): docs/agent/plans/2026-10-01-hold-misconfigured-and-real-stop.md, base a8b5302.
Tier 2, four tasks, approved by the owner on 2026-10-01: a turn failing as
`provider_misconfigured` holds its provider out for 10 minutes (served false, 503 uncharged, waiting
jobs refunded) and the web shows the unavailable notice; every runner learns of a cancel within 5s;
ChatGPT never sends a cancelled turn and presses its stop button on one already sent. The probe
may delete its own threads (the owner's yes).

- [x] T1 red checks and the real measurement | `python acceptance.py` 37/39 (held provider still
  served and a new turn 202 and charged; the job behind it done, attempts 1; "a hold ends by itself"
  green as a guard); liveness 3/4 (420s lease: the driver never told within a 3s turn, no cadence
  constant); composer 19/21 (a stopped job's turn sent; the stop button never pressed);
  ui_smoke 52/53 (no notice, the admin's English text in the header in both languages); the real
  probe on today's driver (`/tmp/stop_probe.py before`, ChatGPT off the host worker): the stop
  button is there at once after the send for a text and a picture; pressed at 5.8s the text stopped
  at 792 chars (none added in 10s, the server calls it finished_successfully, 841 chars); pressed
  at 9.9s no picture arrived in 120s; both threads deleted (True); 6bc040d
- [x] T2 the hold | `python acceptance.py` 39/39 (not served right after the refusal, grok still
  served, a new turn 503 and uncharged; the job behind it failed at once, never claimed, quota
  95 -> 94; served again 4.2s later, an ordinary turn done); ui_smoke 53/53 (the notice in English
  and Vietnamese, no header error, no admin text); `npm run build` exit 0; fcf1a06
- [x] T3 stop | liveness 4/4 (cadence 5.0s shipped; with a 420s lease the driver told to stop
  0.52s into a 3s turn); composer 21/21 (stopped before the send: nothing typed, last_stop sent
  false; stopped while writing: the stop button pressed once, last_stop pressed true);
  `python acceptance.py` 39/39; 4536183. The `.env.example` and `api/src/config.py` comments on
  the beat corrected with it
- [ ] T4 review, mutants, full gate, real gate, real probe, Evidence | **SET ASIDE: the real gate
  and the real probe are NOT PASSED and move to the session plan**; the review, the mutants, the
  full gate (once more at db429a1) and the Evidence are done. Its history: first blocked on the
  owner's ChatGPT login, everything else done at 482413e. Done: the code review (tier 2), 0 blocking, 10
  non-blocking; its fixes in 482413e (a stopped job attaches no picture; Grok signed out only on
  401 or 403, and its stop waits for the thread's address, with the radius widened to
  `worker/src/providers/grok.py` and `tests/test_grok_memory.py` on the owner's yes; the gate's
  hold checks tightened); composer 22/22, grok memory 20/20 (17/20 red first), grok settle 8/8,
  liveness 4/4; **15 of 15 mutants red** on 482413e, each on its own check
  (`/tmp/run_hold_stop_mutants.py`, logs `/tmp/hold_stop_gate_mutants.log`); **full gate once at
  482413e, clean tree: 39/39, build exit 0, ui_smoke 53/53**; the real Grok check
  (`/tmp/grok_stop_check.py`, two turns through the platform): a plain turn done in 25s ("Paris"),
  a turn stopped 8s after its send: the worker's result refused 4.1s after the stop, the new
  chat's thread stored for its conversation. **Not run:** the real ChatGPT gate (started, its
  first three turns failed "the provider rejected a fresh session token; the session is logged out
  or expired", the run's own job records in `$TMPDIR/ai-platform-acceptance-snmfc5q1`, so the
  agent interrupted it); `/tmp/stop_probe.py after` (same session); the real Gemini hold (the
  owner declined the call). The owner's new ChatGPT login was then not saved: the login script
  waited for the plain cookie name while chatgpt.com keeps it in chunks; fixed in db429a1 with
  the radius widened to `scripts/login_provider.py` and `tests/test_login_provider.py` on the
  owner's yes (`tests/test_login_provider.py` 5/5, red first). **The real gate on the new login
  (2026-10-01 16:35 to 16:48, db429a1, `python -u acceptance.py --real --keep`, workspace
  `$TMPDIR/ai-platform-acceptance-4e01f7i4`, log `/tmp/chatgpt-real-gate-db429a1.log`): NOT
  PASSED, interrupted by the agent.** Its own database: 10 jobs, 7 done (pong 22s; a word
  recalled in its thread and not in another conversation; two zips, 30s and 36s; a picture asked
  for in a chat turn, done after 317s, its media row there until the gate deleted the
  conversation), 2 failed, 1 cancelled by the gate's own delete check. The failures: the first
  picture job at 16:37, `worker_error`, "TimeoutError: Locator.inner_text: Timeout 30000ms
  exceeded ... waiting for locator(div.ProseMirror[contenteditable="true"], #prompt-textarea)"
  41s into the job (`chatgpt.py` `_send` reads the composer at :418, :420, :430 and :443; which
  one is not on record, so whether the prompt went out is not known); and at 16:45 the follow-up
  turn in the picture's thread, `provider_error`, "the provider showed its error banner:
  cloudflare_challengeRetry", after which the thread's deletion failed too
  (`thread_tombstones.error`: "thread 6abe2a6d was not deleted: server status 403"). The memory
  reading was `off` before the first turn. The table printed 0/39 "stack did not start" (the
  known defect of an interrupted gate). The first interrupt went to the shell wrapper instead
  of the gate's python (`pgrep -f` matched both), so the gate ran one minute longer and started
  its delete-while-running job, cancelled in the same second. The cancel check never ran.
  `/tmp/stop_probe.py after` NOT RUN: three more turns into a session Cloudflare is checking is
  not done. `/tmp/picture_send_probe.py` (not run) samples the composer after a picture prompt,
  for the first failure. **To close the plan** once ChatGPT answers again: restart the worker,
  `python acceptance.py --real --keep` with ChatGPT off the host worker, `/tmp/stop_probe.py
  after` (three turns, the driver pressing stop, its threads deleted with the owner's yes), then
  the Evidence, the marker removed, HANDOFF

The previous one, `docs/agent/plans/2026-09-30-ui-polish.md` (tier 2, three tasks), closed on
2026-09-30 at a8b5302: Back closes the phone's open list and every other close takes its history
step out, "chat" in the nav closes it, an empty list or a search with no hit says so (in a live
region, only once the list has answered), the provider select is named, and every text and
placeholder meets WCAG AA, pinned by seven new ui_smoke checks (52/52). Its Evidence holds every
number. Task log:

- [x] T1 red checks | `tests/ui_smoke.py` 46/52, exactly checks 1, 3, 4, 5, 6 and 7 red, check 2
  green (a guard): Back lands on `about:blank#before`; the list stays open after "chat"; no note
  empty or on a miss; the select named None, then by its lock sentence; 68 faint texts on 14
  screens (265 measured): the typing timer 2.56, a hovered × 4.41 (both measured now), placeholders
  2.54, slate-400 2.34 to 2.56, the badge 4.34; 7c65e54
- [x] T2 the fixes | `tests/ui_smoke.py` 52/52 (267 texts on 14 screens, 0 under the floor; Back
  stays on the app; each close lands Back on `about:blank#before`), `npm run build` exit 0,
  `python acceptance.py` 36/36; 374deec (a one-line comment trimmed after the ui_smoke run)
- [x] T3 review, design review, mutants, full gate, Evidence | code review: 1 blocking (a new
  person's first message showed "No conversations yet." beside it for the whole first reply),
  8 non-blocking; design review: 0 blocking; fixed in a8b5302 with the note in a live region and
  `window.history`, the new ui_smoke red on 374deec's web for exactly those holes (51/52); 14 of
  14 mutants red on a8b5302; full gate once 36/36 + build + ui_smoke 52/52; before and after
  pictures sent to the owner; host worker back to real, all three

The previous one, `docs/agent/plans/2026-09-30-chatgpt-delete-token-wait.md` (tier 3, three
tasks), closed on 2026-09-30 at 94efd1f: ChatGPT's `delete_thread` reads the session token again
every second for up to 20s before it calls the session logged out (composer test 19/19, red first
18/19; 3 of 3 mutants red; the real after-count not run, the owner declined it). Its Evidence
holds every number.

The previous one, `docs/agent/plans/2026-09-30-gate-checks-measure-the-thing.md` (tier 2,
three tasks), closed on 2026-09-30 at 89e8beb: a deletion check passes only when the worker's own
count grew and the api's record shows a tombstone new since the delete, for this thread, claimed
by the worker and settled; "threads never cross conversations" only on a finished, non-empty
reply. Its Evidence holds every number. Task log:

- [x] T1 red evidence | the mock gate on a copy whose api tombstones another url
  (`/tmp/run_gate_mutant.py`): the old deletion check PASS "0 -> 1", 36/36, while the
  conversation's own thread was never deleted; the old cross-conversation rule replayed on the two
  failed Gemini runs (`/tmp/replay_cross.py`): PASS on a failed, empty turn, the new rule FAIL, both
  PASS on the green run; no repo file changed, nothing to commit
- [x] T2 the checks | `python acceptance.py` 36/36 exit 0 ("its own thread deleted" twice); the
  wrong-url copy with the new gate: the deletion check red, 35/36; 4ab53de. The cancel check's wait
  now runs only when its turn was sent (it waited 150s for nothing on grok real runs)
- [x] T3 review, mutants, full gate, Evidence | review (tier 2): one blocking finding, the first
  version trusted the api's `deleted_at` alone (an api settling its own tombstones read 36/36);
  fixed in 89e8beb and proven: that mutant now red on both checks (33/36), the wrong url red, no
  tombstone for a cancelled turn red, a missing database path red without crashing the gate; full
  gate once 36/36 + build + ui_smoke 45/45; host worker back to all three

The previous one, `docs/agent/plans/2026-09-29-busy-runner-keeps-alive.md` (tier 2, three
tasks), closed on 2026-09-29 at 34b533c: a busy runner pings every 5s while it deletes a thread and
while it finishes a cancelled job; the Gemini real gate went from 20/25 to 25/25. Its Evidence holds
every number.

The previous one, `docs/agent/plans/2026-09-29-first-open-and-refusal-probe.md` (tier 2, three
tasks), closed on 2026-09-29 at 3e32a12: a late ChatGPT composer gets a second load before the
driver gives up (home and a stored thread that exists), a picture of the page is kept under
`storage/diagnostics` when it still does, and the gate's refusal probe skips only a picture that is
gone. One acceptance line not run yet: the Grok real gate (Next steps 0). Task log:

- [x] T1 red checks | `tests/test_chatgpt_composer.py` 12/15, exactly the three new checks red:
  one load of the home page, one load of a stored thread that exists (status 200), no picture;
  1e260f3
- [x] T2 the fixes | `tests/test_chatgpt_composer.py` 15/15; `python acceptance.py` 36/36 exit 0;
  8420e40. The third Gemini real gate (new account, switch off) hit the refusal defect too
  (video 404), with the old gate loaded
- [x] T3 review, mutants, the real ChatGPT gate, Evidence | review (tier 2): nothing blocking; its
  test holes closed in 3e32a12 (17/17; the plan's 3 mutants and the review's M4, M5, M6, M8, M9 all
  red, M4 being a fall back to a new chat); the gate's video probe skips only on 404 (mock gate
  36/36, "video 503"); ChatGPT real gate 30/30 at 3e32a12 (the first open took 27s, no second load
  needed that run); full gate once 36/36 + build + ui_smoke 45/45; host worker back to all three

The previous one, `docs/agent/plans/2026-09-29-reply-blocks-and-file-card.md` (tier 3, three
tasks), closed on 2026-09-29 at bbb3924: replies without blank lines between blocks, file cards
inside their gallery tiles. Its Evidence holds every number.

The previous one, `docs/agent/plans/2026-09-29-view-follows-tail.md` (tier 3, three tasks), closed
on 2026-09-29 at 9d3a60b: the chat view keeps its tail by intent, pictures and a shorter area
included. Its Evidence holds every number.

The previous one, `docs/agent/plans/2026-09-29-mobile-layout.md` (tier 2, three tasks), closed on
2026-09-29 at ab8e210: the web on a phone (the list behind "☰", 16px fields, bubbles that keep long
links, a one row nav from 360px). Its Evidence holds every number.

The previous one, `docs/agent/plans/2026-09-29-served-providers.md` (tier 2, four tasks), closed
on 2026-09-29 at a4a36f3: `GET /providers` and a 503 uncharged refusal for a turn nobody serves,
and the web greying such a provider out. Its Evidence holds every number.

The previous one, `docs/agent/plans/2026-09-28-runner-stop-event.md` (tier 3, two tasks), closed
on 2026-09-28 at 26dc5fc: the runner's stop Event is `_halt`, so an ended runner answers
`is_alive()`, `snapshot()` and `join()` instead of raising `TypeError: 'Event' object is not
callable` and taking `/health` down. `tests/test_runner_health.py` 4/4 (red first 0/4), the mutant
red, full gate once 34/34 + build + ui_smoke 25/25, the real worker's `/health` shows all three
runners alive. Its Evidence holds every number.

Before it, `docs/agent/plans/2026-09-27-grok-memory-guard.md` (tier 2, three tasks),
closed on 2026-09-27 at 20f1aad: the Grok driver reads `enableMemory` (`GET /rest/user-settings`)
before every turn and refuses while it is on; with memory off a two-turn leak test came back
"Unknown"; grok is back on the host worker. Its Evidence holds every number. Task log:

- [x] T1 red tests and the measurement | `tests/test_grok_memory.py`: 0/12 on the current driver
  (no memory read; a turn with memory on is sent; `memory` is None); the research note records the
  switch, the endpoint and the change; 2622880
- [x] T2 the driver and the gate | `tests/test_grok_memory.py` 12/12, `tests/test_grok_settle.py`
  8/8, `python acceptance.py` 34/34 exit 0; mutants (`/tmp/run_grok_mutants.py`) 5 of 5 red: the
  read removed, the key misread, on still sending, unknown blocking, the refusal as provider_error;
  7555b93
- [x] T3 review, real leak test, Grok back, Evidence | tier 2 review: nothing blocking, four test
  gaps closed in a9e03c1 (17/17, 9 of 9 mutants red); two real turns through the driver:
  `memory=off` both times, the word came back "Unknown"; no cache headers on the read; full gate
  once at 20f1aad 34/34, build ok, ui_smoke 25/25; host worker `PROVIDERS=chatgpt,grok,gemini`, all
  three ready; 20f1aad

Before it on 2026-09-27: `2026-09-27-gemini-google-block.md` (743a586; the real-page check could
not run, the block had lifted) and `2026-09-27-gemini-provider.md` (bbeb471). Each plan's Evidence
holds its numbers; docs/research/2026-09-27-gemini.md holds Gemini's measurements.

What the Grok plan's real runs and reviews cost, kept because it is the part that is easy to forget:

- Four defects the real runs found, all fixed: a job sat pending forever with the worker off; one
  provider's cooldown parked the others; a worker pausing between turns looked dead and its queued
  jobs were failed; a composer click landing on an overlay typed into nothing and sent an empty turn
- Three blocking findings from the tier 1 review, none of which the gate could see: `keyboard.type`
  splitting a prompt into one turn per line; nothing checking that a job's provider matched its
  conversation's; and `_open`'s fresh-chat recovery being unreachable, so one lost thread parked the
  whole provider for fifteen minutes
- Three more from the scoped re-review: the composer read-back comparing raw text with rendered
  text, `grok_probe` still using `keyboard.type` on the real account, and a 403 read as a signed-out
  session when it is also what a page behind the Cloudflare challenge returns
- Two test gaps the reviewer proved with its own mutants, now closed and each watched red first:
  `statuses [202, 202, 202] quota 98 -> 95` without the provider lock, and
  `queued failed kind no_worker` without the heartbeat ping
- The gate had its own bug: `skip()` was not sticky, so checks meant to be skipped still ran and
  still spent real Grok turns, and the count line printed `17/15 PASSED`
