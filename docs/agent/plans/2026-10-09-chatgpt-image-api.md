# Plan: a proper image API on ChatGPT, called with a personal API key

Approved by the owner on 2026-10-09: **"Duyệt, làm ngay (Recommended)"**, offered with seven steps,
two real ChatGPT turns at the end, and the host worker stopped a few minutes for each full gate.

## 1. Goal

The owner, 2026-10-09: **"giờ như thế này, tôi cần bạn giúp tôi hoàn thiện chuẩn chỉnh api tạo hình
bằng chat gpt, tôi muốn cần biết bạn làm như thế nào, nhưng khi gọi api vào thì input là prompt hoặc
hình ảnh hoặc của 2 cái đó, output là hình ảnh"**.

Settled with the owner the same day:
- "Gửi rồi hỏi lại (Recommended)": a call returns a request id at once; the caller asks again for the
  status and, once done, downloads the pictures
- "Không cho, phải có prompt": the input is a prompt, or a prompt with a picture; a picture alone is
  refused
- "Khoá API riêng mỗi người (Recommended)": a long-lived key per person, revocable
- "Tự tạo trong web (Recommended)": each person creates, lists and revokes their keys on a page of
  the web

Read in the code on 2026-10-09:
- `api/src/routes/image.py`: `POST /image/generate` takes JSON with a required `prompt` and an
  optional `reference_media_id` (a picture already in the caller's media); there is no way to send a
  picture of one's own (no upload route in `api/src`)
- Nothing sends `reference_media_id`: not the web, not `acceptance.py`; the mock ignores
  `reference_filename` (`worker/src/providers/mock.py` 210-221); no driver test covers a picture
  turn with a reference. The path is unproven
- `worker/src/providers/chatgpt.py` 950-957: with a reference the instruction is hard-coded as "Using
  the attached image as the character reference, generate a new image: ..."
- Auth is a login JWT that lives 24 hours (`api/src/security.py` `current_user`, `TOKEN_TTL_HOURS`)
- `python-multipart==0.0.20` is in `api/requirements.txt`, importable in the api container and in
  the cloakbrowser venv the gate runs the api under
- The api writes `/data/media`, which is `./storage/media`, the directory the host worker reads

Done means: a person creates a key on the web; a program calls `POST /v1/images` with that key and a
prompt, or a prompt and a PNG, JPEG or WEBP picture of up to 10 MB; it gets a request id at once;
`GET /v1/images/{id}` says queued, running, done (with the pictures and where to download each),
failed or cancelled; the download returns the picture's bytes. Each request costs one credit and a
failure gives it back. Proven on the real ChatGPT account with a key: one prompt alone, one prompt
with a picture.

## 2. Non-goals

- Grok and Gemini through `/v1`; a picture alone with no prompt; one call that waits for the
  picture; cancelling through `/v1`; rate limits beyond the existing credits
- Any change to the web's own routes or to `POST /image/generate`, which the web keeps using
- API keys on any route outside `/v1/images`: not the web's routes, not key management, not admin
- ChatGPT's pacing and Cloudflare's check (a known risk of bursts, unchanged)

## 3. Invariants touched and risk tier

- **Auth.** A key authenticates only its owner and only on `/v1/images` routes; a revoked key is
  refused at once; a key is shown once at creation and only its SHA-256 is stored; a login JWT does
  not work on `/v1`, a key does not work anywhere else
- **Ownership.** Through `/v1` a caller reaches only their own requests and pictures (404 otherwise)
- **Quota.** A request takes one credit when it is accepted and gives it back exactly once if it
  fails or is cancelled (the existing `create_job` and settle); a refused request (400, 401, 402, 413,
  415, 503) charges nothing
- **Untrusted uploads.** A picture is accepted only by its content (PNG, JPEG or WEBP signature), at
  most 10 MB read, saved under a name the server chooses; a refused request leaves no file behind

### Risk tier

**Tier 1** (auth, tokens, untrusted input, credits): reviewed by a strong model through a risk lens
with at least three separate mutants; after fixes, a scoped re-review of the fixed parts and the old
repros. The web page also gets one design-review pass.

## 4. Acceptance evidence

```
python acceptance.py   # N/N PASSED (44 before); the new key and /v1 checks red first on the code as it stands
~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py   # N/N PASSED (49 before); the reference-turn check red first
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: all green, the new page's checks red first
```

The checks in `acceptance.py` (mock worker): a key is created and shown once, listed without its
secret, and revoked; a key reaches `/v1/images` and is refused on `/auth/me`, `/conversations`,
`/auth/api-keys` and an admin route; a login JWT is refused on `/v1`; a revoked or unknown key is
refused; a prompt alone ends with a downloadable picture; a prompt with a picture ends with a
picture, and the worker received exactly the uploaded bytes; no prompt, a picture alone, an
unsupported or fake picture, and an over-limit picture are refused with nothing charged and no file
left; another person's request and picture are 404; a failed request gives its credit back once; the
example script runs end to end against the mock stack.

Mutants on copies, each red: any `aip_` string accepted; a revoked key accepted; a key accepted on
`/auth/me`; a JWT accepted on `/v1`; the content check removed (the declared type trusted); the size
limit removed; the key stored in plain; the owner check removed from `GET /v1/images/{id}`; the
upload file left behind on a 402.

Real, through `/v1` with a key, the host worker on the new code: one ChatGPT request with a prompt
alone and, minutes later, one with a prompt and a picture, each done with a picture that downloads.
Not yet measured on the real site: a picture turn with an uploaded reference (the upload itself is
measured for video scripts); the real runs are where it is proven.

The host worker runs in the desktop app's Terminal panel; it is stopped a few minutes for each full
gate and started again.

## 5. Blast radius

```
api/src/db/schema.sql
api/src/security.py
api/src/models.py
api/src/main.py
api/src/jobs.py
api/src/routes/auth.py
api/src/routes/v1.py
worker/src/providers/mock.py
worker/src/providers/chatgpt.py
tests/test_chatgpt_composer.py
acceptance.py
web/src/App.jsx
web/src/pages/ApiKeys.jsx
web/src/lib/api.js
web/src/lib/strings.jsx
tests/ui_smoke.py
docs/api-v1-images.md
scripts/image_api_example.py
```

## 6. Reuse pointers

- `api/src/security.py`: `current_user`, `_bearer`, `require_worker` (`hmac.compare_digest`)
- `api/src/jobs.py`: `create_job` (one transaction: quota, held and served checks, conversation,
  user message, credit), `get_job`, `_refund`
- `api/src/routes/media.py`: `_owned`, `_safe_path`, `get_media_file`; `api/src/db/client.py`
  (`CREATE TABLE IF NOT EXISTS`, the added-column list)
- `acceptance.py`: `http`, `http_bytes`, `poll_job`, `run_checks`, the image check (480-510)
- `worker/src/providers/mock.py` `generate_image`; `worker/src/providers/chatgpt.py`
  `generate_image`, `_run(upload=...)`; `tests/test_chatgpt_composer.py` `DrawingPage`, `page.attached`
- `web/src/pages/Gallery.jsx` (a page of its own), `web/src/App.jsx` nav, `web/src/lib/strings.jsx`;
  `tests/ui_smoke.py` the nav checks at 360px in both languages

## Tasks

### T1: Red checks for keys and /v1
The checks of section 4 in `acceptance.py`, a multipart helper beside `http`.
**Files:** acceptance.py
**Acceptance:** the new checks red on the code as it stands (404 on the new routes), the 44 others green

### T2: API keys
A table of keys (id, user, name, prefix, SHA-256, created, last used, revoked); `POST`, `GET`,
`DELETE /auth/api-keys` with a login JWT only (the secret returned once, at most 10 live keys); a
dependency that accepts only a live key, for `/v1` only.
**Files:** api/src/db/schema.sql, api/src/security.py, api/src/models.py, api/src/routes/auth.py
**Acceptance:** the key checks of T1 green

### T3: /v1/images
`POST /v1/images` (multipart: `prompt` required, `image` optional; ChatGPT): the picture read to at
most 10 MB, checked by its signature, saved under a server name, kept as the caller's media on the
request's user message, its file removed if the request is refused; `GET /v1/images/{id}` (status,
error, pictures with their download path); `GET /v1/images/{id}/files/{media_id}` (the bytes). The
mock's picture turn reads its reference and says its size and hash.
**Files:** api/src/routes/v1.py, api/src/main.py, api/src/jobs.py, api/src/models.py, worker/src/providers/mock.py
**Acceptance:** `python acceptance.py` all green

