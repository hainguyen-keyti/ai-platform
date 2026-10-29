# HANDOFF.md: live state (updated at the end of every session)

This file is a handoff note, not a diary; delete stale items, history already lives in git log;
write feature or task ids IN FULL (M3-F9, not F9: short ids collide across milestones and grep
returns the wrong one).

Trimmed on 2026-10-02 from 1022 lines. The note as it stood is kept word for word in
`docs/agent/HANDOFF-full-2026-10-02.md` (not injected at session start). The old task logs live
there and in each plan's Evidence; what the reviews left open moved into its plan, under "Left
open" at the end of the file; what the tests left in the accounts is in
`docs/agent/residue-left-in-accounts.md`.

Last updated: 2026-10-27, at **ea6cf33**, pushed to the private repo
github.com/hainguyen-keyti/ai-platform: c91c68d puts the agent layer in git; a04db8f configures the
mattpocock engineering skills (issues in GitHub Issues, the five triage labels created on the repo,
`docs/agents/`, an "Agent skills" section in `CLAUDE.md`); ea6cf33 records in `CLAUDE.md` that **a
mattpocock skill wins over the kt layer where they disagree** (the owner, 2026-10-27), without
widening Allowed / Ask first / Forbidden, and settles three overlaps: a new spec goes to a GitHub
issue through `to-spec`, handoff between sessions stays in this file, `implement` commits locally.
**The project is now worked from a Windows 11 machine** (`D:\keyti\ai-platform`, a clone of
`origin`), measured 2026-10-27: no `storage/`, no `.env`, no `~/cloakbrowser-env`, no `docker` on
PATH, `python` is only the Microsoft Store alias, WSL Ubuntu is installed; nothing can run there yet
(Known traps). **The owner is handing the project to
another person** and asked for everything on GitHub (DECISIONS 2026-10-27): `CLAUDE.md`, `.claude/`
and the whole of `docs/agent/` are now tracked; not on GitHub, by design: `.env` (its names are in
`.env.example`), `storage/` (the database, the media and the three logged-in browser profiles), the
venv `~/cloakbrowser-env`, the kt plugin and the machine rule file `~/CLAUDE.md`. The code is
unchanged since 3d2d02e. **No plan armed. Plan 2 (the web) closed**: full gate at 3d2d02e 56/56,
build, 74/74. **Nothing runs on 2026-10-27**: Docker is stopped, no host worker answers on :8000.
**The shared ChatGPT account's file storage is FULL** (`chatgpt.com/library`: "Your storage is
full", read 09:59): every ChatGPT turn with a picture (the web's reference and `/v1/images` with an
image) fails, refunded, until the owner removes files there.
**2026-10-21, after twelve idle days, the owner asked for a thorough review before going on**: the
full gate (54/54, build, 59/59) and the eleven offline suites (270 checks) green on 4cd26c8; the three
sessions read signed in without a turn; the drivers' page elements still on the sites; four
independent read-only reviews (api, worker, web and docs, records against code) found **nothing
blocking** and a ranked should-fix list: `docs/agent/reviews/2026-10-21-*.md` (the agent's own
measurements in `2026-10-21-session-and-gate.md`). What to do first is the owner's choice (Next steps).
**The owner's standing yes of 2026-10-02: the agent pushes `master` to the private `origin` on
its own once a plan has closed with its full gate green**; any other push is asked first.
**The host worker serves `chatgpt,grok,gemini` in real mode at 4cd26c8 since 2026-10-21 19:05, in the
desktop app's Terminal panel** (tab "host worker (real)", output also in
`/tmp/host-worker-real-90.log`; the one of 2026-10-09 ended with the app, and no worker ran until
2026-10-21, when a mock one served the gate from 18:54 to 19:04): it outlives the agent's turn and has no two-hour limit, but ends
with the app or the tab; the owner chose this over a launchd service (DECISIONS 2026-10-06). Start it
again with `PYTHONUNBUFFERED=1 PROVIDERS=chatgpt,grok,gemini ./scripts/run-worker.sh 2>&1 | tee -a
/tmp/host-worker-real-81.log`. From 2026-10-02 21:23 to 2026-10-06 13:10 no worker ran (a background
task of the agent's session is stopped at two hours); on 2026-10-06 at 20:04 the owner started one in
a window of Terminal.app, which the agent stopped on 2026-10-07 at 01:18 with the owner's leave for
the unread-thread plan. ChatGPT was off from 01:59 to 11:29 on 2026-10-07 for Cloudflare's check
(below).

The accounts, all three logged in by the owner on 2026-10-01 at 20:13 to 20:16, each into its own
browser profile `storage/sessions/<provider>/` with one device seed. **On 2026-10-21, after twelve
days with no worker and no turn, all three still read signed in** (read-only, the login script's own
proofs, `/tmp/session_alive.py`; ChatGPT's first look read "signed out" because its proof ran 5 s
after load, two later looks read signed in), no bot check on any home page:
- **Gemini** (`ke***2@gmail.com`, plan PRO): still signed in at 01:26 on 2026-10-02 after about
  thirteen launches in five hours (the afternoon's login had died after four launches in 47
  minutes). Personal context off, saved info off, Gemini Notebook off. On 2026-10-06 still signed
  in: chat 36s, a picture 42s, a video in 106s through the platform (10s, 1280x720), a video
  script 42s. Three videos were made that day (the owner's at 13:19, the video plan's two); at 20:07
  a fourth request was answered "Rất tiếc, hiện tại có quá nhiều yêu cầu tạo video ..." (most likely
  the day's allowance, not measured)
- **ChatGPT** (a new account, memory off): Cloudflare's check came at 21:51 on 2026-10-01 after
  a burst; since then the owner's 16 deletions at 00:06, one turn alone at 02:06 and **the real
  gate of 04:37 to 04:54 (sixteen jobs, 30/31) went through with no check**, and so did nine
  turns between 17:39 and 19:24 (the stop probe's three, four pictures, two plain turns). A
  picture now comes back in under a minute (d2d346d); it took five before. A new conversation
  asked "Tôi tên gì?" answers "Bạn tên là Keyti." (Parked questions: the owner's call). On
  2026-10-06 three turns through the web went through (13:53 to 14:03). **On 2026-10-07 at 01:54 the
  first turn after a worker restart met Cloudflare's check** (job 9d4c6765, refunded); ChatGPT was
  taken off the worker and the owner told; with the owner's yes one turn at 11:30 went through (68s)
- **Grok** (a brand-new account, free tier, memory off): turns pass since 23:06 ("pong" in 44s,
  the stop check green); the free tier walls after a short burst. On 2026-10-06 chat 29s, a picture
  24s

The last plan, `docs/agent/plans/2026-10-09-chatgpt-image-api.md` (tier 1), closed at 4cd26c8: an
image API for programs, `/v1/images` on ChatGPT, called with a personal API key each person makes,
lists and revokes on the web's "API" page: a prompt, or a prompt with one PNG, JPEG or WEBP picture
(10 MB, 16384 pixels a side, 50 megapixels), answered at once with an id, asked again for its status,
the pictures downloaded; documented in `docs/api-v1-images.md` with `scripts/image_api_example.py`;
two real requests passed (the second with the first picture as its reference). Before it,
`docs/agent/plans/2026-10-08-gemini-failure-sentence.md` (tier 2), closed at 63ec5dd:
a Gemini turn whose whole answer is Gemini's own failure sentence ("I encountered an error doing
what you asked. Could you try again?") fails as a provider error, refunded, its thread kept (the
sentence is the only sign: its markup and Gemini's stored record are an ordinary answer's); widened
with the owner's yes, it also fixed the full gate's intermittent "smooth scroll is slow" check, whose
own slowed scroll moved back half a pixel. Before it,
`docs/agent/plans/2026-10-06-chatgpt-unread-thread.md` (tier 2) closed at 508c748: a
ChatGPT follow-up turn whose thread cannot be read before the send is refused unsent and refunded,
never returning the earlier answer, and a page that left its thread is not written to; widened with
the owner's yes, it also fixed the video player's intermittent console error (a player removed at
once read its revoked blob); its real follow-up turn passed at 11:30 ("Thủ đô của Đức là Berlin.").
Before it, `2026-10-06-gemini-video-and-upload.md` (tier 2) closed at c691726: asked for a video,
Gemini's turn comes back with its words and the video, which plays in the chat and the gallery (a
real one in 106s), and Gemini's video script works again (the driver waits for the real upload
button instead of pressing the "Add files" placeholder). Before it,
`2026-10-02-chatgpt-picture-wait.md` (tier 2) closed at d2d346d: the ChatGPT driver sees a picture
turn end (the server never closes such a turn with an assistant
node, so every picture had run to the 300 second ceiling; a real one now takes 44 seconds).
Before it, `2026-10-02-gate-accounts-for-an-unsent-turn.md` (tier 1) closed at b589041: the gate accounts for a turn taken away from a running job by its thread
removed or, once nothing is still owed and no thread was tombstoned since, by the driver's own
stop record saying the turn never went out. The gate has 43 checks; the mock plays an unsent
turn, a silent driver and a driver that misreports. On the real ChatGPT gate the check passed
on the driver's word 3.8 seconds after its delete, where it had waited 150 seconds and failed.
Before it, `2026-10-01-gemini-saved-info-guard.md` closed at e64575a: the Gemini driver reads
both of the account's memory switches before every turn and was seen refusing on the real
account at 01:26 (the owner's yes: saved info on for about 10 seconds, refused in 2.9s).

## Where we are

Three providers are built and the host worker serves all three. API (FastAPI, Docker, port 3000), browser
worker (FastAPI on the host, port 8000, cloakbrowser venv) and web UI (React, Docker, port 5173).
The worker holds no database handle: it polls the API and posts results back.

Each provider gets **its own runner thread and its own browser**, because two stealth browsers
cannot be launched from one thread (measured), and its own pacing, so a provider sitting out a
cooldown never parks the others. Claims and tombstones are filtered by provider, a runner refuses a
job that is not its own, and a job whose provider nobody serves is failed as `no_worker` and
refunded rather than waiting forever. A conversation belongs to one provider: the api refuses a
turn from another with 409 and the interface locks the selector to the open conversation. A turn
that fails as `provider_misconfigured` (signed out, a memory switch on) holds its provider out for
10 minutes: not served, new turns refused uncharged, the web shows the unavailable notice.

ChatGPT does chat, image and video script, with one thread per conversation, files, zips, delete;
it does not send a turn cancelled before its send and presses the site's stop on one already sent.
Grok does **chat and image** (a video script uploads a reference picture and grok's upload flow is
unmeasured). Both settle on their own server's word, keep `/c/<uuid>` as the thread, and delete the
thread when the conversation is deleted. Gemini does **chat, image and video script** on the
owner's own Google account: it settles when its `StreamGenerate` request finishes, keeps
`/app/<16 hex>` as the thread, reads the account's two memory switches before every turn
(personal context, then saved info, since e64575a) and refuses while either is on, and deletes
the thread when the conversation is deleted. Since c691726 it also waits for a video it was asked
for (up to 300s after its stream) and keeps it as media the web plays; it presses the real upload
button, never the "Add files" placeholder. Since 508c748 ChatGPT refuses a follow-up turn whose
thread it cannot read before the send.

Twenty-nine plans finished and one set aside, each with its measurements in its own Evidence section:
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
- `2026-09-30-ui-polish.md`, Back closes the phone's list, the empty list's notes, the select named, every text at WCAG AA, closed 2026-09-30 at a8b5302
- `2026-10-01-hold-misconfigured-and-real-stop.md`, a provider its admin must fix is held out, Stop stops at ChatGPT, set aside 2026-10-01 at db429a1 (its two real lines carried into the next)
- `2026-10-01-one-profile-per-provider.md`, one browser profile and one device per provider, closed 2026-10-01 at a0d04b0
- `2026-10-01-gemini-saved-info-guard.md`, Gemini's saved-info switch read before every turn, closed 2026-10-02 at e64575a
- `2026-10-02-gate-accounts-for-an-unsent-turn.md`, the gate's rule for a turn taken away from a running job, closed 2026-10-02 at b589041
- `2026-10-02-chatgpt-picture-wait.md`, the ChatGPT driver sees a picture turn end (a picture in under a minute where it took five), closed 2026-10-02 at d2d346d
- `2026-10-06-gemini-video-and-upload.md`, Gemini's video collected and played, its upload button found again, closed 2026-10-06 at c691726
- `2026-10-06-chatgpt-unread-thread.md`, a ChatGPT follow-up never takes an earlier answer when its thread cannot be read; the video player's console error, closed 2026-10-07 at 508c748
- `2026-10-08-gemini-failure-sentence.md`, Gemini's own failure sentence fails the turn and refunds, closed 2026-10-08 at 63ec5dd
- `2026-10-09-chatgpt-image-api.md`, `/v1/images` on ChatGPT with personal API keys, closed 2026-10-09 at 4cd26c8
- `2026-10-21-safety-of-data-and-credits.md`, no attachment of another turn rides along, Grok never takes an earlier answer, empty done and dead worker refunded, a dead browser recovered, closed 2026-10-22 at 1a5e7aa (its real ChatGPT line waits on the account's storage)

Latest evidence, each on a clean tree:
- **The unread-thread plan at 508c748, 2026-10-07**: full gate once (the host worker in mock)
  `python acceptance.py` **44/44**, build exit 0, `tests/ui_smoke.py` **57/57**;
  `tests/test_chatgpt_composer.py` **49/49**; 16 of 16 mutants red; the real follow-up turn passed at
  11:30 (68s, Berlin) after Cloudflare's check of 01:54 had lifted. The gate at 8496c15 was 55/56
  on the console error T4 then fixed
- **The Gemini video plan at c691726, 2026-10-06**: full gate once (18:28 to 18:36) `python
  acceptance.py` **44/44**, build exit 0, `tests/ui_smoke.py` **56/56**;
  `tests/test_gemini_driver.py` **136/136**; mutants 12 of 12 and 12 of 12 red; real through the web:
  a Gemini video in 106s and a Gemini video script in 42s. The first gate at 3343c1f was 55/56 on
  the same console error
- **The agent's walk of the web as a user, 2026-10-06 13:51 to 14:04, at d2d346d, the host worker
  real** (a throwaway account, `/tmp/manual-test-account.json`): chat Gemini 36s, ChatGPT 22s, Grok
  29s; a picture ChatGPT 57s, Gemini 42s, Grok 24s; video script ChatGPT 34s; red then: Gemini's
  video script and the owner's video turn, both fixed by the Gemini video plan
- **The picture rule at d2d346d, 2026-10-02**: full gate once (19:16 to 19:23, the host worker in
  mock) `python acceptance.py` 43/43 exit 0, build exit 0, `tests/ui_smoke.py` 53/53 exit 0;
  `tests/test_chatgpt_composer.py` **37/37**; 15 of 15 mutants red; a real picture turn through
  the platform done in **44s** with its picture, a plain turn in 22s ("Tokyo"), no Cloudflare check
- Full gate at b589041, 2026-10-02 04:29 to 04:35, the host worker in mock: `python acceptance.py`
  **43/43** exit 0, `npm run build` exit 0, `tests/ui_smoke.py` **53/53** exit 0. Mutants of the
  gate's rule at b589041: 35 of 37 red (the two others cannot go red with a right rule). Every
  offline test at e64575a: gemini driver **111/111**, composer 22/22, grok memory 20/20, grok
  settle 8/8, liveness 4/4, login provider 10/10, runner health 4/4, runner tombstones 3/3,
  tombstones 5/5, session profile 12/12, the session check's table 23/23
- **The real ChatGPT gate at b589041, 2026-10-02 04:37 to 04:54: 30/31 PASSED, 12 skipped, exit
  1, sixteen jobs, no Cloudflare check.** "deleting a conversation cancels its running job and
  refunds" PASSED on the driver's own word ("its turn never sent, by the worker's stop record
  {'sent': False, 'pressed': False, ...}: no thread to remove"). The one red, "a conversation's
  media downloads as one zip": the picture turn before it failed as `provider_timeout`, "chatgpt
  returned nothing after 302s" (the run's own job record), so the conversation held one media
  where two are wanted. Workspace `$TMPDIR/ai-platform-acceptance-ou5249ge`
- Real, Gemini, 2026-10-02: `python tests/session_check.py gemini --keep` "[PASS] gemini answers
  done in 18s, reply 'pong', worker mode real, memory off"; the guard alone on the real profile
  both off in 3.5 to 4.5s; the refusal with saved info on in 2.9s (the plan's Evidence)
- Real gates, the latest per provider: ChatGPT 30/31 at b589041 (above) and 30/30 at 3e32a12;
  Gemini **25/25** at 34b533c;
  Grok **18/18** at 20f1aad and 19/20 at bbb3924 (its red a gate defect since fixed); the web
  journey `tests/ui_journey.py` 8/8 at bbb3924
- The owner's acceptance checklist (13 items), walked by the agent on 2026-10-01 at a8b5302 with
  the host worker real: **33/36**, the only red Gemini's then signed-out session, green in the
  rerun on the new login (chat 18s, a picture 44s, a video script 661 characters)

## Verify commands

```
Quick gate: python acceptance.py
Full gate: python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py
Provider smoke: python acceptance.py --real --keep [--provider grok|gemini]
One real turn: set -a; . ./.env; set +a; python tests/session_check.py <provider> --keep
```

acceptance.py is standard library and starts its own api and worker on free ports. `--provider`
picks who the job checks speak to; in mock mode the worker always serves `chatgpt,grok,gemini` so
the multi-provider machinery is exercised every run. `--keep` keeps the run's workspace, logs and
database: the api's `thread_tombstones.error` holds the worker's own reason a deletion failed.
ui_smoke and ui_journey import cloakbrowser, so they run under the venv python against the running
stack, with the host worker in `PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4` and INVITE_CODE loaded
from `.env` without printing it. The session check passes only on a worker in real mode that read
the account's memory as off and got the word alone; without `--keep` it deletes the conversations
it made, so the agent always runs it with `--keep`. `tests/grok_probe.py`, `tests/gemini_probe.py`
and `tests/provider_probe.py` measure the real sites (`gemini_probe.py all` spends no turn and
changes nothing, but its `list` prints the owner's own conversation titles);
`tests/test_gemini_driver.py`, `tests/test_grok_settle.py` and `tests/test_tombstones.py` need no
account.

## Next steps

**Phase 0, approved 2026-10-27 (DECISIONS 2026-10-27): make the project run on the Windows
machine, inside WSL Ubuntu, from `/mnt/d/keyti/ai-platform`.** Steps: 0-1 Docker Desktop with the
WSL2 backend (the owner, UAC); 0-2 the venv `~/cloakbrowser-env` in WSL (PyPI checked first); 0-3
`.env` with new secrets; 0-4 `python acceptance.py --keep` 56/56; 0-5 compose up, web build, mock
worker with `MOCK_DELAY_SECONDS=4`, `tests/ui_smoke.py` 74/74; 0-6 `.claude/test-command.txt`
running the full gate through `wsl -d Ubuntu --exec bash -lc`; 0-7 every difference from macOS
written down, as input to plan (3)'s setup guide. Then plan (3). Tickets in GitHub Issues (each
asked first), state in this file; provider logins only after Phase 0.
Progress 2026-10-27: **0-2 done**: `~/cloakbrowser-env` in WSL (Ubuntu 26.04.1), Python 3.11.17
installed by uv 0.13.5 (`uv venv --seed`, since the gate and `run-worker.sh` call the venv's pip),
`cloakbrowser==0.5.10` and `playwright==1.63.0` (the versions the macOS machine ran; cloakbrowser
0.6.4 of 2026-10-23 was under two weeks old), then both requirements files; `pip check` clean. No
Chromium downloaded yet. **0-3 done**: `.env` written from `.env.example` with new JWT_SECRET,
INVITE_CODE and WORKER_TOKEN, LF line endings, git-ignored; no value was printed. **Blocker found**:
`core.autocrlf=true` on this machine checks 167 files out with CRLF and there is no
`.gitattributes`, so in WSL `bash -n scripts/run-worker.sh` fails ("unexpected end of file"); the
shell scripts cannot run until the line endings are settled. **Settled the same day** (the owner's
choice): a `.gitattributes` with `* text=auto eol=lf` and the binary types marked `binary`; the
working tree was written again from the index, 167 text files LF and the 28 PNG untouched, and
`bash -n` passes on both tracked `.sh` files inside WSL. **0-4 done**: `python acceptance.py --keep`
in WSL at 2ebc188, clean tree, **56/56 PASSED** in 4m41s (2026-10-27 08:38 UTC, workspace
`/tmp/ai-platform-acceptance-d_3izlrx` inside WSL). The first run read 55/56: "the provider's error
banner is recognised by shape" timed out after 180s because the first cloakbrowser launch on this
machine downloads its Chromium; run alone right after, one try met a passing WSL DNS failure
(`httpx.ConnectError: [Errno -3] Temporary failure in name resolution`) and the next read 10/10. That
Chromium is cloakbrowser's free binary **v146**, where the macOS machine ran chromium-145.0.7632.109.2:
the browser build the sites see changes on this machine (plan (3)'s cloakbrowser pin and
`CLOAKBROWSER_AUTO_UPDATE`); it also warns that the Windows font set is incomplete. Next: 0-1 (Docker
Desktop, the owner, not installed yet), then 0-5. **0-1 done** (Docker Desktop, engine 29.9.2, its
WSL integration on for Ubuntu, compose v5.6.1). **0-5 at 7b53dac: compose build and up (api health
ok, web 200), `npm ci` and `npm run build` exit 0 (npm 11 warns it held esbuild's postinstall), the
mock worker with `MOCK_DELAY_SECONDS=4` claiming from the api, `tests/ui_smoke.py` 73/74 in 3m53s.**
The one red, "on a phone the nav is one row from 360px in both languages, its right side kept
together": nav heights en 360 39, en 390 39, vi 360 **63**, vi 390 39, the right side split, no word
wrapped inside an item. Measured right after through CDP (`CSS.getPlatformFontsForNode` on the
login page): the web's text (`ui-sans-serif, system-ui, sans-serif`) renders in **DejaVu Sans**, the
only sans family in this WSL besides Ubuntu's, where macOS rendered its own system face; DejaVu is
wider, so the Vietnamese nav no longer fits one row at 360px. A host-font difference of the test
machine, not a code change; how to treat it is the owner's call (Parked questions).
**Fonts settled the same day (the owner's choice):** Roboto from apt with a fontconfig alias changed
nothing in the browser: cloakbrowser's Chromium on Linux claims Windows (`navigator.platform` Win32)
and rendered every named host family (Roboto, Ubuntu, even DejaVu Serif) as DejaVu Sans, only the
generic families reaching DejaVu. The owner chose cloakbrowser's own advice instead: 28 font files
of this machine's Windows (Segoe UI, Arial, Calibri, Consolas, Courier New, Marlett, Franklin
Gothic, MS Gothic) copied from `C:\Windows\Fonts` into `~/.local/share/fonts/windows` in WSL, then
`fc-cache -f`. The web's text then renders in **Arial** and cloakbrowser's font warning is gone.
**`tests/ui_smoke.py` 74/74 in 3m46s at 47a35d0** (2026-10-27 12:38 UTC, the nav 39px in both
languages at 360 and 390). The code is the same from 2ebc188 to 47a35d0 (only this file changed),
so the full gate reads quick 56/56, build exit 0, ui_smoke 74/74 on this machine. Real runs will
also show the sites this Windows font set, where the macOS machine showed its own. Roboto and
`~/.config/fontconfig/fonts.conf` stay installed, inert for the browser. **0-6 done**: the full
gate is one command, `scripts/full-gate.sh` (the quick gate, the web build, `docker compose up -d`
and a wait for api and web, a mock worker with `MOCK_DELAY_SECONDS=4` started when nothing answers
on :8000 and stopped on exit, a worker already there used only if its health says mock, then
`tests/ui_smoke.py` with INVITE_CODE read from `.env`), and `.claude/test-command.txt` holds the
one line the test gate runs, `wsl -d Ubuntu --exec bash -lc "cd /mnt/d/keyti/ai-platform &&
./scripts/full-gate.sh"` (double quotes: cmd.exe and wsl.exe do not treat single quotes as
quotes). Run as the gate runs it, `cmd.exe /d /c "<line> 2>&1"` from the project folder, with no
worker up: **exit 0 in 504s**, ui_smoke 74/74 (`set -eu`, so the quick gate and the build were
green before it), and the worker it started was gone afterwards. The file names this machine's
path, so it stays on this machine, git-ignored (the owner's choice). **Phase 0 is done**; next:
plan (3), the docs and the configuration.

**Plan (3), approved 2026-10-27 (DECISIONS 2026-10-27, decisions D1-D8): seven GitHub issues, all
open, labelled `ready-for-agent`, worked one at a time in this order** (each full gate shares the
Docker stack and port 8000): #1 the first-admin race (high risk: an independent reviewer), #2 the
api's settings and `.env.example`, #3 the web image's lockfile, #4 the cloakbrowser, playwright and
Chromium pin, #5 the records against the code, #6 stale comments and the probe's import (blocked
by #1), #7 the README and CLAUDE.md's commands (blocked by #2, #3, #4). **Added 2026-10-28 with
the owner's yes: #8** (T9), `scripts/run-worker.sh` passes the worker every line `.env` sets for
it and a name given on the command line still wins, found by #2, medium risk; it blocks #7. **And
#9** (T10, 2026-10-28, option A): every browser launch that bypasses `open_session` sets
`CLOAKBROWSER_AUTO_UPDATE=false` too, with a guard check, found by #4. The order is now #9, #8, #5,
#6, #7; the orchestrator hands each next ticket on once the previous one is committed, stopping
only for the owner's decision or a ticket failing twice (DECISIONS 2026-10-28). Each issue holds its goal,
its files, its "done when" checklist and the common rules; the orchestrator hands each to a child
session by the `/orchestrate` skill, checks the diff and the full gate, and commits one ticket per
commit. Progress:
- **#1 done** (plan3 ticket 01): `register()` hashes first, then checks the email, counts the users
  and inserts inside one `BEGIN IMMEDIATE`, with a guarded `_rollback`. Two new gate checks fire
  `RACERS = 8` registrations at once at an api of their own on an empty database ("eight
  registrations at once ... exactly one admin"; "the same email registered eight times at once
  ... one 201 and 409 to the rest, never 500", three rounds): red on the old code
  (`[(201, 'admin'), (201, 'admin')]`, and a 500 from `IntegrityError: UNIQUE constraint failed:
  users.email`). Two requests were not enough: with no transaction at all (mutant C) the two-request
  check stayed green 1 run in 5, so the child session raised it to eight on the first review's
  major finding. The child's mutants A, A2, B, B2, C, D were red 5/5 each; the orchestrator's own
  measure on copies of `api/` (scratchpad `measure_mutant_c.py`, 5 rounds each): the code as it is
  green 5/5 on both checks (one admin each round), mutant C red 5/5 on both (2 to 4 admins a
  round). Two independent reviews, the second "Đạt". **Full gate, the orchestrator's run through
  the test gate: quick gate 58/58, build, ui_smoke 74/74, exit 0 in 522s.** The quick gate now
  has 58 checks. Issue #1 ticked with its evidence and closed (the two checks race eight
  registrations, not two, written on the issue).
- **#2 done** (plan3 ticket 02): compose names the seven api settings it lacked as
  `${VAR:-default}`, each default `config.py`'s own; `.env.example` holds D2's values
  (`PROVIDERS=chatgpt,grok,gemini`, `MIN_GAP_SECONDS=3`, Grok's 150 and 600, `NO_WORKER_SECONDS=310`
  with the floor explained, `TOKEN_TTL_HOURS=24`) and says which lines the api reads. Before:
  `docker compose config` listed five variables and `DEFAULT_QUOTA=7` gave a new user 100 credits
  (`printenv` in the container exit 1); after: seven, and 7 credits, back to 100 without it. A mock
  worker serving all three providers keeps ui_smoke at 74/74. **Full gate, the orchestrator's run
  through the test gate: 58/58, build, 74/74, exit 0 in 507s.** Its finding outside its files,
  `run-worker.sh` exporting none of the worker's lines, became #8 (done, below).
- **#3 done** (plan3 ticket 03): `web/Dockerfile` copies `package.json` and `package-lock.json` and
  runs `npm ci`. Before: the old Dockerfile rebuilt with no cache installed vite 6.4.5, postcss
  8.5.32 and autoprefixer 10.6.2, the newest in their `^` ranges, where the lockfile says 6.4.3,
  8.5.28 and 10.6.1; after, measured by the orchestrator in the running container: 6.4.3, 8.5.28,
  10.6.1, react-markdown 10.1.0, the lockfile's. A rebuilt image reaches the container only with
  `docker compose up -d --renew-anon-volumes web` (`-V`): plain `up -d` keeps the old
  `node_modules` in the anonymous volume (Known traps). **Full gate, the orchestrator's run through
  the test gate: 58/58, build, 74/74, exit 0 in 518s.** The child's review passed; low risk, so no
  second independent review. The child left an image `ai-platform-web:plan3-03-old` and a dangling
  volume behind; removing them is the owner's call. `npm ci` reports "3 vulnerabilities (1
  moderate, 2 high)" in the lockfile, not looked into.
- **#4 done** (plan3 ticket 04): `worker/requirements.txt` pins `cloakbrowser==0.5.10` and
  `playwright==1.63.0` and says why; `open_session` sets `CLOAKBROWSER_AUTO_UPDATE=false` unless the
  process set it. A new check in `tests/test_session_profile.py` read 12/13 red before and 13/13
  after (orchestrator's run 13/13); two mutants (overwriting instead of `setdefault`; setting it
  after the launch) red. `pip install -r` changed nothing, `pip check` clean. **Full gate, the
  orchestrator's run through the test gate: 58/58, build, 74/74, exit 0 in 512s;**
  `~/.cloakbrowser/` still holds only `chromium-146.0.7680.177.5`. **The hole it left, measured by
  the child in cloakbrowser 0.5.10's own code:** a launch that does not go through `open_session`
  (`tests/test_dom_signatures.py`, `tests/ui_smoke.py`, `tests/ui_journey.py`,
  `tests/test_gemini_driver.py`, `tests/gemini_probe.py`) still checks for a newer Chromium at most
  once an hour in a background thread, downloads it and writes the marker
  `~/.cloakbrowser/latest_version_linux-x64`, and `get_effective_version` then picks that build for
  every later launch, `open_session` included, whatever `CLOAKBROWSER_AUTO_UPDATE` says. Nothing
  changed today only because the newest free linux build upstream is still 146 (the ten newest
  releases are `-pro`, no linux tarball). The owner chose option A on 2026-10-28: issue #9, worked
  next (below). `.scratch/` (the child sessions' reports) is now git-ignored.
- **#9 done** (plan3 ticket 09): the five test files that launch cloakbrowser themselves
  (`test_dom_signatures.py`, `ui_smoke.py`, `ui_journey.py`, `test_gemini_driver.py`,
  `gemini_probe.py`) set `CLOAKBROWSER_AUTO_UPDATE=false` with `setdefault` at the top of the module.
  A new check in `tests/test_session_profile.py` reads every `.py` under `worker/`, `scripts/` and
  `tests/` with `ast` and fails a launch (any of cloakbrowser's seven launchers or `ensure_binary`,
  by module or by name) with no such `setdefault` above it at module level or in its own function:
  red 13/14 on the old tree naming the five files and their first launch lines, 14/14 after; 18
  mutants red; two child reviews (the first found `launch_context` missed, fixed). Orchestrator's
  runs: `test_session_profile.py` 14/14, `test_dom_signatures.py` 10/10, `test_gemini_driver.py`
  143/143, none printing cloakbrowser's "Update available" (it did before, the variable also turns
  off the wrapper check); `ui_journey.py` and `gemini_probe.py` not run (real accounts), the child
  imported both. **Full gate, the orchestrator's run through the test gate: 58/58, build, 74/74, exit
  0 in 501s, no "Update available" in ui_smoke**; `~/.cloakbrowser/` still holds only
  `chromium-146.0.7680.177.5`, no marker. The hourly Chromium check itself is shown off only
  indirectly (the same variable gates it; upstream has nothing newer to fetch).
- **#8 done** (plan3 ticket 08, worked in the orchestrator's own session at the owner's "Do this task
  here"): `scripts/run-worker.sh` snapshots `export -p`, sources `.env` under `set -a`, then reads
  the snapshot back, so every line `.env` sets reaches the worker and every name the command line
  or the calling shell exported wins, an empty one too (it then falls to the script's default).
  `tests/test_run_worker_env.py` (new) runs the script from a temp copy with its own `.env` (the file
  says real; the command line says mock) against a fake api recording the token: red 3/5 before
  (`providers ['chatgpt']`, `min_gap 0.0` with the file saying `chatgpt,grok` and 7; `PROVIDERS=grok`
  on the command line overwritten), 5/5 after under dash; three mutants red (no `set -a` 3/5, no
  `eval` 2/5, snapshot after the file 2/5). With this machine's `.env` the full gate's mock worker
  now reads `min_gap 3.0` (it read 0.0) and ui_smoke stays 74/74, so `scripts/full-gate.sh` is
  unchanged. **Full gate through the test gate, that worker reused: 58/58, build, 74/74, exit 0 in
  499s** (the script's comments and the test's `mode` assertion were added after it, on the
  independent review; the test was re-run 5/5 with the mutants after them). Independent review:
  passed, minors left open: under bash an exported `SHELLOPTS` or `BASHOPTS` makes the `eval` stop
  the script (readonly; dash is fine), and `set -a` also puts the api's lines of `.env`
  (`JWT_SECRET`, `INVITE_CODE`) in the worker's environment (no path prints it); the new test is in
  no gate. **From now on a real worker paces as `.env` says** (3s between turns, Grok 150s once the
  owner's `.env` carries those lines).
- **#5 done** (plan3 ticket 05, docs only): `PROJECT.md`'s one-screen architecture shows the api as
  FastAPI (Python) in Docker and the worker on the host in WSL polling `/internal/*`, media on local
  disk (no R2); its Local row says compose plus the host worker, from WSL Ubuntu on the Windows 11
  machine. The 2026-09-23 spec opens with a "superseded by the code" line. `ACCESS.md`: "Tôi tên
  gì?" answered "Bạn tên là Keyti." (2026-10-02 02:06), the old state files are the three in the
  old macOS machine's Trash, "Where secrets live" adds `INVITE_CODE`, `WORKER_TOKEN`, login JWTs (the
  token itself in `sessions`), personal API keys (SHA-256 and a 12-character prefix only) and
  passwords (bcrypt), and the WSL paths of the repo, `storage/` and the venv. DECISIONS' 2026-09-23
  rows "Hybrid architecture" and "Every job starts a fresh ChatGPT chat" keep their words and name
  the rows that replaced them (D5). `git grep Hono` finds only the spec's body and the two 2026-10-21
  reviews. The child's review passed (3 minors, 5 nits, fixed but one); the orchestrator checked
  the new lines against `security.py`, `auth.py` and `v1.py`. **Full gate, the orchestrator's run
  through the test gate: 58/58, build, 74/74, exit 0.** Left open by it: `PROJECT.md:7` ("Docker
  Compose deployment") and `ACCESS.md`'s "Local Docker | docker compose up" still leave the host
  worker out; DECISIONS section 3's "Cloudflare deployment, Q4 2026" is due and contradicts the
  FastAPI row (the owner's call).
- **#6 done** (plan3 ticket 06, comments and one import): `ChatGPTProvider`'s docstring now says a
  conversation keeps one thread (a new chat only with no stored thread or a 404, history replayed
  only into a turn with no thread, users kept apart by one owner per conversation and memory off);
  `test_runner_tombstones.py`'s comment no longer names `_stop`; `acceptance.py`'s docstring says
  mock takes about 5 minutes (4m19s measured), `--real` drives one provider picked by
  `--provider`, and `--keep`. `tests/provider_probe.py` imports `ATTACHMENT_PREVIEW` and
  `ATTACHMENT_REMOVE`: unbound before (the remove step's `NameError` was caught and printed, so the
  step was never measured), both resolve after; the probe was not run. The three other files are
  the same code with docstrings removed (`ast.dump` compared, the child's run and the
  orchestrator's own); five mutants red. Two child reviews, the second "Đạt".
  `test_runner_tombstones.py` 3/3. **Full gate, the orchestrator's run through the test gate:
  58/58, build, 74/74, exit 0.** Left open by it: `acceptance.py:2160` still says mock serves two
  providers (it serves three); `V1_REAL_SKIP` (`:117`) says "chatgpt turns" under any
  `--provider`; the tombstone test could `join()` the runner now instead of sleeping; and a
  suspect, read in code by the review, not run: when a stored thread answers 404, `_open` opens a
  new chat but `chat()` replays no history because `thread_url` was given (`chatgpt.py:983`), so
  that turn starts without its conversation's context.
- **#7 done** (plan3 ticket 07, the last of plan (3)): `README.md` (new) takes a fresh clone to a
  green full gate on Windows 11 with WSL2: prerequisites (on WSL the three apt packages Chromium
  needs, `libnss3 libnspr4 libasound2t64`, found by the child's reviews in this machine's apt log
  and `ldd`), the LF checkout and its repair, `.env`, the venv (`uv venv --seed --python 3.11`, both
  requirements files, `CLOAKBROWSER_VENV`), the Windows fonts and why, `npm ci`, Docker with WSL
  integration, registering one's own account before the full gate (the first account is the
  admin), the gates and `.claude/test-command.txt`, logging in, and the `src.main` restart. macOS
  is not walked. `CLAUDE.md`: a line pointing at the README, Run serving `.env`'s `PROVIDERS`,
  `Full gate: ./scripts/full-gate.sh`, `Provider smoke: python3 acceptance.py --real --keep
  --provider <name>`, the login line for any of the three, the R2 rule as D6 decided. `python3`
  where the issue said `python`: WSL's Ubuntu has no `python` (measured). Walked twice from a
  fresh clone in `~/.cache/plan3-07-walk*` (own venv, own `.env`, no compose up there): quick gate
  58/58 both times; every command of the block checked (`--help`, usage errors, `sh -n`, `docker
  compose config -q`). Two child reviews (3 majors, all fixed). **Full gate, the orchestrator's run
  through the test gate: 58/58, build, 74/74, exit 0.** Left behind for the owner to remove:
  `~/.cache/plan3-07-walk/`, `~/.cache/plan3-07-walk2/` and their two logs. Left open: the docstrings
  of `acceptance.py` and `tests/ui_smoke.py`, `.env.example`'s login line and this file's Phase 0
  note still say `python`; compose's `NO_WORKER_SECONDS` default is 180 where `.env.example` says
  310; a truly new WSL distro (no apt packages, no Chromium, no uv or node) is not walked.

**Plan (3) closed on 2026-10-28** with #7: all nine issues done and closed, the full gate green.

**After plan (3), 2026-10-28, this machine runs for real.** The owner logged the three providers
in from WSL (WSLg shows the window); a read-only check with the login script's own proofs read all
three signed in. The owner brought `.env` up to `.env.example` (`PROVIDERS=chatgpt,grok,gemini`,
`NO_WORKER_SECONDS=310`, `TOKEN_TTL_HOURS=24`, Grok's 150 and 600); the api container and the
worker read them back. The ChatGPT account's memory was ON (the first turn was refused, as
designed); the owner turned it off, and the drivers' own readers then read all three accounts
`off`. The real worker runs in the desktop app's Terminal panel ("host worker (real)"). **WSL
restarted by itself twice that morning (about 06:26 and 06:54 UTC), cause not looked into**: each
time the worker ended with it and the api needed `docker compose up -d --force-recreate`.
- **Issue #10 done** (ChatGPT picture turns): the owner's first picture came back after 5m24s with
  the same file twice. The thread's own server record: the picture at +48s, an empty closing answer
  (`end_turn`) at +53s, a `reasoning_recap` without `end_turn` at +55s that the driver took for the
  newest node, so it ran to its 300s ceiling; the tool's "saved at /mnt/data/…" copy was fetched as
  a file too (same sha256). A probe turn found a third shape: the closing answer in the picture's
  own second, the page not painted yet, so the turn failed as returning nothing. The driver now
  leaves `reasoning_recap` and `model_editable_context` out of "the reply" and "the newest node",
  waits for the paint whenever the turn drew, and drops a sandbox file byte for byte a picture
  taken from the page. `tests/test_chatgpt_composer.py` plays the three measured shapes (red on the
  old driver: 303s, 0 pictures at 38s, 2 pictures) and a sandbox file that is not a copy: 60/60;
  four mutants each red on their own check. Full gate through the test gate: 58/58, build, 74/74,
  exit 0. One real picture turn through the fixed driver (the probe, thread deleted): the same
  shape as the owner's (answer +24s, recap +25s), back in 63s with one picture. The probe and the
  mutant runner are in the session's scratchpad, not in the repo.
- **Issue #11 done** (Grok's composer): the owner's second Grok turn, on a thread opened again,
  failed after 4 minutes as "the turn never reached grok's composer", nothing sent. A probe through
  the driver on that thread (typed, read back, cleared, never sent): `_open` had taken
  `textarea[aria-label="Ask Grok anything"]`, the only composer there at the open; the click timed
  out, it was gone; 12s after load the composer is a `tiptap ProseMirror` in
  `[data-testid="chat-input"]`. `_send` now looks for the composer again before each try.
  `tests/test_grok_composer.py` (new, in no gate): the measured shape red on the old driver
  (refused, nothing sent), 3/3 after; two mutants red; `test_grok_settle.py` 17/17,
  `test_grok_memory.py` 20/20. Full gate through the test gate: 58/58, build, 74/74, exit 0. Two
  real turns through the fixed driver (a new chat, then a follow-up on it opened again; thread
  deleted): both answered in 11-13s, but the editor was already mounted at both opens, so the real
  run did not meet the placeholder again (it depends on timing). **This Grok account looks like a
  personal one in use** (pinned bots and chats the platform did not make in its sidebar), where
  DECISIONS recorded a brand-new account for the platform: the owner's call. Grok's cookie dialog
  stays open (its "Reject All" has no id the driver knows); it does not cover where the driver
  clicks.
- **Issue #12 done** (what each provider offers): the owner pressed "Video script" under a Grok
  picture; the api took it (202) and the worker failed the job a second later ("provider grok does
  not support video_script"), refunded. `api/src/models.py` now holds `FEATURES` per provider, the
  drivers' `supported_features`; `create_job` refuses a feature the provider does not offer with 400
  after the 404 and 409 checks, before anything is written or charged; `GET /providers` gives each
  provider's `features`; the web shows "Video script" only where the conversation's provider
  offers it, and while that is unknown. New checks, red before: the quick gate's "a feature its
  provider does not offer is refused at once and uncharged" (was 202) and "the api says what each
  provider offers, as its driver does" (the api said nothing; it reads the drivers with `ast`), and
  ui_smoke's "a picture offers a video script only where its provider writes them" (the list played
  in the browser; 1 button before, 0 after). A drift mutant (grok given `video_script` in the api)
  turns both gate checks red. **The quick gate has 60 checks and ui_smoke 75.** Full gate through
  the test gate: 60/60, build, 75/75, exit 0.
- **Issue #13 done** (a Grok turn the server never got): a follow-up ("hình người thật đi", job
  `cd058655`) failed after 321s as returning nothing; the server's record of the thread had no
  question of that turn, and the same words sent again passed in 28s (why the first send never
  landed, network or page, was not measured). Measured on three real turns (thread deleted): the
  question is listed at the driver's first read after Enter, 4.3-6.3s (written on the issue before
  the number was chosen). The driver now refuses a turn as "grok never received this turn" when a
  read that went through still lists no question of it 30s after Enter (`HEARD_WAIT`); a failed
  read keeps the wait. `tests/test_grok_settle.py`, 21/21: the measured shape red before (300s,
  `provider_timeout`), 32s after; a long answer whose question is listed is still waited on; an
  unreadable thread still waits to the ceiling; the flag resets between turns on one driver; four
  mutants each red on their own check. Full gate through the test gate: 60/60, build, 75/75, exit 0;
  two real Grok turns through the fixed driver (a new chat and a follow-up, deleted) passed in 13s
  and 10s.
- **The owner's acceptance walk, 2026-10-28, done by the agent in the browser pane** (as 123@test.com,
  6 credits): ChatGPT chat and a follow-up in context, a picture (two different pictures, ChatGPT's own
  choice, 2m18s, ChatGPT's page still working all that time), a video script from it (the upload went
  through, so the library may no longer be full); Grok chat and a picture in the same conversation
  (32s after its 150s gap), no Video script under it; the gallery (9 pictures) and the language
  switch. **Gemini failed** as "did not finish within 300s"; its thread on the account holds the
  right answer.
- **Issue #14 (Gemini's new web app), code done, open for the real check**: measured through the
  driver's own open, guard and send: no `StreamGenerate` any more (two short
  `geminiweb-pa.clients6.google.com/v1/processSession` posts; the words over `batchexecute`, painted
  as late as 76.7s); a "Stop response" button from the send until the turn is over (gone at 30.3s
  and 33.3s); pictures still from `lh3.googleusercontent.com/rd-gg-dl/`; a thread's page paints its
  turns about 35s after the load, past `HISTORY_WAIT`, so every deletion refused. The driver now
  ends a turn when the Stop response button it saw goes (a StreamGenerate that ends still does),
  waits up to `ANSWER_WAIT` (90s) for this turn's words, a picture or a note, and waits
  `HISTORY_WAIT` 60s. `tests/test_gemini_driver.py` 147/147 (four measured shapes red before),
  four mutants red; full gate 60/60, build, 75/75, exit 0. Google's unusual-traffic check
  (`www.google.com/sorry`) came on during the fourth probe; probing stopped and the worker ran
  without gemini until it lifted (2026-10-29, a load read not blocked). **Then the real check passed
  through the fixed driver's own `chat()` and `generate_image()`: "lambda" in 81s and one picture in
  53s, both settled by the button, both threads deleted (45s, 24s)**; #14 closed, and the worker
  serves `chatgpt,grok,gemini` again from `.env`. A Gemini chat turn takes over a minute now
  because its words paint late. **Reopened the same night**: the agent's acceptance turn through the
  web (job `09c44615`, 00:46) failed after 4m31s as "carried neither words nor a picture", with
  memory read `unknown` and no conversation made on the account. It did not come back: the same
  question through `chat()` at 01:01 passed in 23s (button 1.3s to 9.9s), and a web turn at 01:25
  in 33s. Likely Gemini itself not taking turns then; not proven, since nothing of that page was
  kept. #14 closed again on the owner's word.
- **Issue #15 done** (a failed Gemini turn's page is kept): a turn that fails once it was sent,
  returned or raised, keeps a screenshot and a short JSON (address, questions, answers, the Stop
  response button, the last answer's text, any alert or status text) in `storage/failures/`
  (`gemini-<UTC time>-<thread or new>-<6 hex>.png/.txt`, git-ignored with `storage/`), and its
  message ends "(page kept as …)"; a record that cannot be kept says "(page not kept: …)" and never
  changes the failure; a turn refused before its send keeps nothing. `tests/test_gemini_driver.py`
  152/152 (three red before), four mutants red; tried on the real page once, no turn (a 236 KB
  picture and the JSON). Full gate 60/60, build, 75/75, exit 0. Old records are not cleaned up.
- **Issue #16, code done, open for the real pictures** (`/v1` picks its provider): `POST /v1/images`
  takes `provider` (`chatgpt` by default, `grok`, `gemini`; another one 400, uncharged); a reference
  picture to grok is refused 400 before it is kept or charged (`TAKES_REFERENCE` in
  `api/src/models.py`); a request on any provider is readable through `/v1`; `GET /v1/providers`
  with a key says served, makes_pictures, takes_reference; the status answer names its provider;
  `docs/api-v1-images.md` and `scripts/image_api_example.py --provider` say it. Three quick gate
  checks red before; four mutants red; **the quick gate has 63 checks**; full gate 63/63, build,
  75/75, exit 0. Real, with a throwaway account `v1-real-…@aiplatform-acceptance.com` and its key
  (revoked after): `/v1/providers` right; ChatGPT a picture in 59s; **Grok** done with words and no
  picture ("Here's a simple generated image…", 16s), then, retried, "answered with nothing" after
  111s; **Gemini** answered "I don't seem to have access to that content" (22s), then **Google's
  unusual-traffic check came on again**: the worker runs with `PROVIDERS=chatgpt,grok` until it
  lifts. The routing is right (each job ran on the provider asked); the missing pictures are the
  providers' turns, not looked into yet. Left on the Gemini account: "Red Apple on Wood" (a probe's; not
  found in the list 15s after the load, so not deleted) and "Màu của bầu trời lúc trưa" (the
  acceptance turn's); the probe threads "kappa" and "1b74d62d" were deleted. The label "Stop response" is the English interface's; another language
  is not measured. The Gemini account shows "Tomy Tom, Pro", where HANDOFF recorded `ke***2@gmail.com`.

**Since 2026-10-27 the owner adopts the mattpocock skills** (precedence in `CLAUDE.md`): the
roadmap's first step is `/mattpocock-skills:improve-codebase-architecture`, which only the owner can
start (the skill refuses a call from the agent, `disable-model-invocation`); then
`grill-with-docs`, and for larger work `to-spec` and `to-tickets` (GitHub issues, each asked first).

**Since 2026-10-21 (the owner's "Làm cả ba theo thứ tự đó", DECISIONS 2026-10-21), three plans in
order, each approved on its own:** (1) the safety plan, closed at 1a5e7aa except its real ChatGPT
line (the account's storage, see Active plan); (2) the web's should-fix list, closed at 3d2d02e;
**(3) next, to propose for approval: the docs and the configuration** (`2026-10-21-review-records-vs-code.md` sections
1 and 4, the api review's first-admin race, the web review's items 8 to 10). Still to raise with the
owner, on its own: DECISIONS section 3 "Cloudflare deployment, Q4 2026" is due and conflicts with the
FastAPI decision (the api cannot run on Workers); it needs open decisions 1 and 2 (a server
provider, a domain). After the three plans, the older list below still stands (items 5 and 7).

The owner approved the whole list on 2026-10-01 ("được, tôi duyệt toàn bộ, bạn làm giúp tôi đi")
and said again on 2026-10-02 at 01:43: "Làm giúp tôi đi". What remains, in order:

1. **Done on 2026-10-02 at b589041: the real gate's outdated check** (the plan's Evidence)
2. **ChatGPT and Cloudflare's check**: it came at 16:45 and at 21:51 on 2026-10-01, each time
   after a burst (18 turns had gone through between 20:27 and 21:21 before the 19th was
   challenged). On 2026-10-02 one turn alone at 02:06 and the gate's sixteen jobs from 04:37 to
   04:54 went through. Before any real ChatGPT run send one turn alone; space bursts hours
   apart; at the check, stop ChatGPT's runs and tell the owner; never pass it. It came again on
   2026-10-07 at 01:54 (the first turn after a restart) and had lifted by 11:30
3. **Done on 2026-10-02: the stop probe** (17:39, the driver pressed stop in all three turns) and
   **the picture turn** (the plan closed at d2d346d: a picture in 44s). **Done on 2026-10-07 at
   508c748: earlier nodes counted as this turn's when the read before the send fails** (the
   unread-thread plan)
4. **Done on 2026-10-08 at 63ec5dd: Gemini's own error sentence passing for a reply** (the plan
   `2026-10-08-gemini-failure-sentence.md`); the pause after such a failure stays, the owner's
   choice (DECISIONS 2026-10-08)
5. Rerun the Grok real gate when its turns allow (`python acceptance.py --real --keep --provider
   grok`), the one line of the first-open plan not yet run; on 2026-09-30 its first turn was
   walled and the agent interrupted it
6. **The owner's own, which the agent may not do** (its rules forbid deleting for good, whatever
   the yes): empty the Trash (three old session files that still hold credentials); delete by
   hand the test conversations listed in `docs/agent/residue-left-in-accounts.md`. **Done by the
   owner on 2026-10-02 at about 05:29: the ten ChatGPT threads the real gate of 04:37 left**
   (`scripts/purge_test_residue.py docs/agent/residue-to-delete-2026-10-02.json --yes`: "done: 10
   removed, 0 failed", each 200; the host worker was up but had not opened ChatGPT's browser, and
   no browser was left on a profile). That was ten more backend calls on ChatGPT at 05:29: count
   them when spacing the stop probe
7. Candidates for the next plan: the UI polish reviews' list (its plan, "Left open"), above all a
   reload with the phone's list open leaving a dead Back step; the gallery has no way to filter or
   group; media created before 8acdaa7 has no message_id and is merged into the thread by timestamp

Restart the host worker after any worker change: uvicorn does not reload there, the api does.
`PROVIDERS=chatgpt,grok,gemini /Users/keyti/Sources/RE/chatgpt/scripts/run-worker.sh` (by its full
path). Check `/health` says no `current_job` before stopping it, and that port 8000 is closed
after. The mock one for ui_smoke serves only `chatgpt`. On 2026-10-01 the app had quit and Docker
Desktop was off too, so api, web and worker were all down until restarted.

## Known traps

- **On the Windows machine Docker Desktop does not start by itself, and when it restarts the
  containers before the Ubuntu distro has mounted `/mnt/d`, the api's bind mount is empty**
  (2026-10-27, twice): the api logs `Could not import module "src.main"` (once with
  `WatchfilesRustInternalError ... /app/src: Bad address`) while compose reports it up, and the full
  gate stops at `full-gate: api does not answer on :3000`. Start Docker Desktop first, then
  `docker compose up -d --force-recreate` from WSL; the database sits on the `storage/db` bind
  mount and survives
- **On the Windows machine (2026-10-27) the kt hooks do not run**: `.claude/hooks/session-start.sh`
  and `stop-gate.py` call `python3`, which is the Microsoft Store alias there, so the session start
  prints no PROJECT, DECISIONS or HANDOFF section and the stop gate never checks this file. Read
  PROJECT.md and HANDOFF.md by hand at the start. The code and these notes assume macOS
  (`/Users/keyti/...`, `/tmp`, zsh, `pgrep` in `tests/test_session_profile.py`); `storage/`, `.env`
  and the venv were never on GitHub by design, and a profile is never copied, so the three providers
  most likely need a fresh login on a new machine (not tried)
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
- **macOS empties `/tmp` and `$TMPDIR` of files unused for three days**: on 2026-10-21 every probe
  script, worker log, mutant runner and kept gate workspace the plans' Evidence cites was gone (the
  kept workspaces were empty shells). A record a plan's Evidence relies on must be copied into
  `docs/agent/reviews/` or the plan itself before the session ends
- A gate interrupted after its stack started prints every check as "stack did not start"
  (`acceptance.py:1311-1316`); to interrupt one, signal the gate's python, not its shell wrapper
  (`pgrep -f` matches both)
- One browser per profile: Chromium refuses a second one. A worker killed while its browser is
  open leaves stale `Singleton*` files in the profile; the next launch opens all the same
- After a worker stops, the api still counts its providers as served for about 310 seconds
- The web container keeps its own node_modules in an anonymous volume: since plan (3) #3 the image
  installs with `npm ci` from the lockfile, so after a dependency or lockfile change run
  `docker compose build web && docker compose up -d --renew-anon-volumes web`; plain `up -d` keeps
  the old `node_modules` (measured 2026-10-27), and `npm install` inside the container rewrites the
  host's lockfile through the bind mount. `scripts/full-gate.sh` runs plain `up -d`, so on a machine
  with an old volume its ui_smoke can run on packages the lockfile does not name
- Docker Desktop being off looks exactly like a broken platform: the host worker still answers on
  8000 while web and api are silent
- A stale host worker has twice been mistaken for a broken feature: compare the process start time
  with the file mtime before believing a symptom
- The Docker api's database cannot be opened read-only from the host (`mode=ro` fails: Linux
  SQLite in the container removes the WAL and SHM files on the last close); read a copy of
  `storage/db/app.db` instead. The gate's own api runs on macOS, where they stay, so its reads work
- In the desktop app's Browser pane a screenshot taken right after an action can show the frame
  before it (2026-10-06: an empty message box after typing, so the agent typed again and the turn
  went out with its prompt twice). Read a field's value (`read_page`, or a read in
  `javascript_tool`) before pressing Send; when the pane stops drawing, drive the web with a headless
  cloakbrowser instead (`/tmp/real_video_walk.py`)
- A shell script that rewrites a docs/agent file must write what it read plus its change: on
  2026-10-07 one assignment that dropped the tail cut HANDOFF.md to 21 lines; it was rebuilt from the
  copy the session start had saved. Check the line count after every such write
- The long-dash hook reads a whole shell command, escapes included: count dashes in one command
  (`chr(8212)`), commit in the next. In zsh the exit code through a pipe is `${pipestatus[1]}`
  and there is no `timeout`

## Parked questions

- **`scripts/run-worker.sh` after #8** (2026-10-28): under bash (macOS `/bin/sh` is bash in sh
  mode) an exported `SHELLOPTS` or `BASHOPTS` comes back from `export -p` as readonly and stops the
  script at the `eval` (measured under bash 5.3; 3.2 not measured); `set -a` exports the api's lines
  of `.env` to the worker too; `tests/test_run_worker_env.py` is in no gate. Small tickets of their
  own if wanted
