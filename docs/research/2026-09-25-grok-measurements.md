# Grok measurements, 2026-09-24

What grok.com did when asked, through cloakbrowser 0.5.10 on this machine, with the account saved
in `storage/sessions/grok.json`. Every line is a printed measurement from `tests/grok_probe.py` or
from a one-off script quoted in the session, not a reading of anyone's documentation. The account
is a **free** tier. Rerun the probes when the site changes; these numbers are the day's.

## Reaching the site

cloakbrowser headless, no session, `https://grok.com/`:

```
first response 403, body "Performing security verification"
t+ 6s blocked=True  composer=none
t+14s blocked=False composer=textarea[aria-label="Ask Grok anything"]
CLEARED after 14s
```

With the saved session the challenge cleared in 5s. No human step, no Turnstile click, no headful
mode, no persistent profile. This is the single fact the plan rested on and it holds.

A OneTrust cookie dialog is present on a fresh context even though the saved session carries
`OptanonConsent`; it can overlay the page, so the provider dismisses it by its own reject or close
control, never by accepting.

## Signed in or not

| | anonymous | this account |
|---|---|---|
| `POST /rest/rate-limits` (DEFAULT, grok-4) | `windowSizeSeconds 14400, remainingQueries 2, totalQueries 2` | `windowSizeSeconds 86400, remainingQueries 7, totalQueries 7` |
| threads in the sidebar | 0 | 9 |
| a sent turn | walled: "Sign up to continue seamlessly with Grok's full power", no reply, no `/c/<uuid>` | answered |

**Seven turns per 24 hours** is the whole budget on this account. The counter did not move after a
real turn (7 before, 7 after), so `/rest/rate-limits` reports a window but does not track what the
web surface spends; pacing cannot be built on it yet. Measure the gRPC-web credits endpoint before
relying on any number.

`/rest/rate-limits` answers 200 from an in-page `fetch` with `credentials: 'include'` and no
anti-bot header, anonymously and signed in.

## The composer, and the cohort trap

- anonymous session: `textarea[aria-label="Ask Grok anything"]`
- this signed-in account: `[data-testid="chat-input"] .ProseMirror[contenteditable="true"]`

Both cohorts are live at the same time on the same site, so a provider must handle both.
ProseMirror ignores Playwright's `fill()`; click to focus, then type through the keyboard, then
press Enter. That is what sends: the box empties and the turn appears.

## Sending, and why the write path is not a problem here

A DOM-driven send on a logged-in session **completes**. No `403 {"error":{"code":7}}`, which is
what every HTTP-replay project fights, because the page mints `x-statsig-id` itself. The thread url
appears about 3 seconds after Enter:

```
thread url appeared after 3s: https://grok.com/c/fd1ba142-d6b8-4df3-8863-98b9939e6a17?rid=...
reply: pong
```

The turn travels over `wss://grok.com/ws/mgw/?uid=<uuid>`. No `POST /rest/app-chat/conversations/...`
was observed for a turn; the REST calls during a turn are all furniture (`/rest/skills`,
`/rest/suggestions/stream`, `/rest/connectors/...`, `/rest/rate-limits`).

The url carries `?rid=<responseId>`; the thread id is the `/c/<uuid>` segment and the query is
dropped when storing it.

## Server truth

`GET /rest/app-chat/conversations/{id}/responses?includeThreads=true` returns every turn:

```
{"sender":"human",     "partial":false, "message":"Generate an image: a plain orange circle..."}
{"sender":"assistant", "partial":false, "message":"<grok:render card_id=... card_type=\"generated_image_card\" .../>"}
```

`GET .../response-node?includeThreads=true` returns `responseNodes` (`responseId`, `sender`,
`parentResponseId`) and `inflightResponses`, empty when nothing is generating.

**The settle rule**: the last assistant turn is finished when `partial` is false and
`inflightResponses` is empty. Verified on a finished image thread: `done=True partial=False`.

Two traps, both paid for here:

- the page is not a witness. Three seconds into a turn the assistant bubble already reads
  `Working for 2s`, and it becomes `Worked for 3s` when done, so a DOM reader that waits for
  "some text" calls an unfinished turn finished. The first probe did exactly that.
