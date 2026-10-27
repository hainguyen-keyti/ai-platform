# Plan: conversation threads and generic deliverables

## 1. Goal

Map mỗi conversation sang một thread ChatGPT riêng thay vì mở chat mới mỗi job, để làm được việc
nối tiếp nhiều lượt; nhận generic mọi thứ ChatGPT trả về kể cả file không phải ảnh.

Storage: "Chắc lưu ở máy local của tôi trước đi, R2 tính sau."

## 2. Non-goals

- Auth, quota and the job queue are not touched
- The typing bubble and the scroll behaviour are not touched
- Grok and Gemini stay unimplemented
- Existing media is not migrated anywhere
- No retention or cleanup policy
- No Cloudflare R2, and therefore no storage abstraction: one backend does not earn an interface.
  Bytes are written to the media directory exactly as they are today

## 3. Invariants touched and risk tier

**Invariant:** a reply belonging to one user must never reach another user.

Today that is held by brute force: every job opens a brand new ChatGPT chat, so nothing can carry
over. This plan relaxes that, and the invariant becomes "one platform conversation maps to one
ChatGPT thread, and a conversation belongs to exactly one user". Relaxing a safety mechanism is
the reason this is not a tier 2 change: it needs its own test, not a side effect of another one.

**Risk tier: 1.** A shared-contract change to how user data is kept apart.

## 4. Acceptance evidence

```bash
python acceptance.py
# 11/11 PASSED, exit 0
```

Three checks are new. Each must be watched failing on the current code before its green counts:

| check | what it measures |
|---|---|
| `thread reused within a conversation` | the second job in a conversation is given the thread the first one created |
| `threads never cross conversations` | a second conversation is given a different thread |
| `non image deliverable is kept` | the mock returns a real zip built with `zipfile`; the bytes fetched back through the API are byte identical |

Plus `python tests/ui_smoke.py`, expected 17/17: one new check that a non-image shows a file card
with a working download rather than a broken image.

Measured before writing this plan, not inferred:
- `playwright.sync_api.Page.expect_download` exists and captured a real 232 byte zip with `PK` magic
- the estuary endpoint returns `http 403` without the session, which is why bytes are fetched
  inside the page and a stored link is not an option
- `boto3` is absent from the venv, which no longer matters because R2 is cut
- `conversations` has no column for a thread reference yet

## 5. Blast radius

```
.env.example
acceptance.py
api/*
worker/*
web/*
tests/*
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py` `_new_chat`, the navigation to follow, which will take an
  optional thread url
- `api/src/db/client.py` `init_db`, the idempotent ALTER already used for `media.message_id`
- `api/src/routes/media.py` `_safe_path`, the rule that a stored name is a bare name and never a
  path; generic files must obey it too
- `worker/src/providers/mock.py` `solid_png`, the pattern of building a real artifact from the
  standard library rather than shipping a fixture

## Tasks

### T1: Three failing checks
Write the new acceptance checks and run them against the current code.
**Files:** acceptance.py
**Acceptance:** `python acceptance.py` reports 8/11 with the three new ones red for the right
reason, not for a missing endpoint

### T2: Thread reference on a conversation
Add `conversations.provider_thread_url`, idempotent ALTER for databases that already exist.
**Files:** api/src/db/schema.sql, api/src/db/client.py
**Acceptance:** the column exists, an existing database keeps every row

### T3: Hand the thread to the worker and store what comes back
The claim payload carries the conversation's thread url; the result carries the url the provider
ended up on; the API saves it.
**Files:** api/src/jobs.py, api/src/models.py, api/src/routes/internal.py
**Acceptance:** the two thread checks go green in mock mode

### T4: Provider follows the thread
`_new_chat` takes an optional url and returns the one it is on. A stored url that no longer loads
falls back to a fresh chat and reports the new url.
**Files:** worker/src/providers/base.py, worker/src/providers/chatgpt.py, worker/src/providers/mock.py, worker/src/pool.py, worker/src/runner.py
**Acceptance:** covered by T3's checks; the real run in T6 proves the browser half

### T5: Keep every deliverable, not just pictures
Capture the browser download a `Download ...` button triggers, store it under the media directory
with its own type, and let the mock build a real zip so the path is testable without a browser.
**Files:** worker/src/providers/chatgpt.py, worker/src/providers/mock.py, api/src/jobs.py, api/src/routes/media.py
**Acceptance:** the file check goes green, bytes match

### T6: A file card in the interface
Media whose type is not an image renders as a named file with a download, in the thread and in the
gallery.
**Files:** web/src/components/FileCard.jsx, web/src/pages/Chat.jsx, web/src/pages/Gallery.jsx, tests/ui_smoke.py
**Acceptance:** `python tests/ui_smoke.py` 17/17

### T7: Prove it against the real provider
A conversation whose second turn depends on the first, and a request that produces a zip.
**Files:** acceptance.py
**Acceptance:** `python acceptance.py --real` 8/8, plus a recorded run where asking for a zip
returns a file with `PK` magic

## Evidence

Measured at HEAD 68259f0, clean tree. Fence audit: 1 commit from base, every change inside the
blast radius, no deviations.

```
$ python acceptance.py                         11/11 PASSED   exit 0
$ python acceptance.py --real                  11/11 PASSED   exit 0
    image job produces file        856039 bytes
    video script job returns text  823 chars
    thread reused within a conversation   the model recalled teal-14350
    threads never cross conversations     a new conversation does not know teal-14350
    non image deliverable is kept  198 bytes, type file, entries ['a.txt', 'b.txt']
$ cd web && npm run build                      exit 0, 157.49 kB
$ python tests/ui_smoke.py                     17/17 PASSED
```

T1 was watched failing first: 8/11, the three new checks red because no thread was reported and a
zip request produced no media, not because an endpoint was missing.

### The invariant check earned its place

`threads never cross conversations` failed against the real provider while every mock check was
green. A fact stated in one conversation was recalled in a brand new one. Three measurements were
needed to find out why, and the first two guesses were wrong:

1. Guess: the root url restores the previous thread. Measured: after `goto(HOME)` the url was
   `https://chatgpt.com/` with zero assistant turns. The page was clean and it still leaked.
2. Guess: the phrase "Remember this word" invoked the memory feature. Measured: rephrased without
   any request to remember, it leaked anyway.
3. Asked the provider directly: `YES 10`. The account had memory enabled with ten items saved.

Nothing in this repository could have fixed it. The two switches were turned off with the user's
explicit permission and the result measured: the same thread still recalls `lychee-4242`, a new
conversation answers `Unknown`, the previously saved `mango-991` is not recalled, and the account
now reports `NO` saved memories. `ACCESS.md` records that this setting has to stay off.

### Deviations from the plan as written

- The plan said the two thread checks would read a marker the mock emits. Against the real provider
  there is no marker, and exposing the thread url through the API to get one would have leaked an
  internal identifier. Real mode measures continuity semantically instead: tell it a word, ask for
  it back, and require a new conversation not to know it. Stronger, and it is what caught the leak.
- `provider_thread_url` was removed from both conversation responses, which the plan did not
  anticipate because the column did not exist when the plan was written.