### T4: ChatGPT's picture turn with a reference
A fake-page check: a picture turn with a reference attaches that file before typing and sends the
caller's prompt in the instruction; the instruction no longer says "character reference".
**Files:** tests/test_chatgpt_composer.py, worker/src/providers/chatgpt.py
**Acceptance:** the check red first; `tests/test_chatgpt_composer.py` N/N

### T5: The web page for keys
A nav entry "API"; the page creates a key (shown once, with a copy button and a warning), lists keys
(name, prefix, created, last used) and revokes one after a confirmation; both languages; a short
example call. Checks in `tests/ui_smoke.py`, red first: create, shown once, listed, revoked; the nav
still one row at 360px in both languages; no console errors. One design-review pass.
**Files:** web/src/App.jsx, web/src/pages/ApiKeys.jsx, web/src/lib/api.js, web/src/lib/strings.jsx, tests/ui_smoke.py
**Acceptance:** the new ui_smoke checks red first, then green; `npm run build` exit 0

### T6: Docs and an example
`docs/api-v1-images.md` (the three calls, fields, statuses, errors, limits) and
`scripts/image_api_example.py` (standard library: send, poll, download), run by `acceptance.py`
against the mock stack.
**Files:** docs/api-v1-images.md, scripts/image_api_example.py, acceptance.py
**Acceptance:** the example's check red first (no script), then green

