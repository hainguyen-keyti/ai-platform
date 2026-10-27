# Plan: close the open measurements, guard the shared account, one zip per conversation

## 1. Goal

"hoàn thành các công việc hiện tại trước đi rồi mới làm plan hướng tiếp theo như là test kỹ lại và
đo và nhưng cái cần tôi quyết định thì cứ làm sản phẩm tốt nhất là được, pháp lý tôi lo được"

Every parked question in HANDOFF as of 8533270 is measured and either closed in code or recorded
with its measurement. Items that were "the owner's call" are settled in favour of the best product,
except one-way deletions inside the owner's ChatGPT account, which still wait for a yes.

## 2. Non-goals

- The schema and interface batch (message tree, media parents, thumbnails, usage log, quota
  refill, rename, search, Vietnamese strings, mobile, trash) is the next plan. Library cleanup
  rides on the trash feature there; here only the endpoint is measured
- Account pool, Grok, Gemini, patchright, R2
- Deleting anything in the shared ChatGPT account beyond the one thread a probe itself created
  seconds earlier
- English text matching on any provider element; shapes only (data-testid, role, class), measured
- Changing how a reply is settled while the server view is readable
- Rewriting prompts so the model produces ten separate pictures; the model returns what it returns

## 3. Invariants touched and risk tier

- **Isolation.** No turn is sent into the shared account while its memory is on. Today nothing
  checks; anyone flipping the switch re-opens the leak measured on 2026-09-23. New guard, tested
  in mock (turn refused, no thread created) and real (the setting is read from the account).
  An unreadable setting is reported as "unknown" and does not block; it is visible in health.
- **Quota conservation.** A refused turn refunds exactly once; the new error kind rides the
  existing failed-job refund.
- **Ownership.** The conversation zip serves only the owner's media (another user gets 404), the
  same rule every media route follows.

**Risk tier: 1.** A security guard on the shared account, a new error kind in the api/worker
contract, a new authenticated download route. Strong-model review through a risk lens with at
least 3 mutants; scoped re-review after fixes.

## 4. Acceptance evidence

```bash
python acceptance.py                                  # 22/22 PASSED, exit 0
python acceptance.py --real                           # 19/19 PASSED, 3 skipped in this mode, exit 0
~/cloakbrowser-env/bin/python tests/ui_smoke.py       # 19/19 PASSED   (mock worker, MOCK_DELAY_SECONDS=4)
~/cloakbrowser-env/bin/python tests/provider_probe.py # every probe prints a measurement, exit 0
```

Four new acceptance checks, each watched failing on the current code first:

| check | measures |
|---|---|
| `memory on refuses the turn and refunds` | mock only: a trigger phrase makes the mock report memory on; job `failed`, error kind `provider_misconfigured`, credit back, no thread stored on the conversation, health shows memory `on` |
| `health reports the provider's memory setting` | both modes: after a turn, `providers.chatgpt.memory` is `off` (real: read from the account, not assumed) |
| `a conversation's media downloads as one zip` | both modes: `GET /conversations/{id}/media.zip` on the conversation holding a picture and a zip returns `application/zip` whose entries equal the media count (2); another user gets 404 |
| `the provider's error banner is recognised by shape` | both modes: `tests/test_dom_signatures.py` under the venv: the captured banner fixture is detected, a normal-reply fixture is not, 2/2 |

One new ui_smoke check: `download all media as one zip` (a header button on the conversation,
caught with `expect_download`, a zip with 2 entries).

Probes in `tests/provider_probe.py`, one subcommand each, output recorded in Evidence whatever it
shows:

- `send`: which request the composer fires on Enter (method and path), seen through
  `page.on("request")`
- `banner`: fail that request with 500 through `page.route`; list what appears (tag, role,
  data-testid, class, text length); save the snippet as `tests/fixtures/chatgpt_error_banner.html`
  and a normal reply as `tests/fixtures/chatgpt_reply.html`
- `memory`: which endpoint carries the memory toggle (network capture while opening Settings,
  Personalization) and its value now; also `memory_scope` on a conversation
- `dom-settle`: fail the conversation GET through `page.route` so the provider settles on the DOM;
  compare the DOM text with the server text read afterwards; print the seconds between the stop
  button leaving and the last text change
- `cleanup`: delete the thread the probe itself just created, through whatever request the site's
  own delete fires (measured), and confirm the server answers 404 afterwards

Measured before writing: none of these. cloakbrowser's `page.route` is assumed to behave like
Playwright's and is confirmed or refuted by the first probe that uses it.

## 5. Blast radius

```
acceptance.py
api/*
worker/*
web/*
tests/*
.env.example
docs/research/*
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py:301` `_thread_nodes`: a token-bearing fetch from inside the
  page; the memory read follows it
