# Plan: ChatGPT's new composer

## 1. Goal

The owner, 2026-09-27: **"Đóng Grok, sửa ChatGPT, rồi mới Gemini"**. ChatGPT works on the platform
again with chat, image, video script, files, zips and delete, and the real gate is green.

Measured the same night without spending a turn: chatgpt.com replaced `#prompt-textarea` with
`div.ProseMirror[contenteditable="true"][aria-label="Ask ChatGPT"]`, which has no id. The session
is signed in (`/api/auth/session` answers 200 with `user` and `account`), no dialog is open, and
every turn dies in `_open` with "composer never appeared; the session is probably logged out", a
wrong guess. The real gate at 72ca6ed read 14/28 for that reason alone.

**Widened by the owner on 2026-09-27, after T1.** T1 measured that not only the composer changed:
every `[data-message-author-role]`, the stop button, the send button's testid and `#upload-files`
are gone too (docs/research/2026-09-27-chatgpt-composer.md). The owner chose to fix the whole new
page contract in this plan, raise it to tier 1, and add the fixtures to the radius. The sections
below are the widened contract; T1 was run and committed under the original one.

## 2. Non-goals

- No shared ProseMirror helper or base class between `grok.py` and `chatgpt.py`: copy grok's four
  small methods; extract later only if Gemini proves a third copy
- No change to the settle RULE (a turn is over when the server says so), the memory guard, pacing,
  or thread handling. The page signals that feed the settle (the stop button) and the scoping of
  images and banners are in scope, because T1 measured them dead
- No Work mode, Plugins, Scheduled or Projects
- No fix for `Runner._stop` shadowing `Thread._stop`, nor for `threads never cross conversations`
  passing on an empty reply (both parked in HANDOFF)
- No api, web or Gemini change

## 3. Invariants touched and risk tier

- **One job, one turn.** ProseMirror ignores `fill()`, and `keyboard.type()` maps every newline to
  Enter; a replayed history carries newlines, so the wrong fix sends one prompt as several turns.
  `insert_text` plus a flattened read-back, the way grok does it
- **Isolation.** `_open`'s check that the url is the thread that was asked for stays as it is, and
  the memory guard still runs before the send
- **Quota.** Unchanged: a failed turn is refunded exactly once
- **An error is never stored as an answer.** The banner detector (`chatgpt.py:216`) only looks
  inside an assistant turn found by `[data-message-author-role]`, which no longer exists, so today
  a banner would pass as a reply (the defect fixed on 2026-09-23)
- **A user's picture is never returned as a generated one.** `chatgpt.py:72-73` skips images inside
  a user turn by the same attribute; a video script job uploads a reference picture into the thread

### Risk tier

**Tier 1** (raised by the owner after T1): two of the invariants above have been paid for before.
A strong reviewer through a risk lens with at least three separate mutants, and after fixes a
scoped re-review of the fixed part and the old repro.

## 4. Acceptance evidence

```
python acceptance.py --real                                     # 28/28 PASSED, 6 skipped, exit 0 (RED today: 14/28)
python acceptance.py                                            # 34/34 PASSED, exit 0
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py    # N/N PASSED, seen red first
~/cloakbrowser-env/bin/python tests/provider_probe.py send      # the turn lands as one turn
~/cloakbrowser-env/bin/python tests/test_dom_signatures.py      # N/N PASSED on fixtures of the NEW page
```

Mock never loads the driver, so the mock gate is a regression guard here, never the proof; the
proof is the real gate and the probe (LESSONS, 2026-09-25).

Mutants for T4, each must turn something red: `keyboard.type` instead of `insert_text` on a
multi-line prompt; only the old `#prompt-textarea`; typing before the ProseMirror mounts (the
textarea placeholder accepted as ready); the "logged out" message restored while the session is
signed in; the banner detector no longer scoped to the assistant's turn; the user-image skip
removed. (`fill()` restored is dropped as a mutant: T1 measured that fill() works on this
composer, so it cannot go red for the right reason.)

## 5. Blast radius

```
worker/src/providers/chatgpt.py
tests/test_chatgpt_composer.py
tests/provider_probe.py
tests/test_dom_signatures.py
tests/fixtures/*
docs/research/*
acceptance.py
```

`acceptance.py` was added by the owner on 2026-09-27 during T3, for one line only: `:310`
required the signature test to print exactly `4/4`, and T2's three new cases made it `7/7`, so the
mock gate read 33/34 on a green test. The condition becomes "every case passed and there are at
least 7", nothing else in the file changes.

## 6. Reuse pointers

- `worker/src/providers/grok.py:240-300`: `_flat`, `_composer_text`, `_clear_composer`, and `_send`
  with read-back, retry from an empty box, and `insert_text`
- `worker/src/providers/chatgpt.py:280` `_composer_ready`, `:288` `_open`, `:331` `_send`, `:681`
  the upload step