- **`create_api_key` still ends its failed transaction with a bare `ROLLBACK`**
  (`api/src/routes/auth.py`, found by both reviews of plan (3) #1): if SQLite has already rolled
  back on its own, "no transaction is active" replaces the real error. `register()` now uses the
  guarded `_rollback`; the same for `create_api_key` is a small ticket of its own
- **ui_smoke's layout checks depend on the test machine's fonts** (2026-10-27, Phase 0): the web
  names no font of its own, so what the checks measure is whatever face the test browser has. In
  WSL without Windows fonts that was DejaVu Sans and the Vietnamese phone nav took two rows at 360px
  (63px, 73/74); with the Windows fonts copied in it is Arial and 74/74. Phones render their own
  system face, which no machine here reproduces. A font of the web's own would make the measure the
  same everywhere (a code change, plan (3) or a ticket); the check is not loosened
- **`tests/provider_probe.py attachment` cannot press remove** (read 2026-10-27, not run): lines
  1014-1015 use `ATTACHMENT_PREVIEW` and `ATTACHMENT_REMOVE`, defined only in
  `worker/src/providers/chatgpt.py:30-31` and not in the probe's import (lines 28-30), so that step
  always raises `NameError`, which the probe reports as text. The driver itself is not affected
- **Two English error texts remain in the web, outside the web plan's file list** (the review of
  2026-10-22): `web/src/components/MediaImage.jsx` says "could not load image" and
  `web/src/components/FileCard.jsx` shows the raw English error, in both languages. Fixing them
  widens that plan's radius, so it waits for the owner (a one-line plan with point 7's mapping)