- `worker/src/providers/chatgpt.py:230` `_open` and `:561` `_send`: the guard runs between them
- `worker/src/providers/chatgpt.py:327` `_settle_via_server` and `:453` `_await_result`: the
  once-a-second loops where the banner check belongs; `:507` `expect_download` already in use
- `worker/src/pool.py:150` maps `ProviderError` to a kind; `:171` exposes provider diagnostics
- `worker/src/providers/mock.py:16` trigger phrases and `:83` the provider-error path to copy
- `api/src/routes/media.py:39` `_owned`, `:47` `_safe_path`, `:75` the file route: ownership and
  path rules the zip route must keep
- `api/src/routes/conversations.py:24` the ownership query for a conversation
- `web/src/components/FileCard.jsx:17` `save` and `web/src/lib/api.js:57` `mediaBlobUrl`:
  authenticated download of bytes
- `acceptance.py:393` `check_zip` and `:487` the skip-in-real pattern; `tests/ui_smoke.py:175`
  the file-card step

## Tasks

### T1: Failing checks first
Four acceptance checks, one ui_smoke check, and `tests/test_dom_signatures.py` that fails for lack
of a fixture, all run against the current code.
**Files:** acceptance.py, tests/ui_smoke.py, tests/test_dom_signatures.py
**Acceptance:** 18/22 and 18/19, the new ones red for the right reason

