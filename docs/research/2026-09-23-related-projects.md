# Related projects: what they do, what they teach, what we should do next

Date: 2026-09-23. Five parallel research passes over GitHub and the web, each aimed at one part of
this platform and required to tie every lesson to a defect we actually hit this week. Nothing here
was run against the provider; probes that are still needed are marked as such.

## The one finding that gates everything else

Two passes reached the same conclusion from different directions. A ChatGPT Plus subscription is
personal use; driving it unattended and serving other people through it is a stated reason for
restriction or a ban, and rotating several accounts is named as a violation, not a mitigation.
Sub2API, the project closest to ours (pools Plus and Pro subscriptions behind one endpoint), says
so in its own README and forbids commercial operation. gpt4free received a lawyer's letter in 2023;
the acheong08 lineage was archived; PandoraNext went closed then shut down.

Our design does exactly the prohibited thing. A ban forfeits the account and takes the whole
platform down at once. This is a decision for the owner, not for code, and it belongs in
DECISIONS before a second teammate is invited:

1. Stay personal-use: one owner, the platform is a private tool, no invites.
2. Move multi-user text to the official API (per-token, sanctioned), keep the browser path only
   for what the API cannot do, and accept that the browser path is one person's tool.
3. Proceed as is, eyes open, with a written acceptance of the ban risk.