- **The quick gate's held-provider check has a 3s margin that heavy load can eat** (2026-10-22, load
  28 to 30 on 8 cores, once: Grok's waiting job was already done when ChatGPT's hold began). The
  other load failure, a start refused 503 right after the gate restarts its worker, is fixed in
  3d2d02e. Widen that margin in a plan of its own, or run the gates when the machine is quieter
- **The shared ChatGPT account's file storage fills with every reference picture** (found full on
  2026-10-22: "File added to chat only. You don't have enough storage space left to save this
  file"); the owner frees it by hand for now (DECISIONS 2026-10-22). A candidate plan: the driver
  removes its own upload from the account's file store once the turn is over (the upload's id comes
  back from `POST /backend-api/files`), or the platform tells users when the store is near full
- Left by the safety plan: the Grok driver's refusal quote takes the last three lines of `main`,
  which since 2026-10-22 are the site's new cookie banner ("Cookies Settings Reject All Accept All
  Cookies"), so the person reads that instead of the thread's own sentence ("High Demand: Grok is
  under heavy usage right now..."); and `_dismiss_overlays` knows the OneTrust ids only, not this
  banner (it does not cover the composer, measured). A failed first Grok turn leaves its thread in
  the account with no url stored on the platform (the orphan-thread class)
- Left by the image API plan, to measure: whether ChatGPT keeps a picture attached in the shared
  composer when a turn is cancelled or raises after the attach (`chatgpt.py` `_run`); if it does, the
  next person's turn sends it. A read-only probe on the real page, with ChatGPT off the worker