### T7: Review, mutants, re-review, the full gate, two real turns, Evidence
**Files:** whatever the review names inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-10-09 at **4cd26c8**, clean tree, nine commits from 63ec5dd, the audit clean (no
widening). Every number is the command's own count line.

| Command | Result |
|---|---|
| **Full gate, once on the final tree, at 4cd26c8, the host worker in mock** | `python acceptance.py` **54/54** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **59/59** exit 0, "no console errors" []; tree unchanged after |
| `tests/test_chatgpt_composer.py` | **51/51 PASSED** at 4cd26c8. Red first: 50/51 at T4 (the "character reference" wording) |
| `python acceptance.py`, the new checks red first | 44/53 at 260d1fd (the nine key and /v1 checks, 404 on the new routes); 53/54 without the example script; the tier 1 review's checks 52/54 before ed2b9a1 (a huge claimed size, a cut header, 12 MB without a key, a web picture through /v1); the re-review's hidden JPEG red before 4cd26c8 |
| `tests/ui_smoke.py`, the new checks red first | 57/59 before the page (the two API page checks); then on the design review's points: the field 20px on a phone, no example to measure, a copy saying nothing, "09/10/2026" |
| **Mutants, api, each on a copy (`/tmp/run_api_mutants.py`), at 4cd26c8** | **20 of 20 red, each on its own check**: any `aip_` string, a revoked key, a key on the web's routes, a login token on /v1, any file taken for a small PNG, no picture size limit, the key in plain, no owner check, the picture left on a refusal, any picture of the person through a request, no key cap, last use never noted, no pixel cap, no request limit before the key, the web's requests through /v1, every JPEG marker walked as a segment; and the review's four: cleanup on 402 only, a path serving any picture but a sent one, exactly 10 MB refused, a picture request charged twice |
| **Mutants, web, each on a copy served on 5174 (`/tmp/run_web_mutants.py`)** | **4 of 4 red, each on its own check**: a refused copy saying nothing, the field shrinking on a phone, dates as numbers, the example running off its box |
| Measured on the live api | an unauthenticated POST of 200 MB: before ed2b9a1 the review measured 1439 MB spooled for 1.5 GB; at 4cd26c8 a declared 200 MB is 413 in 6 ms with nothing sent, a chunked one 413 after 19 MB, nothing kept (`/tmp` 4 KB before and after) |
| The size reader | 33 of 33 real pictures in `storage/media` (29 PNG, 4 JPEG) read; the Gemini JPEG 1024x559 as Gemini's own record says; Chrome's own WEBP (VP8X) and JPEG read right; 10 MB of fill bytes refused in 0.003 s (was 1.4 s); the re-reviewer's 9000x9000 JPEG behind FF 00 refused |
| **Real, two ChatGPT requests through /v1 with a key (2026-10-09 08:58 and 09:03, the host worker on 4cd26c8), `scripts/image_api_example.py`** | **PASSED**: a prompt alone, done in 56 s, a 1,341,483 byte PNG (a red fox in the snow); four minutes later the same picture uploaded as the reference with "the same fox at night under a sky full of stars", done in 66 s, a 1,749,865 byte PNG of that fox, same pose, at night. Jobs 5c7fc77c and 6e71c21e, `done`, `via` v1, the second's reference the uploaded file of exactly the first picture's size, on the person's message; credits 100 -> 98; the key revoked after |

