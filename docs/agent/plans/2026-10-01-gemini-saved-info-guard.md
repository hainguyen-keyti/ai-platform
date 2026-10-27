# Plan: Gemini reads the saved-info switch before every turn

## 1. Goal

The owner, 2026-10-01: **"được, tôi duyệt toàn bộ, bạn làm giúp tôi đi"** (the list's third item:
the Gemini driver guards the saved-info switch), then, asked "Cho tôi làm plan này ngay bây giờ chứ
(driver Gemini tự canh công tắc saved info)?": **"Duyệt, làm ngay, tier 2 (Recommended)"**.

Measured on the account's own profile, 2026-10-01, nothing pressed except the one approved change
of 21:08 (the switch turned off):

- `gemini.google.com/saved-info` stays on `/saved-info` and shows exactly one
  `button[role="switch"]`, `aria-checked="true"` while the feature was on (20:25, 20:58, 21:08) and
  `"false"` since (21:08, 23:19). At 21:08 the very first poll that showed the switch read `true`
  (`/tmp/gemini_saved_info_off.py`, a poll every 500ms after `domcontentloaded`, as the driver
  polls). First switch after 4.2s; `/personalization-settings` took 6.6s in the same run (23:19)
- `/personalization-settings` shows only the personal context switch and links to `/apps` and
  `/saved-info`: the page the driver already loads says nothing about saved info
- The two switches carry the same generated id (`mat-mdc-slide-toggle-0-button`) and no
  `data-test-id`; their labels are words of the interface's language (English on this account,
  "Bật ..." on the first one, `docs/research/2026-09-27-gemini.md`). So a switch is told by the
  page it sits on and by being the only one there, never by its words
- Signed out (16:05, the session Google had ended), both addresses land on `/saved-info`, which
  then shows two switches, personal context first

Today `gemini.py` `_guard` reads personal context only (`_read_personal_context`, one tab, one
page); a turn goes out whatever the saved-info switch says, and `memory` in health reads `off`.

Done means: before every Gemini turn the driver reads both switches, each on its own page, in one
tab of its own; saved info on refuses the turn before anything is sent, as
`provider_misconfigured` (refunded, the provider held out), in words that name saved info and its
page; a saved-info page that cannot be read (no switch, more than one, another address) reads
`unknown` and does not block; a first page that already refuses (personal context on, signed out,
blocked) is the only one loaded; health's `memory` says `off` only when both switches read off;
and one real Gemini turn through the platform passes with `memory off`.

## 2. Non-goals

- The connected apps page (`/apps`) and the activity retention switch
- Turning either switch on, or a leak test with one on (the refusal on the real site is therefore
  not exercised: it would take turning the switch on)
- Keeping a reading from one turn to the next: both are read every turn
- Reading the switches from the page's rpcs instead of its two pages
- The ChatGPT and Grok drivers, the pool, the runner, the api, the web, the gate, the probes and
  the login script
- A new health field
- The rule that an unreadable switch reads `unknown` and does not block (DECISIONS 2026-09-27)

## 3. Invariants touched and risk tier

- **Isolation.** A turn is never sent while the shared Gemini account reads personal context on
  or saved info on; `unknown` does not block, as decided for all three providers
- **Quota.** A refused turn is refunded exactly once, through the existing
  `provider_misconfigured` path (nothing in the api changes)
- **One job, one turn.** The reads are page loads in a tab of their own: the conversation's page
  is never moved and nothing is typed or pressed
- **Honest health.** `memory` never says `off` on one reading alone

### Risk tier

