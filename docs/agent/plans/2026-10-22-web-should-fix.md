# Plan: the web's should-fix list of the review of 2026-10-21

Approved by the owner on 2026-10-22: **"Duyệt, làm ngay (Recommended)"**, offered as the second of
the three plans the owner ordered on 2026-10-21 ("Làm cả ba theo thứ tự đó"), seven points, tier 2,
no real turn, the host worker stopped several times (about 7 minutes each) for the UI test.

## 1. Goal

The owner, 2026-10-21: **"Hiện tại dự án này làm tới đâu rồi, đã lâu rồi chưa đụng lại cần bạn
review plan và source thật kỹ trước khi tiếp tục làm tiếp"**, then **"Làm cả ba theo thứ tự đó"**
(safety, then the web, then docs and configuration), and for this plan **"Duyệt, làm ngay"**.

The web review (`docs/agent/reviews/2026-10-21-review-web-and-docs.md`, items 1 to 7 and 11), read
in the code:

1. **A job is forgotten the moment the person leaves the chat view.** `web/src/App.jsx` unmounts
   `Chat` for the gallery and the API page; `runJob` keeps polling on the dead instance; back in the
   chat there is no typing bubble, no Stop, and the reply shows only after reopening the
   conversation; a person who sends again pays a second credit
2. **A finishing job paints whichever conversation is open now.** `runJob` calls `setConversation`
   for the job's conversation with no check of the open one; the `[activeId]` loader has no
   cancellation, so A then B on a slow link can land A last
3. **An expired login leaves a signed-in shell with no session.** `api.js` clears the token on 401
   but nothing tells `Shell`; every later call fails in red until "sign out" is pressed; and the
   other way round, `api.me()` failing for any reason (a network blip, an api restart) at load signs
   the person out
4. **Sign out never revokes the session** (`POST /auth/logout` exists, the web never calls it)
5. **The gallery's delete has no confirmation**, one tap deletes a file for good
6. **The gallery shows at most 100 items** under a heading that counts them all
7. **Errors and the running phase read in English whatever the language** (items 7 and 11): the
   worker's raw sentence for `provider_error`, `no_worker`, `stranded`, `empty_reply`; the api's
   `detail` for 402, 409, 422; the phase names in the typing bubble

Done means: leaving the chat and coming back mid-job shows the job running with Stop and its reply
when it lands; a finished job never paints a conversation that is not open, and the open one is the
last one asked for; a 401 anywhere brings the sign-in page, and a failed first look at the account
that is not a 401 keeps the token and offers a retry; sign out revokes the session; a gallery delete
asks first; the gallery shows every item, a "show more" past each hundred; the errors a person
reads and the phase are in their language, the raw text kept as a title.

## 2. Non-goals