Reviews:
- Design review (one pass): one blocking (the name field collapsed to 20px on a phone), four should
  fix, eight nice; fixed in cf0bc16 except the nav's tap targets (app-wide and older, already left
  open) and the browser's own confirm (as the chat's delete)
- Tier 1 review: nothing blocking, nine points, four surviving mutants; fixed in ed2b9a1: the request
  cap before the key, the pixel cap, /v1 only for its own requests on ChatGPT, the write inside the
  guarded block, last use once a minute, the docs; the four mutants now red
- Scoped re-review: one blocking, a JPEG steering the size reader with FF 00 to a small frame hidden
  in an APP1 while a browser decodes 9000x9000; fixed in 4cd26c8 with the walk capped, the drain
  bounded (a body declared over 16 MB refused unread) and the root path read

Deviations:
- T2's acceptance said the key checks would be green after T2; two of the three needed the /v1
  route and went green in T3 (a narrowing of the order, said in T2's commit)
- The plan's 10 MB became 10 MB for the picture and 10 MB and 256 KB for the whole request, checked
  before the key; and a pixel cap (16384 a side, 50 megapixels) was added from the review
- `tests/ui_smoke.py`'s nav was narrowed below 640px (App.jsx) so "API" fits one row at 360px in
  Vietnamese with a three digit quota (10px to spare); the email in the nav is truncated from 640px

Left open:
- A picture sent with a request that fails or is cancelled stays kept on the person's message
  (team-only: cancelling needs the login)
- Not measured on the real site: whether ChatGPT keeps a picture attached in the shared composer
  when a turn is cancelled or raises after the attach (`chatgpt.py` `_run`), which would send it
  with the next person's turn; needs a probe
- A stolen 24 hour login can make a key that outlives it (no password asked to make a key); the
  owner's call
- Every JSON route of the api still reads its whole body before the login is checked (the
  re-review: 200 MB to `/chat` took the api to 580 MB); a general cap is a plan of its own
- A client that disconnects mid-upload leaves its temp file held until garbage collection (FastAPI's
  own behaviour, bounded)
- The lossy-only WEBP header (`VP8 `) is read by the format, never by a real file (Chrome writes VP8X)
