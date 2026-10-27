# Plan: one browser profile and one device per provider

## 1. Goal

The owner, 2026-10-01. The request that surfaced it: **"đã xong cả 2, nhưng có lẻ tôi đăng nhập
account mới, cần bạn check kỹ, về các setting cần thiết"**. Then, as the day's two fresh logins
were lost: **"Đóng T4, rồi sửa gốc"**, **"Không làm gì"** (to the Google account, in the minutes it
was signed out), **"Dùng cloakbrowser đi, rồi làm tiếp"**, **"Dùng profile cố định của nó"**; in the
interview: **"Vừa đủ"** (the real runs), **"Tier 1"**, **"Cho đọc expires"**, **"Không cửa sổ, như
hiện nay"**; at approval: **"Duyệt, check tự xoá"**.

Measured 2026-10-01 (the section "Left open" at the end of this file has every number):

- A Gemini login saved at 15:18:40 read "Signed out" at 16:05 (Google's own account chooser), after
  four launches had used its file. Its cookies had not run out: every Google login cookie in the
  file carries an expiry 365 to 400 days away
- The ChatGPT login saved at 16:34 was opened by the real gate's browser at 16:35; from 16:45
  Cloudflare refused that browser ("cloudflare_challenge", then a 403 on a thread deletion), which
  no earlier gate had met. The agent interrupted the gate and sent nothing more
- Every `cloakbrowser.launch()` draws a random `--fingerprint` seed
  (`cloakbrowser/config.py:55-65`, version 0.5.10): two launches read "Apple M3", then "Apple M1
  Pro" as the GPU; with one `--fingerprint=24680` both read "Apple M2", 0 of 16 signals differing.
  Every place that opens a session launches that way and loads the login-day state file:
  `worker/src/providers/chatgpt.py:297`, `grok.py:145`, `gemini.py:167`,
  `scripts/login_provider.py:139`, `tests/grok_probe.py:86`, `tests/gemini_probe.py:64`
- No session is ever written back: the drivers' `stop` runs at shutdown on another thread than the
  browser's, and each state file kept its login time through days of worker runs
- Neither is shown to be why a session was ended; Grok's file of 2026-09-27 still works under both
- Measured without any account: `cloakbrowser.launch_persistent_context(dir, headless=True,
  args=["--fingerprint=N"])` keeps a cookie with an expiry, a cookie set by a response header and
  localStorage across launches; shows the same device at each; is refused to a second browser
  process ("Failed to create a ProcessSingleton for your profile directory"); survives its owner
  being killed (SIGTERM, SIGKILL, 2s or 40s after a cookie: no browser left, no lock file, the next
  launch opens, the cookie kept); and serves `context.request.get`, a second tab and
  `expect_download`. A cookie without an expiry is gone at a restart, and no login cookie of the
  three providers lacks one (names, domains and expiry read from the saved files with the owner's
  yes); Grok's `x-userid` does. A windowed and a windowless launch of one profile and seed agree on
  20 of 23 signals and differ in the screen's depth and pixel ratio and the window's size

Done means:

1. A provider's session is a browser profile, `<sessions>/<provider>/`, with a device seed drawn
   once and kept inside it. The login script, the three drivers and the two probes open that
   profile with that seed and nothing else; the gate's own worker gets the same directory
2. A second browser on a profile that is open is refused in words that name the provider, never
   answered with an empty or temporary session
3. What a session's browser learned is still there after its worker is killed
4. After the owner's logins, each provider still answers after four launches of its browser spread
   over at least two hours (the Gemini login of 2026-10-01 was gone after four launches in 47 minutes)

## 2. Non-goals

- Passing, solving or dodging any bot check: a challenge page, Cloudflare's banner or Google's
  unusual-traffic page stays a failure that stops the run, and the owner is told
- Upgrading cloakbrowser (0.5.10 stays); proxies; a worker whose browsers show a window (the
  owner's choice: windowless, as today)
- Pacing, polling, the lease, the hold, quota: unchanged
- Moving the old state files into the profiles (the owner logs in once per provider); deleting the
  old state files or any profile (the owner's data, asked separately)
- `acceptance.py`, the api, the web
- Why the gate's first picture job timed out on the composer at 16:37 (parked with
  `/tmp/picture_send_probe.py`); the "Keyti" identity question; Grok's and Gemini's own stop buttons

## 3. Invariants touched and risk tier

- One browser session per provider at a time. Was a rule kept by hand; becomes the profile's own
  lock: the second opener fails loudly
- A provider's credentials live only under the sessions directory (`storage/`, git-ignored), never
  in logs, chat or commits. Touched: the profile directory holds them now; the seed is not a secret
- A missing or signed-out session is refused, never papered over: no fall back to an anonymous or
  temporary browser, and an old state file lying beside a missing profile is not a session
- No turn goes into an account in a state the platform must not speak into (memory, personal
  context, signed out): unchanged, still read before every turn
- One credit per job, a job settles exactly once: untouched (no api change)

### Risk tier

**Tier 1**, the owner's choice on 2026-10-01 (sessions are the platform's auth): a review by a
strong model through a risk lens, at least 3 separate mutants, and after the fixes a scoped
re-review of the fixed part and the old repro.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_session_profile.py     # 8/8 PASSED (new)
~/cloakbrowser-env/bin/python tests/test_login_provider.py      # 7/7 PASSED (5 + 2)
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py    # 22/22 PASSED
~/cloakbrowser-env/bin/python tests/test_grok_memory.py         # 20/20 PASSED
~/cloakbrowser-env/bin/python tests/test_grok_settle.py         # 8/8 PASSED
~/cloakbrowser-env/bin/python tests/test_gemini_driver.py       # 62/62 PASSED
python acceptance.py                                            # 39/39 PASSED
(cd web && npm run build)                                       # exit 0
~/cloakbrowser-env/bin/python tests/ui_smoke.py                 # 53/53 PASSED
python tests/session_check.py chatgpt grok gemini               # real, after the logins: 3/3 PASSED, four times
python acceptance.py --real --keep                              # real ChatGPT: every check that runs passes (30 at 3e32a12)
~/cloakbrowser-env/bin/python /tmp/stop_probe.py after          # real ChatGPT: the driver presses the site's stop button
```

The new checks. `tests/test_session_profile.py` drives the real driver classes with a real browser
on a local page, in a sessions folder as this machine will have it (the old state file still lying
beside the profile); on db429a1 it reads **1/8**, checks 1 to 7 red, check 8 green as a guard:

1. chatgpt, 2. grok, 3. gemini: "every launch is the same device": three launches each name one
   `--fingerprint`, the seed kept in the profile, and a page reads the same GPU at each. Red today:
   no launch names a seed
4. "the seed is drawn once and each provider has its own": a seed file in each profile, a seed
   written before the first launch is the one used. Red today: no seed file
5. "what a browser learned outlives a killed worker": a child process opens the session, a local
   page sets a cookie, the child is killed; the next opener still has the cookie. Red today: lost
6. "a second browser on an open session is refused in words": while a child holds the session, the
   driver's open raises a provider error naming the provider. Red today: it opens
7. "a provider with no profile says so at start, an old state file notwithstanding": `start()`
   raises, naming `scripts/login_provider.py <provider>`. Red today: the state file is enough
8. "stop leaves the session free for the next opener": after `stop()` another process opens it.
   Green today (nothing locks): a guard, proven by mutant M7

`tests/test_login_provider.py`, on db429a1 **5/7**: 6. "the login opens the provider's own profile,
with a window, and writes no state file"; 7. "a profile open elsewhere is said in words and the
login gives up". Both run on fakes; no window opens in the test.

`tests/session_check.py` (new, standard library): registers a throwaway user, sends "Reply with
the single word: pong" to each provider named, reads the reply and the worker's health, deletes the
conversations it made (the owner's yes; `--keep` leaves them), prints a PASS/FAIL table and exits
non-zero on any failure. Proven both ways on the mock worker in T1: `chatgpt grok` with only chatgpt
served reads 1/2 and exits 1; `chatgpt` alone reads 1/1 and exits 0.

Mutants, each must turn its check red: M1 a driver launches without the seed (checks 1 to 3);
M2 the seed drawn again at every launch (1 to 4); M3 an open profile answered with a temporary one
(6); M4 a driver opens a context that is not the profile (5); M5 the login script opens another
directory than the drivers (login 6); M6 all providers share one profile (4); M7 `stop` leaves the
browser open (8); M8 an old state file counts as a session at start (7).

The real runs, the owner's choice ("Vừa đủ"), after the owner has logged in once per provider
inside its profile, spaced out, each provider's suites at least 30 minutes apart; **a bot check
anywhere stops that provider's runs, is recorded as NOT PASSED, and the owner is told**:

- Survival: the host worker started four times over at least two hours, `tests/session_check.py`
  after each start: 3/3 every time (12 turns), the worker's health reading memory off
- ChatGPT: one `session_check.py chatgpt` first; then the real gate and `/tmp/stop_probe.py after`
  (`last_stop` sent true, pressed true), the two lines the hold-and-stop plan left NOT PASSED
- Gemini: `/tmp/gemini_settings_sweep.py` (reads only: personal context off, activity retention
  on, what the Apps page and the saved-info switch show; any change needs the owner's yes); the
  acceptance's item 8 (`/tmp/e2e_gemini_item8.py`, 5/5); a word told in one conversation asked in
  a new one comes back unknown and is recalled in its own thread
- Grok: `/tmp/grok_stop_check.py`: a plain turn done, a stopped turn's result refused; and whether
  the account still answers after a restart without `x-userid`

## 5. Blast radius

```
worker/src/providers/session.py
worker/src/providers/chatgpt.py
worker/src/providers/grok.py
worker/src/providers/gemini.py
scripts/login_provider.py
tests/test_session_profile.py
tests/test_login_provider.py
tests/session_check.py
tests/gemini_probe.py
tests/grok_probe.py
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py:271-300`, `grok.py:121-147`, `gemini.py:144-169`: `start`,
  `stop`, `_ensure_page`, three copies of one shape; the shape stays, what they open changes
- `worker/src/providers/base.py`: `ProviderError`
- `scripts/login_provider.py`: `signed_in`, `page_stays`, `summarise`, `main`
- `tests/test_login_provider.py`: the fake context
- `tests/test_gemini_driver.py:547-580`: a real cloakbrowser on a local fixture inside a test
- `/tmp/persistent_profile_probe.py`, `/tmp/profile_lock_probe.py`, `/tmp/profile_kill_probe.py`,
  `/tmp/persistent_api_probe.py`, `/tmp/fingerprint_churn.py`, `/tmp/headed_headless_probe.py`: the
  measurements above, each rerunnable without an account
- `/tmp/who_am_i_check.py`: a turn through the platform's api, the shape of `tests/session_check.py`

## Tasks

### T1: Red tests and the check script
`tests/test_session_profile.py` and the two login checks, seen red on db429a1 for the reasons
above; `tests/session_check.py`, seen failing and passing on the mock worker. One probe more,
without an account: a profile whose browser process itself was killed opens again.
**Files:** tests/test_session_profile.py, tests/test_login_provider.py, tests/session_check.py
**Acceptance:** session profile 1/8 (checks 1 to 7 red, 8 a guard); login provider 5/7; session
check 1/2 exit 1 and 1/1 exit 0 on the mock worker

### T2: The profile and the seed in the drivers
`worker/src/providers/session.py`: the profile's seed (drawn once, kept inside it) and one way to
open it; an open profile raises a provider error in words. The three drivers open it, take its
first page, close it in `stop`, and `start` asks for the directory.
**Files:** worker/src/providers/session.py, worker/src/providers/chatgpt.py,
worker/src/providers/grok.py, worker/src/providers/gemini.py
**Acceptance:** session profile 8/8; composer 22/22; grok memory 20/20; grok settle 8/8; gemini
driver 62/62; `python acceptance.py` 39/39

### T3: The login script and the probes on the same profile
The login script opens the provider's profile with a window through the same function, waits for
the login as it does today, closes, and writes no state file; a profile in use is said in words.
The two probes open the profile the same way (the anonymous comparison keeps a plain launch).
**Files:** scripts/login_provider.py, tests/test_login_provider.py, tests/gemini_probe.py,
tests/grok_probe.py
**Acceptance:** login provider 7/7; both probes compile and, before any login, end by naming the
missing profile and the login command

### T4: Review, mutants, re-review, full gate
Tier 1: the review through a risk lens, M1 to M8 and the reviewer's own, fixes inside the radius
each red first, the scoped re-review, then the full gate once on a clean tree.
**Files:** none new
**Acceptance:** 0 blocking findings; every mutant red; `python acceptance.py` 39/39, build exit 0,
ui_smoke 53/53

### T5: The owner's logins and the real runs
Rollback prepared beforehand: the old state files are not touched and the plan's commits revert
cleanly, which brings the state-file drivers back (Grok's file works as long as its session lives).
The owner logs in once per provider with `scripts/login_provider.py` (Grok first, then ChatGPT,
then Gemini); the real runs of section 4 follow, spaced out; ACCESS.md, the repo's CLAUDE.md,
HANDOFF and DECISIONS say where a session lives now.
**Files:** none in the repo
**Acceptance:** section 4's real runs, each line PASSED or written NOT PASSED with the run's own
record

## Evidence

Closed 2026-10-01 at **a0d04b0**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once at the last commit: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **39/39 PASSED** exit 0, build exit 0, **53/53 PASSED** exit 0, at a0d04b0 with the host worker in mock, the tree clean before and after; the same once at 171b7b7, before the real runs: 39/39, build exit 0, 53/53 |
| `tests/test_session_profile.py` | **12/12**. Its first form on db429a1's drivers: **1/9**, checks 1 to 7 red (no launch named a seed, three launches read the GPU as M1, M4 Pro, M1; no seed file; the killed worker's cookie lost; a second browser opened; an old state file passed for a session), the stop check green as a guard, the ninth red (a driver opened a browser on the old file); 11/12 on 8e0d55a, exactly the second round's three seed cases (UnicodeDecodeError, ValueError, a used profile given a new seed) |
| `tests/test_login_provider.py` | **10/10**; 5/8 on db429a1's script (its own launch, `grok.json` written, no refusal, a ChatGPT cookie answered 401 taken for a sign-in); 9/10 on 8e0d55a's script (the settings tab opened 34 times in five minutes of an ended session's cookie; 5 after, and a proof that missed asked again 66s later) |
| `python tests/session_check.py --self-test` | **23/23** |
| `tests/session_check.py` on the mock worker | as the real check: FAIL "worker mode mock", 1/2 exit 1, where the first version passed; with `--mock`: 2/2 exit 0 |
| Offline suites at a0d04b0 | composer 22/22, grok memory 20/20, grok settle 8/8, gemini driver 62/62, runner liveness 4/4 |
| Review, tier 1, three passes (a strong model, risk lens) | db429a1..3b6db80: 1 blocking (the session check passed on a mock worker), 9 non-blocking, 13 of its 15 mutants through the tests; 8e0d55a: nothing blocking, 10 more through; 171b7b7: nothing blocking, "the first login still works", a race of two draws 0 of 1200. Fixed in 8e0d55a, 171b7b7 and a0d04b0 (tests only), each red first; the rest under "Left open" at the end of this file |
| Mutants on copies (`/tmp/run_session_mutants.py`) | **55 of 55 red**, each on its own check: the plan's thirteen, the first reviewer's fifteen, thirteen more from the re-reviews and fourteen for the rounds' own fixes (logs `/tmp/session_mutants*.log`) |
| The owner's logins, into the profiles | Grok 20:13 ("sso-rw and /rest/app-chat/conversations answered"), ChatGPT 20:14 ("session-token.0 and /backend-api/settings/user answered", the new proof's first real run), Gemini 20:16 ("__Secure-1PSID and .../personalization-settings stayed put") |
| Survival: `tests/session_check.py` after starts of the host worker | **Gemini PASS every time**: 20:27 (14s), 21:21 (34s), 21:52 (23s), 22:31 (36s), memory off; its profile opened 7 times in 2h15 after the login and stayed signed in, where the afternoon's login read "Signed out" after four launches in 47 minutes. **ChatGPT PASS at 20:27 (26s) and 21:21 (20s)**, then left out after Cloudflare's check at 21:51. **Grok no PASS**: memory on at 20:27 (refused before sending, the provider held out as designed), "grok never opened a thread for this turn" at 21:21, the free tier's wall at 21:27, "the turn never reached grok's composer" at 21:52, on a brand-new account whose page differs ("Type @ to search your apps (AI Agent)", a Grok Bot popover, a cookie banner); the probe's own plainer send got "pong" in 85s at 21:25. **NOT PASSED as written ("3/3 every time")** |
| `python acceptance.py --real --keep` (ChatGPT at a0d04b0, 20:59 to 21:19) | **29/30 PASSED, 9 skipped, exit 1**, no bot check in sixteen jobs; the picture job, the zip of a picture and the thread deletion that had failed at 16:37 and 16:45 passed; **"a running job can be cancelled": "at the site {'sent': False, 'pressed': False}"**, the hold-and-stop plan's line. The red: "deleting a conversation cancels its running job and refunds ... a new thread removed False": the check still wants a thread removed from a turn the driver no longer sends since 4536183 (`acceptance.py:763-770`), read from the same run's cancel check, not from that job's own record; the gate is outside this plan. **NOT PASSED as written** |
| `/tmp/stop_probe.py after` (ChatGPT, 21:50) | **NOT PASSED**: its first turn failed in 15s on "the provider showed its error banner: cloudflare_challengeRetry"; its report is empty; ChatGPT's runs stopped there |
| Gemini's settings, read only (20:25, 20:58) | plan PRO, personal context off (since 15:49), activity retention on, Google Workspace off, five other apps on (YouTube, Gemini Notebook, Google Flights, Google Hotels, Verify AI); the saved-info switch on, turned off at 21:08 with the owner's yes (read back off after a fresh load). A leak test through the platform (`/tmp/recall_check.py`): "Unknown" in a new conversation, recalled in its own thread. Item 8: chat 18s, a picture 44s 1024x559, a video script (Gemini's own error sentence at the first try, which the check of the time took for a script; 661 characters at the second) |
| Grok's settings, read only (21:07, 21:08) | `enableMemory` false (it read on at 20:27; the agent changed nothing), `allowXPersonalization` false |
| Grok, after the close (23:05 to 23:12, the owner's word to go on) | **the Grok line now PASSED**: the driver's open and typing on the new page, three times without pressing Enter (`/tmp/grok_send_probe.py`): the composer read the prompt each time, nothing over it; `tests/session_check.py grok --keep`: PASS, "pong" in 44s, memory off; `/tmp/grok_stop_check.py`: a plain turn done in 206s ("Paris"), a turn stopped 8s after its send: the worker's result refused 4.1s after the stop, the thread stored. The three failures of 21:21 to 21:52 sat around the free tier's wall of 21:27 and did not come back; nothing in the driver was changed |

Tier 1: the review through a risk lens, mutants, two scoped re-reviews. Deviations, all narrowing
and reported: the login test has 10 checks where the plan said 7, the profile test 12 where it said
8 (holes the reviews found), the session check carries its verdict's table and a deletion row (its
count reads 4/4 for three providers), the Gemini saved-info switch was turned off on the owner's word.
Shown: one profile and one device per provider, opened by everything that opens a session; a second
browser refused in words; what a browser learned kept through a killed worker; and a Gemini login
that outlived seven launches in 2h15. Not shown: that chatgpt.com's Cloudflare check stays away (it
came back at 21:51 on the pinned device, after the gate's twenty minutes), and that Grok works on its
new account (its page and its free tier, both outside this plan).

## Left open (moved from HANDOFF on 2026-10-02)

The lead on the sessions that died, as HANDOFF's Parked questions held it before this plan:

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

What the tier 1 review and its two re-reviews left open (non-blocking, not fixed):

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
