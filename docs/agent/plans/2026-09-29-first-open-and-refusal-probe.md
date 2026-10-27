# Plan: ChatGPT's first open gets a second load; the gate's refusal probe uses a live picture

## 1. Goal

The owner, 2026-09-29, after the real runs at bbb3924: **"Lập plan nhỏ ngay"**, then **"Duyệt"**.

Measured 2026-09-29:

- the real ChatGPT gate (`--real --keep`, workspace ai-platform-acceptance-r0c4bg7o) was 29/30: its
  first turn, on a freshly launched browser, saw no composer within the 45s wait although the
  session was signed in (job a87a78e8, 11:56:16 to 11:57:04); every later turn opened fine. Three
  cold opens measured after, no turn sent (`/tmp/chatgpt_cold_open.py`): the composer showed at
  7.8s, 13.7s and 34.9s. The driver keeps no picture of the page, so what it showed is unknown.
  The stored thread path (`worker/src/providers/chatgpt.py:320-345`) waits the same 45s and, when
  the thread exists (status 200) but the composer is late, raises at once without trying again
- the real Grok gate (`--real --keep --provider grok`, workspace ai-platform-acceptance-3shmv4j6)
  was 19/20: the refusal check's video probe used the run's only picture, which the deletion check
  had removed (media rows 0 in the kept database), so the api answered 404 before 503, as designed

Done means: when the composer has not shown within the wait, the driver loads the page once more
and waits again before giving up, on the home page and on a stored thread the server says exists;
when it still gives up, the page is kept as one picture in the run's diagnostics folder next to its
media folder, and the error it raises is unchanged. The gate's refusal check probes a video script
only with a picture that still exists.

## 2. Non-goals

- The 45s wait itself, the error texts, the thread retry on 429 and 5xx
- The Grok and Gemini drivers; warming the browser when the worker starts
- Any other gate check, or the gate's order

## 3. Invariants touched and risk tier

None: a slow open still ends in the same provider error, refunded, as today; no job, quota or
conversation path changes.

### Risk tier

**Tier 2**: a change to the real browser flow. One code review round; acceptance with three
mutants; no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py   # 15/15 PASSED (12 + 3 new), the three new checks RED first
python acceptance.py                                            # 36/36 PASSED, unchanged
python acceptance.py --real --keep                              # the ChatGPT real gate once after the fix (real turns)
python acceptance.py --real --keep --provider grok              # NOT RUN until Grok's daily turns allow (the refusal check)
```

The three new checks, on the fake page: a composer that shows only on the second load of the home
page is waited for; the same on a stored thread that exists; a composer that never shows leaves
exactly one picture under the diagnostics folder and raises the same error. The gate change's red
is today's recorded Grok run; its green is the next real Grok gate.

Mutants, each red: no second load on the home page; no second load on a stored thread; no picture.

## 5. Blast radius

```
worker/src/providers/chatgpt.py
tests/test_chatgpt_composer.py
acceptance.py
```

## 6. Reuse pointers

- `tests/test_chatgpt_composer.py`: the fake page, the clock, `provider_on`
- `worker/src/providers/chatgpt.py`: `_open`, `_composer_ready`, `_thread_nodes`
- The kept workspaces of 2026-09-29 (`ai-platform-acceptance-r0c4bg7o`, `-3shmv4j6`)

## Tasks

### T1: Red checks
The three checks in `tests/test_chatgpt_composer.py`, as in section 4, each red on today's driver.
**Files:** tests/test_chatgpt_composer.py
**Acceptance:** `tests/test_chatgpt_composer.py` with exactly the three new checks red

### T2: The fixes
The second load and the picture in `_open`; the refusal check's video probe on a picture that
still exists.
**Files:** worker/src/providers/chatgpt.py, acceptance.py
**Acceptance:** `tests/test_chatgpt_composer.py` 15/15; `python acceptance.py` 36/36

### T3: Review, mutants, the real ChatGPT gate, Evidence
One code review round; the three mutants; the full gate once; the ChatGPT real gate once.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-29 at **3e32a12**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **45/45 PASSED**, exit 0, at 3e32a12 with the host worker in mock |
| `tests/test_chatgpt_composer.py` | red first at **12/15** on bbb3924 (1e260f3): one load of the home page, one load of a stored thread that exists (status 200), no picture; **17/17** now (two checks added by the review round) |
| Mutants on copies (`/tmp/run_open_mutants.py`, the composer test) | **8 of 8 red**: the plan's three (no second load of the home page, of a stored thread; no picture) and the review's five survivors of the first version (the thread falling back to a new chat, five home loads, a reload without the once-only flag, a failed picture escaping as an exception, no picture when the thread gives up) |
| `python acceptance.py --real --keep` (ChatGPT, once, host worker on `grok,gemini`) | **30/30 PASSED**, 6 skipped, exit 0, at 3e32a12 (29/30 at bbb3924). Its first turn opened in 27s and no picture was kept, so this run did not need the second load: the fix is proven by the fake page and the mutants, the real run shows no regression |
| The gate's refusal probe | red in two recorded real runs at bbb3924 (grok 19/20 and the third gemini run, both "video 404" after the delete check removed the run's only picture); mock gate "video 503" now; the probe skips only when the picture answers 404 (the review's note). `python acceptance.py --real --keep --provider grok`: **NOT RUN** yet, waiting for Grok's daily turns |

Review, tier 2: nothing blocking. Its test holes were closed by adding cases, accepted by the
review's own mutants going red. Its notes, not fixed here: a job cancelled during a slow open still
sends (pre-existing, `_open` never checks for a stop; the extra load widens that window), and a
picture of the page can show the shared account's sidebar and another user's thread, kept under
`storage/diagnostics` with no cleanup (gitignored, not served by the api).

Deviation: the test count is 17, not the planned 15, from the review round.
