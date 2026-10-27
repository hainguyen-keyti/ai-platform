# Plan: Gemini names Google's unusual-traffic block instead of failing blind

## 1. Goal

The owner, 2026-09-27, on the driver misreading Google's block: **"Làm một plan nhỏ ngay"**; then,
after the correction that a turn fails with a generic message carrying the block page's url (which
encodes this network's address), **"Duyệt như trên"**, tier 3 with five mutants.

Measured 2026-09-27: after a day of automated Gemini traffic from this machine, every Gemini page
(the app, a thread) redirected to `https://www.google.com/sorry/index?continue=<path>&q=<token>`,
Google's unusual-traffic check; the `q` token starts with a 4-byte IPv4 address (decoded locally,
not printed). By the code today:

- `_open` (`gemini.py:227-243`) waits for a composer that never comes, two attempts of 30s, then
  raises `gemini did not open ...: composer False landed https://www.google.com/sorry/index?continue=/app&q=EgSr-nSaG`
  as a provider error. Those first 60 characters of the url carry the whole encoded address, and
  the web shows a failed job's error text to the user who ran it (`web/src/lib/api.js:85`)
- `_read_personal_context` (`gemini.py:175-215`) takes any page off gemini.google.com at its
  deadline as `signed-out`, so a reading taken during the block says "run
  scripts/login_provider.py gemini"
- `delete_thread` waits 30s for a composer and 20s more in `_thread_shows`, then raises "neither
  opened nor went back to /app"

Done means: a page on `www.google.com/sorry/` is recognised the moment it shows, in those three
places, and fails as a provider error (so the pool backs off, `pool.py:48`) with a message that
names the block, says to wait rather than log in again, and carries no url; the guard reads it as
`blocked`, which refuses the turn as `signed-out` does.

## 2. Non-goals

- Waiting out, solving or bypassing the check; no proxy, no humanize, no change to how cloakbrowser
  is launched (`gemini.py:151`)
- The rule that an unreadable switch reads `unknown` and does not block (DECISIONS 2026-09-27)
- ChatGPT's and Grok's drivers, the pool, the runner, the api and the web
- Any retry or wait beyond the pool's existing cooldown
- A new health field: the existing `memory` reading gains the value `blocked`

## 3. Invariants touched and risk tier

- **Isolation guard.** A turn is sent only when the guard reads `off` or `unknown`; `blocked` joins
  `on` and `signed-out` as refusing states, so the guard is not weakened
- **Quota.** A failed job is refunded exactly once, through the existing ProviderError path
- **What a user sees.** A failed job's error text carries no url query, so this network's address
  never reaches a team member
- **Pacing.** A blocked provider cools down (provider_error) instead of retrying into the wall

### Risk tier

**Tier 3**, the owner's choice on 2026-09-27: a small slice of one driver. No separate reviewer;
the coordinator runs acceptance with five mutants.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_gemini_driver.py   # N/N PASSED; the three new cases RED first on the current driver
python acceptance.py                                        # 34/34 PASSED, unchanged
python3 /tmp/run_gemini_mutants.py B1 B2 B3 B4 B5          # 5 of 5 red
```

Real: one turn attempt with the new driver while the block lasts (one page load): it fails at once
as a provider error naming the block, with no url, and nothing is sent. If the block has lifted by
then, the Evidence says "not confirmed on the real page"; it is never inferred.

## 5. Blast radius

```
worker/src/providers/gemini.py
tests/test_gemini_driver.py
docs/research/2026-09-27-gemini.md
```

## 6. Reuse pointers

- `worker/src/providers/gemini.py`: `_read_personal_context` (its `SIGNED_OUT_PATH` and off-site
  handling), `_guard`, `_open`, `delete_thread`
- `worker/src/providers/grok.py:21-23, 155-166`, `_wait_for_challenge`: the precedent of telling a
  challenge page from a signed-out session. Cloudflare's clears by itself; Google's does not, so
  Gemini fails at once instead of waiting
- `tests/test_gemini_driver.py`: "a settings page bounced to Google sign-in is a signed-out
  session, refused" and `ListPage(redirect=...)`, the patterns for the new cases
- `worker/src/pool.py:48`: provider_error cools down

## Tasks

### T1: Red tests and the measurement
Three cases on the fake page, each red on the current driver: a turn whose page lands on the block
fails at once as a provider error naming it, with no url in the message and nothing sent; the
guard reads a settings page on the block as `blocked` and the turn is refused as a provider error,
not as signed out; a thread deletion that meets the block is refused naming it, nothing deleted.
The research note records the block: the url's shape, the address in its token, what came before
it, the pages it covered.
**Files:** tests/test_gemini_driver.py, docs/research/2026-09-27-gemini.md
**Acceptance:** `tests/test_gemini_driver.py` shows exactly the three new cases failing, for those
reasons

### T2: The driver
One test of a url for the block (host `www.google.com`, path starting `/sorry/`) and one message,
checked right after each `goto` in `_open` and `delete_thread` and in the guard's loop; `last_open`
keeps the landed address without its query.
**Files:** worker/src/providers/gemini.py
**Acceptance:** `tests/test_gemini_driver.py` N/N; `python acceptance.py` 34/34; mutants B1 to B5
red: the recognition removed, `_open` not checking, the guard's `blocked` read as signed out, the
message carrying the url, `delete_thread` not checking

### T3: One real page, then Evidence
One turn attempt on the real site with the new driver (one page load), then the Evidence and close.
**Files:** none new
**Acceptance:** section 4

## Evidence

Closed 2026-09-27 at **743a586**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_gemini_driver.py` | **62/62 PASSED**; red first at 58/62 on 4dcf93b, exactly the four new records: a turn failed after 60s quoting `...&q=EgQKAAABb`, that url sat in the error a user sees, the guard read `signed-out` as provider_misconfigured, a deletion gave up after 20s without naming the block. After: a turn fails after 0s naming the block with no url, the guard reads `blocked` and refuses as a provider error with nothing sent, a deletion is refused after 0s |
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **34/34 PASSED**, build ok, **25/25 PASSED**, exit 0, at 743a586 with the host worker in mock; restored to real (chatgpt, grok) afterwards |
| `python3 /tmp/run_gemini_mutants.py B1 B2 B3 B4 B5` | **5 of 5 red**: the check never recognised, `_open` not looking, the guard reading it as signed out, the error carrying its url, `delete_thread` not looking; the whole set **49 of 49 red** |
| Real page (`/tmp/gemini_block_check.py`, `_open` only, one page load) | **Not confirmed on the real page**: 45 minutes after the block was seen the app opened in 6.1s, composer ready, so the new path could not be exercised. The block's handling is proven on the fake page only |

Deviation, narrowing: T3 opened the app through `_open` alone rather than a whole turn attempt, so
nothing would be sent if the block had lifted (it had).

Real page loads spent: one. Nothing was sent.