**Tier 2**, the owner's choice on 2026-10-01: one review round by a separate reviewer; after
fixes, acceptance with mutants, no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_gemini_driver.py   # N/N PASSED (62/62 today); the new checks red first on a0d04b0, where /saved-info is never loaded
python acceptance.py                                        # 39/39 PASSED, unchanged
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: 39/39, build exit 0, 53/53
```

Mutants on a copy, each red: the saved-info page never loaded; saved info on still sending;
`unknown` blocking; several switches on the page read as the one; the saved-info page loaded
after personal context already refused; `memory` saying off on one reading; a reading reused on
the next turn; the settings tab left open.

Real, on the account's own profile, the host worker restarted on the new code:
`/tmp/gemini_guard_probe.py` (the guard alone, no turn) reads `memory off` and prints the seconds
each page took; then `python tests/session_check.py gemini --keep` passes (the word, worker mode
real, memory off), which since this plan takes both pages read.

## 5. Blast radius

```
worker/src/providers/gemini.py
tests/test_gemini_driver.py
docs/research/2026-09-27-gemini.md
```

## 6. Reuse pointers

- `worker/src/providers/gemini.py:181-236`: `_read_personal_context` (the tab of its own, the
  poll, blocked, signed out, the redirect that comes back) and `_guard`
- `worker/src/providers/grok.py` `_read_memory` and its refusal right after `_open`;
  `docs/agent/plans/2026-09-27-grok-memory-guard.md`, the same kind of plan at the same tier
- `tests/test_gemini_driver.py:48-78, 189-343, 533-540`: the fake `Box`, `Page` and `Context`;
  `:710-772` the settings checks; `:880-888` the redirect that comes back
- `worker/src/pool.py:221-224`: health already shows a provider's `memory`
- `tests/session_check.py`: a real turn passes only with worker mode real and memory off

## Tasks

### T1: Red checks, the fake's second page, the research note
The fake settings page gains the account's saved-info page (its own address, how many switches
it shows, the first one's state, where a load of it lands), a record of the addresses asked for
and of tabs opened and closed; a redirect chain plays on the first load only. New checks, red on
a0d04b0 unless marked as a guard: saved info on refuses the turn, in words naming it and its
page, and nothing is sent; both switches off read off, from two pages in one tab; a saved-info
switch that never renders, two switches, a switch that says neither true nor false, or a page
sent elsewhere on the site each read `unknown` and do not block; personal context unreadable and
saved info on still refuses; personal context unreadable and saved info off reads `unknown`,
never `off` (guard); Google's unusual-traffic check on the second page is a provider error;
personal context on, signed out or blocked on the first page load nothing more (guards); every
turn reads both again, so a switch turned on between two turns refuses the second; `memory` does
not keep an earlier reading; the settings tab is closed whatever was found (guard); a page that
fails to load does not stop the other from being read. The two existing checks that call
`_read_personal_context()` directly ask through `_guard()` and `memory` instead, green on
a0d04b0 before anything in the driver changes. The research note records the measurements above.
**Files:** tests/test_gemini_driver.py, docs/research/2026-09-27-gemini.md
**Acceptance:** `tests/test_gemini_driver.py` red on a0d04b0 on the new checks only, each for
the reason that the driver never loads `/saved-info`; the 62 existing checks still green

### T2: The guard reads both switches
One helper reads the single switch of a settings page it is given (its address and its own
path); `_guard` opens one tab, reads personal context, then saved info, refuses at the first
reading that refuses, sets `memory` to `off` only when both read off, and closes the tab.
`SAVED_INFO_ON` beside `PERSONAL_CONTEXT_ON`, whose text does not change.
**Files:** worker/src/providers/gemini.py
**Acceptance:** `tests/test_gemini_driver.py` N/N; `python acceptance.py` 39/39

### T3: Review, mutants, the full gate, the real turn, Evidence
One review round (tier 2); any fix seen red first; the mutants on a copy; the full gate once on
a clean tree with the host worker in mock; then the host worker back in real mode on the new
code, the guard alone on the real profile, and one real Gemini turn through the platform.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-10-02 at **e64575a**, clean tree, four commits (69a849c, c1da860, ce82755, e64575a),
the audit clean. Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_gemini_driver.py` | **111/111 PASSED**, exit 0. Red first twice: 66/83 on a0d04b0's driver (17 of the 21 new checks, each because `/saved-info` was never loaded: "loaded ['personalization-settings']", memory `off`, the turn sent; 4 green as guards); then 97/110 on ce82755's driver for the review's two fixes (13 checks: a page on another host read `off`, `off` believed at the first poll) |
| Full gate, once, at e64575a, clean tree, the host worker in mock (00:54 to 01:01) | `python acceptance.py` **39/39 PASSED** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **53/53 PASSED** exit 0; tree unchanged after |
| Mutants (`/tmp/run_gemini_saved_info_mutants.py`, each on a copy; log `/tmp/gemini_saved_info_mutants.log`) | **59 of 61 red** at e64575a: the plan's 20 (20 of 20 already at ce82755), the reviewer's 36 carried over to the fixed guard (26 of them had gone through the tests at ce82755), 5 for the round's own fixes. Not red: S02 (`page.goto` with its defaults: the fake does not model load events, left as it is) and T03 (a wait that never ends hangs the run; no check names it) |
| The guard alone on the real profile, the host worker stopped, no turn (`/tmp/gemini_guard_probe.py 2`) | at e64575a, 00:53: look 1 "would send in 4.5s, memory 'off'" (`/personalization-settings` off in 2.2s, `/saved-info` off in 1.8s), look 2 in 3.5s (1.7s, 1.5s); one tab open after each look, exit 0. Before the second poll, at ce82755, 00:02: 4.4s (2.6s, 1.5s) and 2.6s (1.1s, 1.4s) |
| One real turn through the platform, the host worker in real mode at e64575a (`python tests/session_check.py gemini --keep`, 01:02) | "[PASS] gemini answers  done in 18s, reply 'pong', worker mode real, memory off", **1/1 PASSED**, exit 0; health after it: gemini `memory` off, `last_settle` server |
| Every other offline suite at e64575a | composer 22/22, grok memory 20/20, grok settle 8/8, liveness 4/4, login provider 10/10, runner health 4/4, runner tombstones 3/3, tombstones 5/5, session profile 12/12, the session check's table 23/23 |

