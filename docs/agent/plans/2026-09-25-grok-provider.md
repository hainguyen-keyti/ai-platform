# Plan: Grok as a second provider (chat and image)

## 1. Goal

"Giờ nghiên cứu và lên plan làm tiếp tục với Grok giúp tôi", with the two answers given when asked:
the account is a **free** Grok account, and the scope is **chat plus image**, that is parity with
what ChatGPT already does (chat, image, video script, one thread per conversation, delete the
thread when the conversation is deleted).

## 2. Non-goals

- Grok Imagine video generation. It is a new feature type, not a second provider for an existing
  one, and the free tier does not include video at all
- The x.com/i/grok surface: a different backend, GraphQL ids that rotate, an Arkose login, and by
  the wording of the consumer terms it is governed by X's terms rather than xAI's
- Any HTTP replay of the chat call, and any attempt to compute `x-statsig-id` ourselves
- Copying code from the surveyed projects: several carry no licence at all, one is GPL. They are
  read as measurements to verify, never as source
- Refactoring `worker/src/providers/chatgpt.py` into a shared base class. Two implementations are
  not three; extract only what the second one proves is duplicated
- Gemini, account pools, more than one account per provider
- Changing ChatGPT's launch options, selectors, or settle rules

## 3. Invariants touched and risk tier

- **Isolation.** One conversation, one thread, one owner, as today. A Grok thread url is never
  stored on a ChatGPT conversation and the reverse. The two provider sessions live in separate
  browsers and are never loaded into one context, so a Grok page can never read the ChatGPT session.
- **Quota conservation.** A Grok job charges one credit at create and refunds exactly once when it
  ends failed, cancelled or stranded. Unchanged rules, new provider.
- **Liveness (new).** A job whose provider no worker serves must not sit pending forever. Today it
  fails fast only as a side effect of a single unfiltered claim; once claims are filtered by
  provider that protection disappears, so it becomes explicit. This also closes an existing hole:
  with the worker off, every job sits pending forever and the user watches a typing bubble.
- **Pacing isolation (new).** A cooldown, a minimum gap or an image budget on one provider must not
  hold another. `pool.hold_seconds()` currently returns the maximum across all providers.

**Risk tier: 1.** A second set of account credentials, money-like quota accounting, a changed
api/worker claim contract, and a provider whose failure modes are easy to conflate (anti-bot 403
with `code:7`, quota 429, and a sign-in wall all look like "the provider is unwell").

## 4. Acceptance evidence

```bash
python acceptance.py                                   # 31/31 PASSED, exit 0   mock, chatgpt
python acceptance.py --provider grok                   # 31/31 PASSED, exit 0   mock, grok-named
python acceptance.py --real                            # 25/25 + 3 skipped, exit 0, unchanged
python acceptance.py --real --provider grok            # 9/9 PASSED, N skipped by name, exit 0
~/cloakbrowser-env/bin/python tests/ui_smoke.py        # 25/25 PASSED
cd web && npm run build                                # exit 0
~/cloakbrowser-env/bin/python tests/grok_probe.py all  # every probe prints a measurement, exit 0
```

Four new acceptance checks, each watched failing on the current code first:

| check | measures |
|---|---|
| `a second provider runs beside the first` | mock, `PROVIDERS=chatgpt,grok`: a chatgpt job and a grok job both finish, health lists a runner per provider, each with its own browser |
| `one provider's cooldown does not hold the other` | force a provider error on chatgpt, then a grok job still starts within one poll interval |
| `a job no worker serves is failed and refunded` | a worker serving only grok: a chatgpt job ends `no_worker` within the timeout and the credit comes back |
| `grok keeps one thread per conversation` | two turns in one conversation land on one thread, a second conversation gets another |

The real Grok gate is deliberately small because the account is free: api health, chat completes,
thread reused within a conversation, threads never cross conversations, an image produces a file,
delete removes the thread, health reports grok's own quota. Checks the free tier cannot exercise
are skipped by name with the reason, the way mock-only checks already are.

**Measured before writing this plan** (2026-09-24, recorded in docs/research/2026-09-25-grok-measurements.md):