- Left by the image API plan: every JSON route still reads its whole body before the login is checked
  (200 MB to `/chat` took the api to 580 MB); `/v1/images` is capped, the rest wants a general cap;
  a picture sent with a request that fails or is cancelled stays on the person's message
- Left by the unread-thread plan: nodes an earlier ChatGPT turn still writes after the read before
  the send (one that hit the 300s ceiling, or a stop that did not press) can still be taken for this
  turn's; `python acceptance.py` runs the mock provider and never loads `chatgpt.py`, so its count
  says nothing about the ChatGPT driver
- Left by the Gemini video plan: the gallery tiles' footers do not line up; 26px tap targets across
  the app; a video is loaded whole (6 MB) before its player shows; the pending state's own markup,
  Gemini's daily video allowance and a turn that writes and makes a video at once are not measured;
  the owner's 13:19 video is only in the Gemini account (thread 1dfbd9cdd9657b27)
- Grok's free tier answers a short burst and then asks for about nine minutes; fully spent it says
  22 hours. Nothing but the page says so: `/rest/rate-limits` reports 7 of 7 for grok-4 and never
  decrements. The driver treats a turn that finishes carrying neither words nor a picture as a
  refusal, quotes the page, refunds and cools down. A walled turn still creates a thread. A paid
  tier is the only way to make Grok useful for a team; that is the owner's call