Review, tier 2: one round by a separate reviewer (80 tool uses; read-only on the repo, pages on
127.0.0.1 only). **Nothing blocking**: no path types or sends a turn after either switch read on,
and `memory` never says `off` unless both pages read off in that look. Eight non-blocking points
and 26 of its 36 mutants through the tests. Fixed in e64575a, each seen red first:

- A switch is read only on `gemini.google.com` itself: before, a load ending on another host with
  the same path and one switch read `off`
- `off` is believed only when two polls in a row say so, `on` at once, and a value that is neither
  keeps the look waiting: the note's evidence was one first sighting at 500ms spacing, which cannot
  rule out a default shorter than a poll. Cost: 0.5s a page
- The tests gained what the mutants went through: a switch that paints late (7s; 10s on each
  page, each with its own wait), a first page unreadable in five ways with saved info still read,
  a tab that is kept, will not close or cannot be opened, a look skipped or made late for a
  reopened thread or a picture (nothing is handed over before the look), a redirect that comes
  back on either load, a slash or a query after an address, the refusal's words. The fake page
  now tells a closed tab from an open one and answers only `button[role="switch"]`

Not fixed, under "Left open" at the end of this file with the reviewer's repros (`/tmp/rv_gsi/`): the broad
`except` that reads the driver's own errors as `unknown`; `memory` keeping the earlier look when a
turn stops in `_open`; a profile with two Google accounts (`/u/1/...` reads `unknown`); the look's
worst case, about 151s where it was 75s; a switch that turns on later than a poll after its first
paint; the login script proving a login on the settings page only; `goto` with its defaults.

Not passed as written: nothing. Not exercised, as the non-goals say: the refusal on the real
site (the driver has never met either switch on since this guard; the fake's on is the page's
`aria-checked="true"`, read on the real page at 21:08 on 2026-10-01 by a script polling as the
driver polls).

Deviations, both narrowing or inside the plan's words: the two older checks that called
`_read_personal_context()` ask through `_guard()` and `memory` (in the plan's T1); ce82755 was not
planned: the plan's own mutant run showed a refusing guard stopping the test run instead of
failing a check, and its message says more than it did (a guard that refuses everything still
stops the run at an older check after two named failures). One file was written through the shell
once during the review round (`tests/test_gemini_driver.py`, inside the radius; the audit above
covers it).

What a turn costs now: the look takes 3.5 to 4.5s on the real profile where one page took 1.1 to
2.6s, and each turn loads three documents on the account instead of two. Real Gemini turns
spent: one ("pong", kept in the account and in the platform's throwaway user). The profile was
opened three times for this plan (00:02, 00:53, 01:02) and was still signed in 4h46 after its
login.

Afterwards, 2026-10-02, at the owner's word ("Cho làm", 01:10): the refusal on the real site,
which the non-goals had left out. `/tmp/gemini_saved_info_on_check.py` at e64575a, the host
worker stopped, one browser launch, no turn sent, 01:26:15 to 01:26:39 (log
`/tmp/gemini_saved_info_on_check.log`):

| Step | What the run printed |
|---|---|
| Before | the page's one switch `false`; the driver's look "would send in 3.3s, memory 'off'" |
| Pressed on, 01:26:26 | no dialog; right after and after a fresh load: `true` |
| **The driver's look with it on** | **"REFUSED (provider_misconfigured): the shared Gemini account has saved info switched on, so this turn was not sent; ask the account owner to turn it off (gemini.google.com/saved-info) and try again" in 2.9s, memory 'on'** (`/personalization-settings` off in 1.6s, `/saved-info` on in 1.2s) |
| Pressed off, 01:26:35 | no dialog; a fresh load: `false`; "it was on for about 10s" |
| After | the driver's look "would send in 3.1s, memory 'off'"; two tabs open before closing (the conversation's and the script's own), no browser left on the profile |

The research note records it (302a274). Full gate once more at 302a274, clean tree, the host
worker in mock (01:27 to 01:34): `python acceptance.py` **39/39 PASSED** exit 0, `npm run build`
exit 0, `tests/ui_smoke.py` **53/53 PASSED** exit 0. Pushed: e64575a at 01:12 and 302a274 at
01:36, `origin/master` at 302a274 (the owner's standing yes of 2026-10-02 for a push after a
plan closes with its gate green). The host worker is back in real mode at 302a274.

## Left open (moved from HANDOFF on 2026-10-02)

What the tier 2 review left open (non-blocking, not fixed):

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