- cloakbrowser headless clears grok.com's Cloudflare managed challenge by itself in about 14
  seconds: first response 403 "Performing security verification", composer present at t+14s. No
  human step, no Turnstile click
- the composer is `textarea[aria-label="Ask Grok anything"]`; typing and pressing Enter sends (the
  box empties and the message appears in the thread)
- grok.com sends turns over `wss://grok.com/ws/mgw/?uid=<uuid>`. No `POST /rest/app-chat/...` was
  observed for a turn
- an in-page `POST /rest/rate-limits` with `credentials:'include'` and no anti-bot header returns
  200: `{"windowSizeSeconds":14400,"remainingQueries":2,"totalQueries":2}` anonymously
- an anonymous turn is walled: the reply never arrives and the page offers "Sign up to continue"
- grok.com shows a OneTrust cookie dialog that can overlay the page
- two cloakbrowser browsers cannot be launched in one thread (Playwright sync API), but two threads
  each with one browser run side by side
- today a job for grok fails cleanly as `provider_error: provider grok unavailable: not enabled on
  this worker` and the credit is refunded, so the api, the database and the interface are already
  provider-agnostic
- `scripts/login_provider.py grok` pointed at x.com/i/grok and saved without verifying: it captured
  13 x.com cookies, no grok.com session, and the saved state opens grok.com signed out

**Not yet measured, and T1 exists to measure it:** whether a logged-in DOM send completes without
`403 code:7`, whether the thread url is `grok.com/c/<uuid>` and survives a reload, whether
`response-node.inflightResponses` is a usable settle signal, whether a free account can generate
images at all, what the free quota reads, whether delete works, and which composer cohort this
account gets.

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

- `worker/src/providers/chatgpt.py:288` `_open` (url verification, retry on 429), `:331` `_send`,
  `:445` `_settle_via_server` (server truth with a DOM gate), `:647` `_download`, `:737`
  `delete_thread`: the shape a Grok driver mirrors
- `worker/src/pool.py:14` `build_provider`, `:117` `execute` under a per-provider lock, `:24`
  `ProviderHealth`: where a second provider plugs in
- `worker/src/runner.py:38` the poll loop, `:58` `_claim`, `:65` `_heartbeat`: becomes one runner
  per provider
- `api/src/jobs.py:166` `claim_next_job`, `:115` `_sweep_stranded`: the claim filter and the
  no-worker sweep
- `worker/src/providers/mock.py`: already takes `name=`, so mock mode covers any provider name
- `acceptance.py:487` the skip-by-name pattern, `:244` running a sub-test as a check
- `tests/provider_probe.py`: the structure `tests/grok_probe.py` follows

## Tasks