Sources: [Manifest on subscription bans](https://manifest.build/blog/banned-from-chatgpt-subscriptions/),
[Sub2API](https://github.com/baryon/sub2api), [gpt4free takedown](https://techcrunch.com/2023/04/25/a-developer-exploited-an-api-flaw-to-provide-free-access-to-gpt-4/),
[nstbrowser on ban causes](https://www.nstbrowser.io/en/blog/chatgpt-ban).

## What the field converges on

### Read server truth, stop guessing the DOM

Five wrong selector guesses this week, a button whose label changes with the reply language, and a
stop button that flickers between tool steps all share one cause: we infer state from rendering.
The projects that lasted read structured data the page already fetches with its own cookies.

- Reply settled: poll `/backend-api/conversation/<id>` until the last assistant node has
  `status == finished_successfully` and non-empty content
  ([chatgpt_web_automator](https://github.com/syntaxsurge/chatgpt_web_automator)). CatGPT-Gateway
  waits for the newest turn's Copy button instead; either beats the stop button.
- Files: the "Tải file" button calls one of `/files/{id}/download`,
  `/conversation/{id}/attachment/{file}/download` or
  `/conversation/{id}/interpreter/download?message_id&sandbox_path`
  ([chat2api](https://github.com/lanqian528/chat2api)). Listening on `page.on("response")` for
  those, or calling them from inside the page, is language-independent by construction. File urls
  expire in about an hour, consistent with our 403 measurement: pull bytes immediately.
- Thread identity fallback: inject a UUID into the prompt and read it back, in case `/c/` ever
  stops appearing in the url.

Needs a probe: the exact JSON shape of the conversation endpoint as fetched from inside our page,
and which download endpoint the button actually hits.

### Provider errors are failures with a cooldown, not answers

Today a "Something went wrong" banner was stored as a successful reply, and plain chat slowed from
12s to 256s after heavy use. Every gateway treats this as a health signal: One-API disables a
channel after 5 consecutive timeouts or 3 consecutive 4xx/5xx; LiteLLM cools down on 429 at once;
Sub2API pulls an account out on 429 (honouring retry-after) and 401/403. Browser clients add
pacing: a minimum gap between turns, per-account hourly and daily budgets, an image budget aware of
the roughly 50 images per rolling 3 hours on Plus, exponential backoff on the rate-limit popup.

For us: classify error banners as `provider_error`, fail the job, refund quota, back off, pause the
queue, and show all of it in `/health`. Do not match the English banner text; measure its DOM when
it next appears.

Sources: [One-API](https://github.com/songquanpeng/one-api), [LiteLLM](https://github.com/BerriAI/litellm),
[gpt2agent pacing](https://github.com/robotlearning123/gpt2agent), [Plus image limits](https://www.cometapi.com/how-many-images-can-i-generate-with-chatgpt-plus-%E2%80%94-a-2026-status-report/).

### Temporary Chat might remove the memory leak by design

chat2api sends `history_and_training_disabled: true`, which the UI exposes as Temporary Chat: no
history, no memory, no training. That would also end the Library clutter our jobs create. Two
things are unmeasured and one is a known conflict: whether a per-conversation thread url survives
under it, and chat2api's note that file download "needs history enabled". Worth one probe; if both
hold it replaces the account-setting dependency with a per-request property.

### Jobs need leases, cancel and phases

Postgres SKIP LOCKED, SQLite lease queues and BullMQ all do the same thing: a claim sets
`lease_expires_at` and bumps `attempts`; a janitor returns expired `running` rows to `pending` or
fails them at `max_attempts`; settling is guarded by the claimed attempt so a reclaimed job cannot
finish twice. We set `status='running'` and nothing else, so a worker restart during a 300s hang
strands the row forever. Cancel is a flag read between steps (ComfyUI `/interrupt`, Celery
`revoke`); our `_await_result` loops once a second and is the natural checkpoint. Progress as
phases ("reply started", "image appeared", "download appeared") is cheaper than websockets and
enough for the typing bubble. LibreChat swaps Send for Stop; Open WebUI notifies when the tab is
hidden.

Sources: [SKIP LOCKED](https://www.prisma.io/blog/you-dont-need-a-job-queue-postgres-already-has-skip-locked),
[SQLite leases](https://dev.to/d_security/why-i-built-a-job-queue-with-sqlite-instead-of-redis-and-what-i-learned-4f05),
[BullMQ stalled](https://docs.bullmq.io/guide/jobs/stalled), [ComfyUI routes](https://docs.comfy.org/development/comfyui-server/comms_routes).

### Data model additions that are free while pre-launch

- `messages.parent_id`: every mature chat UI stores a tree; edit and regenerate create siblings.
- `media.parent_media_id` and `kind`: a video script comes from an image, a zip from images;
  uploads differ from results (InvokeAI, Immich).
- A thumbnail row per image, webp, so the gallery stops streaming 2 MB originals into a 64px grid.
- `conversations.account_id` the day a second account exists: a thread lives inside one account,
  so affinity is mandatory, not a tuning knob (Sub2API sticky sessions).
- A usage log table separate from jobs: user, provider, feature, duration, outcome, media count.
  Every gateway has one; it is the prerequisite for any quota decision.
- Quota reset window with auto-refill (LiteLLM `budget_duration`, LibreChat `refillInterval`).
- Parameters embedded in the PNG (`tEXt` chunk, as A1111 and Fooocus do) so a downloaded file
  still says where it came from and the gallery survives a database reset.
- 30-day trash and a per-user byte cap (Immich) answer the storage question R2 was deferred for.

### Interface gaps the field has already solved

Cancel; rename and search conversations; browser notification when the tab is hidden; Vietnamese
strings (present in Open WebUI, LibreChat, LobeChat; our UI is English while our users type
Vietnamese); a mobile pass (PWA). Sharing links, folders and pins come later.

Sources: [Open WebUI](https://github.com/open-webui/open-webui), [LibreChat](https://github.com/danny-avila/LibreChat),
[LobeChat](https://github.com/lobehub/lobe-chat).

### Tooling

CloakBrowser: 31.6k stars, free tier is one concurrent session on an ageing binary, v148+ needs
Pro. Benchmarks put it level with curl_cffi (26 of 31 Cloudflare targets). patchright is the
cleanest drop-in fallback for our Playwright code, monthly releases, no session cap. nodriver has
the best stealth but is not a Playwright shim, so a rewrite. Steel is a plausible self-hosted home
for the worker later. On 2026-09-08 OpenAI shipped a new Turnstile that killed every pure-HTTP
client; browser-driven clients survived, which is the side we are on, but a DOM redesign hits us
the same way: keep selectors in one module with a nightly canary.

Sources: [benchmark, 651 verdicts](https://dev.to/ianlpaterson/anti-detect-browser-benchmark-2026-7-stealth-tools-31-cloudflare-targets-651-verdicts-4361),
[patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python), [nodriver](https://github.com/ultrafunkamsterdam/nodriver),
[Steel](https://github.com/steel-dev/steel-browser).

## What not to build at this size

Redis, BullMQ, Celery, Temporal, websockets, ClickHouse, content-addressed dedup, presigned
uploads, RAG, agents, MCP, SSO, token-multiplier pricing, per-user API keys, protocol translation,
100 providers, semantic caching. One worker on SQLite polled every second is fine.

## Proposed order

| # | Work | Size | Why first |
|---|---|---|---|
| 0 | Owner decides the ToS posture, recorded in DECISIONS | decision | Everything multi-user depends on it |
| 1 | Provider error classification, latency backoff, pacing and image budget, all in /health; code sha in /health | S | Fixes two things seen today; makes throttling visible instead of mysterious |
| 2 | Leases, attempts, janitor, guarded settle; cancel; phases in the typing bubble | S | Closes the stranded-job hole and the "no way out" wait |
| 3 | Probe: conversation JSON and download endpoints from inside the page; if they hold, replace stop-button settle and button clicking | M | Retires the whole class of DOM-guessing defects |
| 4 | Probe: Temporary Chat for thread persistence and file download | S | If it holds, memory leak and Library clutter disappear by design |
| 5 | Schema while breaking is free: parent_id, parent_media_id, kind, thumbnails, usage log, quota refill, PNG metadata, trash and byte cap | M | Cheap now, expensive after launch |
| 6 | UI: cancel button, rename and search, hidden-tab notification, Vietnamese strings, mobile pass | S-M | Highest user-visible value per effort |
| 7 | Second account for the gate only, then account pool with affinity and cooldown | M | Only after 0 is settled and a second subscription exists |
| 8 | patchright as fallback driver | M | Insurance against the free CloakBrowser binary ageing |

## Measurements taken after this note, 2026-09-23

Probes against the real provider, from inside our own page, no guessing:

- `/backend-api/conversation/<id>`: 404 with cookies alone, 200 with the `accessToken` from
  `/api/auth/session` as a Bearer header. Top level carries `current_node`, `is_temporary_chat`,
  `memory_scope`. Each `mapping` node has `message.status`, `message.end_turn`,
  `message.content.content_type`, `message.content.parts`.
- A plain text turn is one assistant node: `status finished_successfully`, `end_turn true`.
- A file turn is four nodes: user text; assistant `content_type: code` with `end_turn: false` and
  recipient `python`; tool `execution_output` whose text names the file (`Created /mnt/data/hello.zip`);
  assistant text with `end_turn: true`. Waiting for the last assistant node with `end_turn` is
  therefore correct across tool use.
- The file button fires `/backend-api/conversation/<id>/interpreter/download?message_id=<final
  assistant node>&sandbox_path=<path>` (422 without `sandbox_path`), which resolves to an estuary
  url with `fn=<name>&cd=attachment`. The sandbox path is in the tool node's output text.

Adopted: the provider now settles a turn on the server's word and falls back to watching the page
only when the server view is unavailable. Text is taken from `parts`, which also drops the
follow-up suggestion chips that used to leak into replies.

- 2026-09-24: the download endpoint's body is `{status: "success", download_url, file_name,
  mime_type, metadata.file_id}`. Files are now fetched from it directly, using the sandbox path
  named in the tool output and the final assistant message id; the labelled button is only a
  fallback.
- 2026-09-24: a brand new thread answers 404 on its first read for a moment; treating that as
  "unavailable" sent every new-thread turn down the DOM fallback. It is "not yet": keep polling
  within the deadline, give up only after 30 unreadable ticks.
- 2026-09-24: taking every sandbox path named anywhere in the turn over-collects. A zip of two
  text files came back as three downloads, the two members included, both empty. The model names
  what it hands over in its final message (`sandbox:/mnt/data/two_text_files.zip`); the tool output
  names every scratch file it wrote. Prefer the final message.
- 2026-09-24: polling `/backend-api/conversation/<id>` every 1.5s through a full gate produced
  `429` on that endpoint, and thread pages then loaded too slowly for the composer to appear. The
  page's stop button is the cheap busy signal; the server is now asked only when the page looks
  finished, with exponential backoff on 429 (3s doubling to 30s).
- 2026-09-24: with the thread page slow, `_open` fell back to a fresh chat and the model answered
  "Unknown" to a recall question it had just been told the answer to. Silent fallback removed: a
  fresh chat is started only when the server reports the thread as 404.
- 2026-09-24, Temporary Chat rejected: after a message is sent the url stays
  `https://chatgpt.com/?temporary-chat=true` and never gains `/c/<id>`. No thread id means no
  thread to return to and no server view. The account-level memory setting remains the control.

## Business logic worth noting

The independent gateway vendors consolidated in 2026 (Portkey, Helicone, OpenRouter acquired,
TensorZero archived) while the self-hosted open source ones kept growing (LiteLLM, New-API,
Bifrost). Gateways monetise credits and admin; chat UIs monetise hosted tiers. Every project that
turns a consumer subscription into a shared endpoint is either explicitly non-commercial, dead, or
carrying a takedown letter. As a private team tool this platform is on defensible ground; as a
SaaS, the browser-on-subscription path is the wrong foundation and the sanctioned one is the API.