### T2: Probes and measurements
`tests/provider_probe.py` with the five subcommands, run against the real session with the host
worker stopped; fixtures saved; measurements written to `docs/research/2026-09-24-provider-measurements.md`.
**Files:** tests/provider_probe.py, tests/fixtures/*, docs/research/*
**Acceptance:** each probe prints a measurement; nothing silently skipped

### T3: Memory guard
`ProviderError` carries a kind. The ChatGPT provider reads the memory setting once per job after
the page is on the site and before sending (endpoint from T2), keeps the state for health, and
refuses with `provider_misconfigured` when memory is on. The pool passes the kind through, opens no
cooldown for it, and exposes `memory` in health. The mock gains a trigger phrase.
**Files:** worker/src/providers/base.py, worker/src/providers/chatgpt.py, worker/src/providers/mock.py, worker/src/pool.py
**Acceptance:** both memory checks green in mock; the real check reads `off` from the account

### T4: Error banner by shape
A detector written from the fixture's shape; both settle loops raise `ProviderError` when it shows
and no assistant node has finished.
**Files:** worker/src/providers/chatgpt.py
**Acceptance:** signature check 2/2; mock and real gates unchanged

### T5: One zip per conversation
`GET /conversations/{id}/media.zip` (owner only, optional `message_id`), a header button
"Download all (N)" when the conversation holds two or more media, the same on a message with two
or more.
**Files:** api/src/routes/conversations.py, web/src/pages/Chat.jsx, web/src/lib/api.js
**Acceptance:** zip check green in mock; ui_smoke 19/19

### T6: Tier 1 review
Strong-model review through a risk lens with at least 3 mutants (the guard when the setting read
fails; the zip route without the ownership clause; the kind lost between provider and pool), fixes,
scoped re-review.
**Files:** whatever the review names, inside the radius
**Acceptance:** 0 blocking findings; every mutant went red

### T7: Full gate, real gate, a real journey, evidence
The four commands in section 4, plus one pass through the web interface against the real provider
as a user (screenshots kept).
**Files:** none new
**Acceptance:** the numbers in section 4

## Evidence

Accepted 2026-09-24 at HEAD 0a229e9, clean tree. Fence audit: "base 8533270, 7 commit(s) from
base to HEAD, all changes since base are inside the blast radius". Commits: cf4dcfc (probes,
fixtures, research note), 2d74af2 (zip route and buttons), 983e542 (memory guard, banner by shape,
error kind through the pool, mock phrase, checks), c8b8221 and a63d4a5 (review fixes), 3674791
(every banner counted), 0a229e9 (the real journey script).

Full gate:

```
python acceptance.py                                22/22 PASSED, EXIT=0   health sha 0a229e9
cd web && npm run build                             built in 1.23s, EXIT=0  (at 3674791; no web change after)
~/cloakbrowser-env/bin/python tests/ui_smoke.py     19/19 PASSED, EXIT=0   host worker PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4
python acceptance.py --real                         19/19 PASSED, 3 skipped in this mode, EXIT=0   (at 3674791; 0a229e9 adds only tests/ui_journey.py)
~/cloakbrowser-env/bin/python tests/ui_journey.py   8/8 PASSED, EXIT=0    real provider, screenshots in /tmp/ui_journey
~/cloakbrowser-env/bin/python tests/provider_probe.py all   5 probe(s) ran, 0 crashed
```

Section 4 promised 22/22, 19/19 with 3 skips, 19/19 and a probe that prints without crashing; all
four matched. The mock-only skips in real mode are the provider error on command, the worker
killed mid-turn, and the pretend memory switch.

Red first (T1, on 8533270): acceptance 18/22, the four new checks failing for the right reasons
(`zip 404`; `status done kind None ... health memory None`; `health memory None`; `exit 1 0/2
PASSED`); ui_smoke 18/19 on the interface without the button (web changes stashed):
`TimeoutError: no Download all control, or no archive came out`.

Lines worth keeping from the real gate:

```
health reports the provider's memory setting       memory off
a conversation's media downloads as one zip        3 media, 3 entries ['chatgpt-...png', 'chatgpt-...png', 'hinh_vuong_mau_xanh(4).zip'], one message 2 entries, unknown message 404, other user 404
a follow-up turn packages what the first one made  708251 bytes, type file, entries ['a_simple_minimalist_graphic_a_clean_white_backgro.png']
thread reused within a conversation                the model recalled teal-63245
threads never cross conversations                  a new conversation does not know teal-63245
the provider's error banner is recognised by shape 4/4 PASSED
```

Mock only: `memory on refuses the turn and refunds: failed as provider_misconfigured, credit
returned, health shows memory on`. ui_smoke: `download all media as one zip: 2 entries [png, zip]`.
ui_journey, through the web interface as a user: `a real picture arrives in the thread: 1 image(s)
after 308s, 1254x1254`; `the model's own zip arrives as a file card: 'hinh_tron_mau_cam.zip 725 KB'
after 77s`; `download all packs the picture and the file: 3 entries`; `quota tracks two real turns:
100 -> 98`; `the worker read the memory switch before speaking: memory off settle server p50
305.7s`. The account was slow that day (p50 305s) after a full day of testing; the picture landed
8s past the provider's 300s reply ceiling measured from the click, inside it measured from the send.

Probes (full record in docs/research/2026-09-24-provider-measurements.md):
- `send`: the turn's request is `POST /backend-api/f/conversation`, after `conversation/init` and
  `f/conversation/prepare`; settled on the server in 14s and 18s.
- `dom-settle`: with the conversation GET answered 500 from inside the page, `settle=dom`, 12 reads
  withheld, text identical to the server's; on an ordinary turn the text stopped changing 1.6s
  before the stop button left, so `SETTLE_SECONDS = 6` is ample.
- `memory`: no JSON flag by name; the switch is `PATCH settings/account_user_setting?feature=m3m`
  and reads back as `settings.m3m` (with `sunshine`, `moonshine`) in `GET settings/user`, measured
  by flipping it on and off once with the worker stopped and no turn sent; `memory_scope` on a
  conversation read `global_enabled` with the switch off and is not used.
- `banner`: one `.text-token-text-error` div with the server's message and a Retry button, no
  `role=alert`; the address after the failure is `/c/WEB:<uuid>`, a placeholder the server does
  not know.
- `cleanup`: `PATCH /backend-api/conversation/<id> {"is_visible": false}` -> 200, then GET 404.

Review (tier 1): round 1 on 983e542, 0 blocking, 10 non-blocking; mutants M1 (kind lost in the
pool), M2 (zip without ownership), M3 (detector always fires), M4 (mock guard no-op), M5 (refund
skipped) each went red on the predicted check, control 22/22. Fixes in c8b8221 and a63d4a5;
scoped re-review: 0 blocking, 12/12 fake-page repros as expected, the retry mutant red, control
22/22, one gap left (only the first banner compared), closed in 3674791 and pinned by the
two-banner case (test_dom_signatures 4/4) and 5/5 fake-page baseline cases.

Deviations, all narrowing: the "no thread stored on the conversation" clause of the memory-on
check is not asserted (thread urls never reach a client, and a failure result carries no
thread_url by construction); ui_smoke does not drive the per-message "Download these" button (the
mock returns one media per turn; the api side is gated through `?message_id=`); the banner
signature check runs first in the acceptance so its browser never overlaps a real worker's. The
`memory-toggle` probe changed the account setting for a few seconds, with the worker stopped and
no turn sent, and restored it; verified off afterwards and read off by every later turn. The
one-way cleanup of test residue in the owner's account (2 memories, 127 threads) was inventoried
and handed to the owner, not executed by the agent.

Left open, in HANDOFF: Library cleanup through the next plan's trash feature; rendering the
model's markdown in reply bubbles; the archive built in memory.