- Grok's upload flow (base64 to `/rest/app-chat/upload-file`, then `fileAttachments`) is unmeasured,
  which is why video script is unsupported there
- `tests/grok_probe.py` and the gate both create threads in the shared accounts. The probes delete
  their own; the gate's are deleted by the conversation delete, but a failed run can leave some
  behind (the Gemini gate leaves eight per run). `scripts/purge_test_residue.py` speaks only
  ChatGPT's `/backend-api`
- The whole archive is built in memory; fine for a team, a spooled file before SaaS
- A refused result's files are removed by the worker, measured in mock mode only
- `tests/test_runner_tombstones.py:73` still says "No join(): Runner names its Event _stop, which
  shadows Thread._stop"; since 26dc5fc the Event is `_halt` and `join()` works (a stale comment)
- The Gemini plan's open points, at the end of its Evidence: the row label check skipped on an
  empty title, only the first stream counted, a quota wall painted as an ordinary reply,
  multi-picture turns, a thread still opening right after its delete, how soon a sent turn's
  address becomes the thread's
- Left open by the picture rule's review (its plan's Evidence): a caption that comes more than
  about 10 seconds after the picture with no stop button is returned without its words (not seen
  on the real site); a picture node without a `create_time` misses the rule and the turn runs to
  the ceiling as before; why the picture of 04:46 was not on the page at 300 seconds