### T1: A login that verifies, then the probes
Rewrite `scripts/login_provider.py` so grok opens `https://grok.com`, waits for the challenge,
polls until the session is really authenticated (a grok.com session cookie and no sign-in wall),
saves only then, and prints what it captured. No terminal Enter. Then `tests/grok_probe.py` with
the probes named in section 4, run once against the real session, measurements written to
`docs/research/2026-09-25-grok-measurements.md`.
**Files:** scripts/login_provider.py, tests/grok_probe.py, docs/research/*
**Acceptance:** the saved session opens grok.com signed in; every probe prints a measurement

### T2: Failing checks first
`--provider` on acceptance.py, per-provider capability skips, the four new checks, run red.
**Files:** acceptance.py, tests/ui_smoke.py
**Acceptance:** 27/31 and the four new ones red for the right reason

### T3: The worker serves more than one provider
One runner thread per configured provider, each owning its browser; pacing and cooldown read per
provider; health reports a section per runner.
**Files:** worker/src/runner.py, worker/src/main.py, worker/src/pool.py, worker/src/config.py, .env.example
**Acceptance:** the first two new checks green in mock

### T4: The api hands work to the right worker
`claim` takes the providers a worker serves; a pending job older than the no-worker timeout fails
as `no_worker` and refunds.
**Files:** api/src/jobs.py, api/src/models.py, api/src/routes/internal.py, api/src/config.py, .env.example
**Acceptance:** the third new check green in mock

### T5: The Grok provider
`worker/src/providers/grok.py`: open with the challenge wait, dismiss the cookie dialog, send
through the composer, settle on server truth with the DOM as fallback, collect images, keep the
thread url, delete a thread, read the quota, and classify anti-bot, quota and sign-in wall as
distinct error kinds.
**Files:** worker/src/providers/grok.py, worker/src/pool.py, worker/src/providers/base.py
**Acceptance:** the fourth new check green; `--real --provider grok` green

### T6: Tier 1 review
Mutants: the claim filter removed, the no-worker sweep removed, pacing shared again, a Grok
sign-in wall read as a reply, the Grok session loaded into the ChatGPT context.
**Files:** whatever the review names, inside the radius
**Acceptance:** 0 blocking findings, every mutant red

### T7: Gates and evidence
**Files:** none new
**Acceptance:** the numbers in section 4

## Evidence

Closed 2026-09-27 at **72ca6ed**, clean tree. Every number below was read from the command's own
count line and exit code, not from a wrapper.

| Command | Result | Where and when |
|---|---|---|
| `python acceptance.py` | **34/34 PASSED**, exit 0 | 72ca6ed, 2026-09-26 |
| `python acceptance.py --provider grok` | **34/34 PASSED**, exit 0 | 72ca6ed, 2026-09-27 |
| `python acceptance.py --real --provider grok` | **17/17 PASSED, 17 skipped**, exit 0 | 72ca6ed, 2026-09-26 23:11 |
| `python acceptance.py --real` | **28/28 PASSED, 6 skipped**, exit 0 | acceptance.py of f28b3f9, api and worker of 2031f57, 2026-09-25 12:24 |
| `python acceptance.py --real` | 14/28, exit 1, **outside this plan** | 72ca6ed, 2026-09-27 00:01, see below |
| `tests/test_runner_tombstones.py` | **3/3 PASSED** | 72ca6ed; red on the old runner first |
| `tests/grok_probe.py open` | challenge cleared in 7s, composer present, 25 threads | 2026-09-26, costs no turn |
| `tests/ui_smoke.py` | 25/25 at 2031f57, **not rerun** | needs the host worker switched to mock; no web or api change since |
| `cd web && npm run build` | exit 0 at 2031f57, **not rerun** | no web change since |

The forecast in section 4 was wrong in two places and the table above is what was measured: mock
has 34 checks, not 31, and the real grok gate counts 17 with 17 skipped by name, not 9.

**The ChatGPT real run at 72ca6ed is red for a reason outside this plan.** Every turn failed with
"composer never appeared; the session is probably logged out". Measured the same night without
spending a turn: the session is signed in (`/api/auth/session` 200 with `user` and `account`), no
dialog is open, and chatgpt.com has replaced `#prompt-textarea` with
`div.ProseMirror[contenteditable="true"][aria-label="Ask ChatGPT"]`, which has no id. The driver's
"logged out" is a guess, and a wrong one. Changing ChatGPT's selectors is a non-goal of this plan
(section 2), so the owner chose on 2026-09-27 to close this plan and fix the composer in a plan of
its own before Gemini.

Two deviations inside the radius, both found by the real gates, each seen red first:
- **f28b3f9**, acceptance.py: in real mode the no-worker check restarts the worker and nothing
  sent a turn afterwards, so `health reports the provider's memory setting` read `None` on a
  healthy account (27/28). One plain turn after the restart, only when the check is not skipped
- **72ca6ed**, worker runner and pool: while a provider held for its pacing gap the runner skipped
  tombstones entirely; the real grok gap is 150s and the check waits 60s. Before: 2 tombstone
  claims in a 14 minute run and no result. After: 70 claims, 1 result, the check green. A
  deletion now runs during a pacing gap and never during an error cooldown (a mutant ignoring the
  cooldown turns the test red)

Measured on the way and recorded in HANDOFF, not fixed here: the free tier walls a turn and still
creates a thread; the account holds 39 older threads left from before 72ca6ed; `Runner` shadows
`Thread._stop`; `threads never cross conversations` passes on an empty reply.