- The API keys page's own errors, the login page's errors, the admin view
- Pagination of the conversation list (search covers it), the history step, the lightbox's Back,
  tap targets, the video loaded whole (the review's nice-to-haves and the older open list)
- Any api or worker change; the conversation list's search race
- The Grok refusal quote (a worker point, parked)

## 3. Invariants touched and risk tier

- **Quota.** Nothing here charges or refunds; the web must not lead a person into paying twice for
  one turn (point 1)
- **A person sees only what they asked for.** A finished job paints only its own conversation, and
  only while it is the open one
- **Sessions.** A revoked or expired login is never used again by the web; a sign out ends the
  session on the server

### Risk tier

**Tier 2** (UI, a session's end): one review round plus one design-review pass; after fixes the
coordinator runs acceptance with mutants, no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/ui_smoke.py   # N/N PASSED (59 before); each new check red first on the web as it stands
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end
```

The new ui_smoke checks, each in its own browser context with the api answered in the browser where
a state has to be held (the pattern of the follow-the-tail checks): leaving the chat for the gallery
mid-job and coming back shows the typing bubble and Stop, and the reply lands without reopening; a
job finishing while another conversation is open leaves that one on screen, and a slow first load
of A answered after B's leaves B; a 401 on any call shows the sign-in page; a first account read
that fails on the network keeps the token and its retry brings the shell back; sign out makes the
old token 401 on `/auth/me`; a gallery delete asks, a dismissed question deletes nothing; a gallery
of 137 items shows 100 and a "show more" that shows the rest; in Vietnamese a `provider_error`, a
402 and a phase read in Vietnamese, the raw text in the title.

Mutants on a copy of the web served on 5174, each red: `Chat` unmounted again; the open-conversation
guard removed; the 401 handler not called; `logout` not called; the gallery confirm removed; the
offset ignored; the error mapping removed.

## 5. Blast radius

```
web/src/App.jsx
web/src/pages/Chat.jsx
web/src/pages/Gallery.jsx
web/src/lib/api.js
web/src/lib/strings.jsx
web/src/components/TypingBubble.jsx
tests/ui_smoke.py
docs/agent/reviews/*
acceptance.py
```

`acceptance.py` was added on 2026-10-22 with the owner's "Cho sửa gate (Recommended)", for T7 only.

## 6. Reuse pointers

- `tests/ui_smoke.py`: `tail_gap` (a context with the token set by an init script, the api answered
  by `route`), `heard`, `shot`, `record`, `png`, the provoked-error filters
- `web/src/pages/Chat.jsx`: `runJob`, `stopJob`, the `[activeId]` effect, the providers poll's `live`
  flag (the shape for the loader), `served`
- `web/src/lib/api.js`: `request`, `waitForJob`, `mediaBlobUrl`
- `web/src/pages/ApiKeys.jsx`: the confirm and its strings
- `api/src/routes/auth.py` `logout`, `api/src/routes/media.py` `list_media` (`limit`, `offset`, `total`)

## Tasks

### T1: Red checks
The ui_smoke checks of section 4.
**Files:** tests/ui_smoke.py
**Acceptance:** each new check red on the web as it stands for its reason, every other check green

### T2: The chat's job and the open conversation (points 1, 2)
`Chat` stays mounted and is hidden while another view shows, refreshing the list and the open
conversation when shown again; a ref of the open conversation guards every `setConversation` of a
job and the loader; the typing bubble and Stop belong to the job's own conversation.
**Files:** web/src/App.jsx, web/src/pages/Chat.jsx
**Acceptance:** the checks of points 1 and 2 green

### T3: The session (points 3, 4)
`api.js` tells the shell of a 401; the shell's first account read clears the session only on 401
and otherwise offers a retry; sign out calls `/auth/logout` before forgetting the token.
**Files:** web/src/lib/api.js, web/src/App.jsx, web/src/lib/strings.jsx
**Acceptance:** the checks of points 3 and 4 green

### T4: The gallery (points 5, 6)
A confirm before a delete; `/media` asked page by page with a "show more".
**Files:** web/src/pages/Gallery.jsx, web/src/lib/api.js, web/src/lib/strings.jsx
**Acceptance:** the checks of points 5 and 6 green

### T5: The person's language (point 7)
A mapping from a failure's status or kind to a sentence in each language (the raw text as a title),
used by the chat and the gallery; a `no_worker` failure shows the unavailable notice like a 503; the
phases mapped in the typing bubble.
**Files:** web/src/lib/strings.jsx, web/src/pages/Chat.jsx, web/src/pages/Gallery.jsx, web/src/components/TypingBubble.jsx
**Acceptance:** the check of point 7 green; `npm run build` exit 0

### T6: Review, design review, mutants, the full gate, Evidence
**Files:** whatever the reviews name inside the radius
**Acceptance:** section 4

### T7: The gate waits for a restarted worker to be seen (added 2026-10-22, owner's approval)
The full gate read 55/56 on 526e75c: "a running job can be cancelled" started its job right after
the dead-worker check brought the gate's worker back, and the api refused it with 503 (its own
record: no job; the kept api log: `POST /chat 503`) because a worker counts as serving only from its
first claim, which a loaded machine delays past the worker's health page. `start_worker` waits
until the api has recorded a contact from each provider the new worker serves.
**Files:** acceptance.py
**Acceptance:** the full gate green; the dead-worker check states the measured wait

## Evidence

Closed on 2026-10-22 at **3d2d02e**, clean tree, the marker removed after a clean audit (5 commits
from base 1a5e7aa, all inside the radius). Records in `docs/agent/reviews/2026-10-22-web-*`.

```
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # at 3d2d02e
56/56 PASSED
✓ built in 1.69s
74/74 PASSED
exit 0
```

| Step | Result |
|---|---|
| T1 red checks (87f907e) | 57/68 on the web as it stood, the nine new checks red for their reasons |
| T2 alone, on a copy of the web on 5174 | 62/68, the six later checks red |
| T2 to T5 (0d0452d) | 68/68 |
| Review round, red first on 0d0452d | 67/74: the six new checks and the reworded Vietnamese one |
| Review round (1a1b937), then the bubble rule (526e75c) | 73/74 (the clock check's stay too short for its floor), then 74/74 |
| Mutants W1 to W10 (`2026-10-22-run-web-mutants.py`) | 10 of 10 RED on their own checks |
| Full gate at 526e75c | 55/56: "a running job can be cancelled" refused 503 with no job right after the gate restarted its worker, load about 20; fixed in T7 |
| T7 (3d2d02e), full gate | green as above; the restarted worker seen by the api 0.0s after its health page, at load 5 to 7 |

Mutants, each a copy of web/ on 5174 with one change, against the whole ui_smoke:
W1 the chat unmounted outside its view; W2 the open-conversation guard removed; W3 the read counter
ignored (2 checks); W4 the 401 handler not called; W5 sign out without logout; W6 the gallery
confirm removed; W7 the offset ignored; W8 the error mapping removed; W9 the providers not asked
again when shown; W10 the bubble under whatever is on screen. The runs of W3 to W7 also failed the
"opens it" check once each, which found the bubble shown under the previous conversation's messages
right after opening the job's one; fixed in 526e75c and pinned (W10).

Review: the tier 2 code review (1 blocking, 1 should fix, 5 nice) and the design review (1 blocking,
6 should fix, 2 nice) were fixed in 1a1b937, except two English texts outside the radius
(MediaImage, FileCard), parked for the owner. The design review read 25 captures, then 29
(`docs/agent/reviews/2026-10-22-captures/`).

Not measured here: the gate's restart wait under load (the race was seen twice at load 20 to 30;
the green runs were at load 5 to 7). No real provider turn was run; this plan changed no browser
flow.