- **Grok and Gemini still send a turn stopped before its send** and never press their own stop
  (`gemini.py` `_run` checks for a stop only in the wait after `_send`); Gemini's look before
  speaking takes 2.9 to 4.5s, that much more time for a stop to come too early to be seen
- Not measured for the Gemini guard: the saved-info page with entries saved (an entry that brought
  a switch of its own would make the page read `unknown`, which does not block), both pages in a
  Vietnamese interface, a profile holding two Google accounts (`/u/1/...` reads `unknown`), and
  the new guard meeting personal context on. Seven review points stay open in the plan's "Left
  open": above all the broad `except` that reads the driver's own errors as `unknown`, and
  `memory` keeping the earlier look when a turn stops in `_open`
- **Sessions that die: the cause is not proven.** The remedy shipped at a0d04b0 (one profile and
  one pinned device per provider) and Gemini's login has outlived every earlier one; ChatGPT's
  Cloudflare check still came on the pinned device. If a login dies again under a profile, the
  lead (a new device at each launch, login-day cookies never written back) was wrong. The whole
  record and sixteen open review points are in the session plan's "Left open": above all a
  driver never recovers from a dead browser until the worker restarts, `pool.stop()` closes a
  browser from the wrong thread, and an aborted login leaves a profile that passes `start`
