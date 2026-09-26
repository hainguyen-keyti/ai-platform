# chatgpt.com after the overnight change, measured 2026-09-27

Probe: `~/cloakbrowser-env/bin/python tests/provider_probe.py composer`, then
`PROBE_THREAD=<id> ~/cloakbrowser-env/bin/python tests/provider_probe.py turn-dom`, against the
saved session, with the host worker running.
One real turn was spent (thread 6ab805cb, left in the account until the owner says otherwise).

## The page

| Thing | Measured |
|---|---|
| Session | signed in: `/api/auth/session` 200 with `user`, `account`, `accessToken` |
| First paint | `textarea#pending-home-input`, aria-label "Ask ChatGPT", at 1.4s |
| Real composer | `div.ProseMirror[contenteditable="true"][aria-label="Ask ChatGPT"]`, role textbox, no id, at **11.5s**. Typing before it mounts types into a box that is about to be replaced: the first probe run did exactly that and nothing was sent |
| `#prompt-textarea` | gone |
| Mode | "Chat" and "Work" buttons; Chat is the default (`aria-pressed="true"`) |
| Memory read | `settings.m3m` path still answers: `off` |

## Typing and sending

| Thing | Measured |
|---|---|
| `fill()` | **works** on this ProseMirror: read back `'fill probe text'`. The HANDOFF trap "ProseMirror ignores fill()" was grok's, not this one |
| `insert_text` with a newline | read back flattened equals the prompt flattened |
| Enter | sends once the ProseMirror is mounted: composer empty after 0.5s |
| One turn or several | **one**: the page reads "You said: Reply with the single word: ok This second line belongs to the same turn." and the server holds exactly one user node |
| Send button | `button[aria-label="Send"][type="submit"]`, no data-testid; `button[data-testid="send-button"]` is gone |
| Stop button | `[data-testid="stop-button"]` was never seen during a turn. A second real turn (a six-sentence reply, thread 6ab80afc) recorded the composer's own buttons every second: at 2.0s the last one was `button[aria-label="Stop"]` (type button, no testid); at 7.2s, the reply done, it had become `aria-label="Start Voice"`. No "Stop" stayed on the page |

## Files

`#upload-files` is gone. Three file inputs exist once the composer mounts, with React generated ids
that must not be relied on: `_r_c_` accept `image/*,video/*`, `_r_b_` accept `image/*`, `_r_a_`
accept anything. The composer carries a button `aria-label="Add files and more"`.

## Turns in the DOM

`[data-message-author-role]`, `article`, `[data-testid^="conversation-turn"]` all count **0** on a
thread that holds a finished turn. What the page carries instead, counted inside `main`:
`data-conversation-role` 1, `data-user-message-bubble` 1, `data-chatgpt-agent-turn-start` 1,
`data-turn-key` 1, `data-chatgpt-selection-message-id` 1, `data-chatgpt-search-message-ids` 2.

## Server view

`/backend-api/conversation/<id>` with the session's bearer token: 200, a user node and an assistant
node, both `finished_successfully`, the assistant with `end_turn: true`. The rule the driver settles
on still holds.

## What in the driver this breaks, by line (worker/src/providers/chatgpt.py at 72ca6ed)

- `:13` `TEXTAREA`, `:280` `_composer_ready`, `:329` the wrong "logged out" message
- `:14` `SEND_BUTTON`, used as the fallback send at `:348`
- `:15` `STOP_BUTTON`: `:471` is how `_settle_via_server` decides the page looks finished; with no
  stop button the page always looks finished after the start floor, so the server is asked every
  poll. `:594` is the DOM fallback's own signal
- `:16` `ASSISTANT_TURN`: the baseline at `:675`, the reply text at `:564`
- `:72-73`: images inside a user turn are skipped by their `[data-message-author-role]` ancestor;
  with none left, a reference picture the user uploaded is no longer told apart from a generated one
- `:216`: the error banner is recognised only inside an assistant turn; with no such ancestor it is
  never recognised, and a banner can be stored as an answer again
- `:17` `UPLOAD_INPUT`, set at `:681`: video script cannot attach its picture
- `tests/fixtures/chatgpt_*.html`, read by `tests/test_dom_signatures.py` and `acceptance.py`, are
  the old markup

**Correction, same day:** `:216` above is not the banner detector but `SNAPSHOT_DOWNLOADS`, the
file download buttons of the DOM fallback. The banner detector is `ERROR_BANNER_PRESENT`, which
never used the role attribute; it breaks for a different reason, measured below.

## Measured during T2, without spending a turn

Three existing gate threads were opened by id (`probe_fixtures`, `turn-dom`), and the error banner
was provoked by answering the turn request with a 500 from inside the page.

| Thing | Measured |
|---|---|
| A turn in the DOM | ONE `div[data-turn-key]` holds the user's bubble and the reply together |
| The user's words | `div[data-user-message-bubble="true"]` |
| The reply's words | `div[data-chatgpt-selection-message-id="<message id>"]`; absent for a picture-only reply |
| The reply's start | `span[data-chatgpt-agent-turn-start]` and a hidden `h4[data-conversation-role="assistant"]` |
| A generated picture | `img` with a **`blob:`** src inside `button[data-testid="generated-image-preview"]` inside `div[data-testid="generated-image-gallery"]`, after the reply's start marker; the blob reads back from the page (image/png 813947 bytes) |
| A user's upload | `img` with a `blob:` src inside the turn but outside both the bubble and the reply, before the reply's start marker |
| Consequence | `COLLECT_CANDIDATE_IMAGES` only accepts estuary and oaiusercontent urls, so **no generated picture is collected at all** |
| Files | no `button.behavior-btn` in a zip thread; the files still come from the server path (`_fetch_sandbox_files`), the button click is only its fallback |
| The error banner | `aside[role="alert"]` with `text-danger` classes, the server's message and a Retry button; `.text-token-text-error` is gone, so **`ERROR_BANNER_PRESENT` no longer recognises a failure** |
| A failed first turn | the address becomes `/c/local-chatgpt%3A<uuid>`, not `/c/WEB:<uuid>`, so `_thread_id` would hand back a thread the server does not know |