- the reader must not truncate. An image turn's `/responses` body is 5227 characters; a helper that
  cut every response at 600 characters made every parse fail, and the settle never fired for 242
  seconds while the turn had in fact finished at 15. The ruler was broken, not the site.

## Images

The free account **does** generate images. The turn produced no text at all once the render tag is
stripped; the picture arrives as attachment metadata on the assistant turn:

```
fileAttachments:         ['75fede48-3de7-4c3a-b89a-02d2c76ee291']
fileAttachmentsMetadata: [{fileMetadataId: '75fede48-...', fileMimeType: 'image/jpeg', ...}]
generatedImageUrls:      []
message:                 <grok:render card_id="AOaVh" card_type="generated_image_card" .../>
```

`generatedImageUrls` is empty; the url is built from the asset id and matches what the page shows:

```
https://assets.grok.com/users/<userId>/generated/<assetId>/image.jpg
```

Fetched from inside the page with `credentials: 'include'`: `200 image/jpeg, 71785 bytes`. So the
bytes come back the same way ChatGPT's do, inside the session, never as a stored link.

The assistant text must have `<grok:render ...>` tags stripped before a person sees it.

## Deleting a thread

```
DELETE /rest/app-chat/conversations/soft/<id>  -> 200 {}
DELETE the same id again                       -> 404
GET .../response-node after the delete         -> 404
```

Idempotent, which is what the tombstone worker needs. Both probe threads were deleted this way.

## Two browsers

Not a Grok fact, but it decides the worker's shape:

```
two cloakbrowser browsers in one thread  -> Error: Playwright Sync API inside the asyncio loop
one browser per thread, overlapping      -> both alive, both usable
one browser, two contexts                -> works, cookies isolated
```

The worker has one runner thread that creates its browser lazily, so a second provider would hit
the first case on its first job.

## What the platform does today with a Grok job

Measured against the running stack before any of this was built: a job with `provider: grok` fails
in seconds as `provider_error: provider grok unavailable: not enabled on this worker`, and the
credit is refunded (quota 100 -> 100). The api, the database and the interface are already
provider-agnostic; only the worker lacks a driver.

## Memory (2026-09-27)

`GET /rest/user-settings`, fetched from inside the page with the session's cookies, answers four
keys: `enableMemory`, `agentCustomizations` (a list), `allowGrokFinishedNotification` and
`mutedBotPushAgentIds` (a list). `enableMemory` was **true**. The page loads it on every visit,
beside a dozen other `/rest/` calls.

The switch it mirrors is under the account menu (the sidebar's bottom button with the avatar):
Settings, then the Data Controls section, "Personalize Grok with your conversation history"
(marked Beta, "Allow Grok to remember details from your previous conversations"), a
`button[role="switch"]` reading `aria-checked`. On a shared account that is the cross-user leak
ChatGPT had, so with the owner's permission it was turned off, that switch only: the page sent
`POST /rest/user-settings {"enableMemory": false}`, the switch then read `false`, and a fresh
`GET /rest/user-settings` said `false`. The same section holds two more switches, both on and left
alone: "Improve the Model" (training on the account's data) and "Allow chat link sharing". The
Behavior section's "Require Cmd+Enter To Submit" is off, so Enter sends, as the driver expects.

Whether memory actually carries a fact from one conversation into another was not tried while it
was on: a leak test would have written into the account's memory.

With it off, two real turns through the driver after the guard went in (a9e03c1): a new
conversation was told "Remember this word for later: teal-...", answered "ok" (17.3s); a second new
conversation asked for the word and answered "Unknown" (15.5s). Both turns read `memory=off` before
sending. The response to `GET /rest/user-settings` carries no `cache-control`, `expires`, `pragma`,
`etag` or `last-modified` header (only `vary: Origin, ...`), so nothing marks it as reusable from
the browser's cache; the driver fetches it again before every turn.

## Still unmeasured

- whether `partial` and `inflightResponses` behave the same on a long streaming answer, a search
  answer, or a refusal
- what the site shows when the seven turns are spent, and which error kind that should map to
- whether a second cohort (the plain textarea) ever appears for this account
- the gRPC-web credits endpoint, which is where a usable quota number probably lives
- image generation while the daily budget is nearly spent