- `tests/provider_probe.py`: the probe structure the T1 measurements extend
- `/tmp/chatgpt_open.py` from 2026-09-27: the no-turn measurement that found the change

## Tasks

### T1: Measure the new page
Up to three real turns. Composer selector; whether a multi-line prompt typed with `insert_text`
goes out as one turn; whether Enter sends; the send and stop buttons; the assistant turn
selector; `#upload-files`; whether `/backend-api/conversation/<id>` and the memory read
(`settings.m3m`) still answer; which of Chat and Work is the default. Written to
`docs/research/2026-09-27-chatgpt-composer.md`.
**Files:** tests/provider_probe.py, docs/research/*
**Acceptance:** every item above prints a measurement

### T2: Red tests first
A fake page drives `_open` and `_send`: the new composer is found, the placeholder textarea is not
taken as ready; a signed-in session with no composer is not reported as logged out; a multi-line
prompt produces exactly one Enter. New fixtures captured from the new page by the probe (a reply,
the healthy main area, and the error banner) replace the old ones, and `test_dom_signatures.py`
is pointed at them, so the banner and the user-image scoping are checked against real markup.
**Files:** tests/test_chatgpt_composer.py, tests/provider_probe.py, tests/fixtures/*,
tests/test_dom_signatures.py
**Acceptance:** both red on 72ca6ed for the right reasons (the banner not recognised inside the new
markup, the composer not found)

### T3: The driver
The new page contract in one place: composer cohort list (the new ProseMirror first, the old id
kept as a fallback in case the site is A/B testing, as grok's two cohorts were) and readiness that
waits for it rather than the placeholder; `_send` through `insert_text` with a flattened read-back
and a retry from an empty box; the send button by `aria-label="Send"` or the composer form's
submit; the turn markers T1 measured (`data-conversation-role` and friends) in place of
`[data-message-author-role]` for the baseline, the reply text, the user-image skip and the banner
scope; a page-finished signal that does not need the stop button, so the server is still asked
only a few times a turn; the upload input by `accept="image/*"`; and an open error that asks
`/api/auth/session` before it says "logged out". Anything T2's fixtures show that T1 did not is
measured first, not guessed.
**Files:** worker/src/providers/chatgpt.py
**Acceptance:** T2 green; `python acceptance.py` 34/34

### T4: Review, tier 1
A strong reviewer through a risk lens; the mutants in section 4 each red; after fixes a scoped
re-review of the fixed part and the old repro.
**Files:** whatever the review names, inside the radius
**Acceptance:** 0 blocking findings

### T5: Gates and Evidence
**Files:** none new
**Acceptance:** the numbers in section 4

## Evidence

Closed 2026-09-27 at **280cbfe**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| `python acceptance.py --real` | **28/28 PASSED, 6 skipped**, exit 0 (14/28 at 72ca6ed before this plan): image 871207 bytes, video script 886 chars with its reference picture uploaded, files and zip kept, thread deleted, memory off |
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **34/34 PASSED**, build ok, **25/25 PASSED**, exit 0, host worker in mock at 280cbfe |
| `tests/test_chatgpt_composer.py` | **12/12 PASSED**, red first at 4/8 on the old driver |
| `tests/test_dom_signatures.py` | **10/10 PASSED** on fixtures of the new page, red first at 4/7 |
| `tests/provider_probe.py send` | `success=True settle=server memory=off 14s`, the turn request `/backend-api/f/conversation` sent once |
| Mutants | **13 of 13 red**: keyboard.type, old composer only, placeholder taken as ready, signed-in called logged out, old banner shape only, user-image skip removed, `local-chatgpt:` taken as a thread, a draft never cleared (the prompt itself left in the box went out twice), old reply selector, a one-character read-back, an earlier turn's picture kept, any role=alert counted, a box that would not clear typed into |

Review, tier 1: one strong reviewer through a risk lens, then a scoped re-review. Nothing blocking;
findings on the earlier turn's picture, the neutral alert, the cut-short paste, the box that would
not clear and the untested reply selector were fixed with cases seen red first. It also proved one
mutant I had called equivalent was not.

Deviations, each approved by the owner: widened after T1 to the whole new page contract and tier 1
(fixtures and `test_dom_signatures.py` into the radius); widened in T3 for `acceptance.py:310`,
which demanded exactly `4/4` from a test that had grown to seven cases.

Real turns spent: four (two in T1 and T3 measurement, the gate's own, one probe send). The probe
threads were deleted with the owner's yes (6ab805cb, 6ab80afc, 6ab81576, each 404 afterwards).

Left open, non-blocking: before a new reply paints its start marker, only the DOM fallback could
still take the previous turn's picture; `SESSION_TOKEN` swallows errors, so a challenge page can
still read as logged out; no test attaches a reference picture through `UPLOAD_INPUT` (the real
gate's video script check does); `probe_send` still captures fixtures with the old selectors.