- From the hold-and-stop review, in that plan's "Left open": a stranded job requeued while its
  provider is held is still claimed once; `PROVIDER_HOLD_SECONDS` never reaches the Docker api
  (`docker-compose.yml` passes five variables only); the web still shows admin text for
  `provider_error` failures (ChatGPT logged out, a missing profile with its host path)
- **A new ChatGPT conversation asked "Tôi tên gì?" answers "Bạn tên là Keyti."**, on the old
  account (2026-10-01) and on the new one too (2026-10-02 02:06, one turn through the platform
  as a throwaway user, done in 22s, memory read `off`): the shared account's own identity
  reaches every platform user. A made-up name told in another conversation did not cross
  (2026-10-01). Where ChatGPT takes the name from is not traced (the account's profile name, or
  its personalization's "what should ChatGPT call you"); what to do about it is the owner's call
- The served window is pinned only against a wider one: a window a third as long would refuse a
  runner in the middle of a long turn in production, and nothing catches it. A throwaway-database
  test of `_served` against `_sweep_unserved` at W-1, W and W+1 would; it needs a new file under
  `tests/`
- A kept picture under `storage/diagnostics` can show the shared account's sidebar and another
  user's thread, and nothing removes old ones (first-open review, 2026-09-29)
- `tests/gemini_probe.py purge` still opens a row's menu by hovering a visible button, the flow the
  real page defeats; it fails safe (deletes nothing). Delete through the driver instead
- Seen in the Gemini rerun (2026-10-01): the video script's reply ends with two stray lines, "JPG"
  and a bullet "2", after the script itself; they look like the attached picture's chip, not traced
- From the busy-runner review (2026-09-29): a heartbeat answered with anything but 200 neither
  pings nor sets lost, and a stuck driver keeps its provider looking served
- On a phone (measured 2026-09-29): the composer's placeholder at 16px is cut (the English one
  needs 275px and has 267 at 390px, the Vietnamese one needs 317 and has 278); the header's title
  gives way to the select while a provider is unserved (about 112px left at 390px, 42 at 320);
  from 640px the nav shows the brand and the email while the chat keeps its phone layout up to
  767px, and in Vietnamese with a long email the nav wraps at 768-800px
