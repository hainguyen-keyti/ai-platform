# Plan: offer and accept only the providers a worker serves

## 1. Goal

The owner, 2026-09-29, on the next item of the overview ("the web selector offers every provider,
including ones no worker serves; picking one costs a 310s wait"): **"ok, làm tiếp đi"**, then
**"Cả api lẫn web"**, **"Hiện nhưng mờ, có ghi chú"** and **"Tier 2"**.

Today the web lists providers from a constant (`web/src/pages/Chat.jsx:10`), and the api accepts a
job for any known provider (`api/src/jobs.py:77`), charges it, and only fails and refunds it as
`no_worker` once no worker has asked for that provider within `no_worker_seconds` (310s by default,
`api/src/config.py:33-39`; `_sweep_unserved`, `api/src/jobs.py:185`). Whether a worker serves a
provider is already known: every claim, ping and heartbeat stamps `worker_pings.last_seen`
(`jobs.py:176-182`, `:304`), so a runner in the middle of a long turn stays served.

Done means: `GET /providers` tells a signed-in user, for every provider, whether a worker has
served it within that same window; a turn (chat, image, video script) for a provider nobody serves
is refused at once with 503, uncharged and leaving nothing behind, after the checks that already
refuse it (404, 409) and before a conversation is created or a credit taken; the web shows such a
provider greyed out with a note, never picks it on its own, and in an open conversation whose
provider nobody serves it says so and does not send.

## 2. Non-goals

- The worker, the pool, the runners and how a worker proves it is alive
- Features per provider (Grok's video script): a separate question
- The `no_worker` sweep itself, which still fails and refunds a job whose worker went away after it
  was accepted
- The gallery, the login page, anything else in the web
- A push channel: the web asks again on load and every 60 seconds

## 3. Invariants touched and risk tier

- **Quota.** A turn refused with 503 takes no credit and creates no conversation, message or job;
  the existing paths still charge once and refund once
- **One conversation, one provider.** The 409 for a turn into another provider's conversation keeps
  coming first (a single-provider real gate relies on it)
- **One served window.** "Served" means exactly what the `no_worker` sweep means: `last_seen`
  within `no_worker_seconds`; there is no second clock

### Risk tier

**Tier 2**, the owner's choice on 2026-09-29: one review round by a separate reviewer and one
design-review pass (desktop and mobile), then acceptance with mutants, no re-review.

## 4. Acceptance evidence

```
python acceptance.py                                            # 36/36 PASSED (34 + 2 new), the two new checks RED first
(cd web && npm run build)                                       # ok
~/cloakbrowser-env/bin/python tests/ui_smoke.py                 # 27/27 PASSED (25 + 2 new), the two new checks RED first
```

The two gate checks, at the moment the no-worker check has proven a provider unserved: `GET
/providers` says that provider is not served (and, in mock mode, that the worker's other provider
is); a turn for it answers 503 at once with the credit unchanged. The two ui checks answer
`GET /providers` in the browser with a chosen reply: the selector shows the unserved provider
greyed out with the note, and an open conversation of an unserved provider shows the notice with
sending disabled.

Mutants, each red: the window ignored (every provider served), the refusal placed after the charge,
the refusal placed before the 409, the option not disabled, sending not disabled.
Real: on the running stack, `GET /providers` lists the three providers the host worker serves as
served.

## 5. Blast radius

```
api/src/jobs.py
api/src/routes/chat.py
web/src/pages/Chat.jsx
web/src/lib/api.js
web/src/lib/strings.jsx
acceptance.py
tests/ui_smoke.py
```

## 6. Reuse pointers

- `api/src/jobs.py:185-209` `_sweep_unserved`: the served window and its SQL condition
- `api/src/routes/chat.py`: the features router and `current_user`
- `web/src/pages/Chat.jsx:328-332` the selector; `t.providerLocked` in `web/src/lib/strings.jsx`
  for the two languages
- `acceptance.py:936-959`: the no-worker check, where a provider is provably unserved
- `tests/ui_smoke.py`: its checks against the running stack

## Tasks

### T1: Red checks
Two gate checks in `acceptance.py` and two ui checks in `tests/ui_smoke.py`, as in section 4, each
red on today's api and web for the missing behaviour.
**Files:** acceptance.py, tests/ui_smoke.py
**Acceptance:** the four new checks red for that reason; the others as before

### T2: The api
`GET /providers` and the 503 refusal in `create_job`, both on the one served window.
**Files:** api/src/jobs.py, api/src/routes/chat.py
**Acceptance:** `python acceptance.py` 36/36

### T3: The web
The selector's greyed-out option with its note, no automatic pick of an unserved provider, the
notice and disabled sending in a conversation of an unserved provider, the strings in both
languages, the list asked for on load and every 60 seconds.
**Files:** web/src/pages/Chat.jsx, web/src/lib/api.js, web/src/lib/strings.jsx
**Acceptance:** `npm run build` ok; `tests/ui_smoke.py` 27/27

### T4: Review, design review, mutants, gates, Evidence
One review round and one design-review pass; any fix seen red first; the mutants; the full gate
once; the real `GET /providers`.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-29 at **a4a36f3**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build ok, **28/28 PASSED**, exit 0, at a4a36f3 with the host worker in mock (load average about 56 from other apps) |
| `python acceptance.py`, the two new checks | red first at 34/36 on 26dc5fc (`/providers` 404; a turn nobody serves 202 and charged 98 -> 97); now "chatgpt not served while the worker served only grok, grok served; anonymous 401" and "chat 503 in 0.0s, image 503, video 503; 404/409 still first {missing conversation 404, missing picture 404, another provider's conversation 409}; quota 97 -> 97" |
| `tests/ui_smoke.py`, the three new checks | red first on the old web (grok's option not disabled; no notice, Send enabled with text in the box); now "grok (unavailable)" disabled; an open conversation of an unserved provider shows the notice with Send and Video script held; a send the api refuses keeps the words, shows the notice, no header error |
| Api mutants (`/tmp/run_served_mutants.py`, the mock gate on copies) | **red**: every provider served (W1), the refusal before the 409 (W3, once the review's order probe was in), only chat refused (W4), the list open to anonymous callers (W5). The refusal after the charge (W2) survives and is equivalent: the refusal raises inside the transaction, so the charge rolls back with it (quota 98 -> 98) |
| Web mutants (edited in place, ui_smoke run, reverted, file hash checked) | **red**: the option not disabled plus the old refusal path (checks a and c), Send and Video script not held (check b, both parts) |
| Real, the running stack at a4a36f3 | `GET /providers` as a signed-in user: chatgpt, grok and gemini all `served: true` (the host worker serves the three); anonymous 401 |

Review, tier 2: one code review and one design-review pass. The code review found no defect in
the code and one gap blocking acceptance: nothing in the mock gate pinned the 409 before the 503
(its mutant survived); now pinned, with the 404s, every kind of turn and the anonymous 401. The
design review found nothing blocking; its points on the wording (no "worker" jargon, what to do
next), the refused send losing the words, the screen reader and the select's contrast were fixed,
and the code review's point that the auto-switch could swap a provider the person chose was fixed
by moving only a provider nobody chose. Also fixed from the review: a missing picture's 404 now
comes before the 503.

Deviations: the plan's "refusal after the charge" mutant is equivalent (above), a narrowing. The
ui checks grew from two to three, and the second now opens a conversation first: coming back from
the gallery remounts the chat with none open, where the web rightly moves off an unserved provider.
One ui_smoke run failed "view follows new messages" (432px from the bottom) under load and passed
unchanged on the rerun; parked as a possible race between the smooth scroll and `onScroll`. The
design review ran on screenshots (`/tmp/served_design/`), because the reviewer cannot sign in
without the invite code.

Left open, non-blocking: the served window is pinned only against a wider one (a window of a third
would refuse a runner in the middle of a long turn; `>=` against `>` is one second); a turn sent
within the first second of a provider's first ever start is refused until its first claim; the
60 second refresh and its cleanup are not pinned by a test.