- The UI polish reviews' list (eight points, four older ones from the design review) is in that
  plan's "Left open": a reload with the phone's list open leaves a dead Back step, the list can
  answer an older search than the box shows, the gallery says "Nothing generated yet." before it
  has loaded

## Active plan

- none. The last one closed, `docs/agent/plans/2026-10-22-web-should-fix.md` (base 1a5e7aa, tier 2,
  approved 2026-10-22 "Duyệt, làm ngay (Recommended)", the second of the three plans the owner
  ordered; its radius took `acceptance.py` for T7 with "Cho sửa gate (Recommended)"), closed on
  2026-10-22 at 3d2d02e, the marker removed after a clean audit (5 commits inside the radius), its
  Evidence written, pushed. **Full gate at 3d2d02e: 56/56, build, 74/74**; ten web mutants RED
  (`docs/agent/reviews/2026-10-22-web-*`). Commits: 87f907e red checks, 0d0452d the seven points,
  1a1b937 the review round, 526e75c the bubble under its own conversation, 3d2d02e the gate waits
  for a restarted worker.

Before it, `docs/agent/plans/2026-10-21-safety-of-data-and-credits.md` (tier 1) closed at 1a5e7aa,
pushed. **Its real ChatGPT line is NOT PASSED**: the shared account's file storage is full (the
attach said "You don't have enough storage space left to save this file", the turn failed and was
refunded). The owner frees the storage by hand (DECISIONS 2026-10-22, at `chatgpt.com/library`,
"Manage", or Settings, Storage); then, with ChatGPT on the worker, `set -a; . ./.env; set +a;
python3 docs/agent/reviews/2026-10-21-real-safety-runs.py chatgpt`, its line in that plan's
Evidence, push. Its Grok real line passed (2026-10-22 08:00). Its task log is in its Evidence.

Before them: `2026-10-09-chatgpt-image-api.md` (tier 1) at 4cd26c8,
`2026-10-08-gemini-failure-sentence.md` (tier 2) at 63ec5dd, `2026-10-06-chatgpt-unread-thread.md`
(tier 2) at 508c748, `2026-10-06-gemini-video-and-upload.md` (tier 2) at c691726 and
`2026-10-02-chatgpt-picture-wait.md` (tier 2) at d2d346d. The earlier plans' task logs are in
`docs/agent/HANDOFF-full-2026-10-02.md` and in each plan's Evidence.
