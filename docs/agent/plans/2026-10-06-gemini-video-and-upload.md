# Plan: Gemini's video is collected, and its renamed upload button is found

Approved by the owner on 2026-10-06: **"Duyệt, làm ngay (Recommended)"**.

## 1. Goal

The owner, 2026-10-06: **"Sao rồi dùng cứ báo lỗi, bạn tự bật lên và test manual lại các model
đi"**. The agent's walk of the web found two Gemini faults; asked how to fix them, the owner chose
**"Sửa cả hai (Recommended)"**, offered as: "Một plan: Gemini nhận nút đính kèm mới, và nền tảng
lấy được video Gemini làm, xem ngay trong chat và thư viện. Sẽ dùng 1-2 lượt làm video thật của
tài khoản Gemini để đo và thử."

Measured on 2026-10-06:
- The owner's turn of 13:19, "Tạo video 30s nó về cuộc sống thời AI hiện nay" (gemini, chat), failed
  after 54s as `provider_timeout`, "gemini's turn carried neither words nor a picture" (job
  34af03ba, its own record), refunded. Its thread (1dfbd9cdd9657b27, opened read-only at 13:59)
  holds "Video của bạn đã sẵn sàng!" and a 10 second video
- **One real video turn, watched** (`/tmp/gemini_video_watch.py`, 14:50, thread 5cbf5c7ea13d3b12,
  "Tạo video 10 giây về một chú mèo con đang ngủ dưới nắng bên cửa sổ."): the stream finished
  6.7s after the send. From 4.3s the answer showed "Tôi đang tạo video. Quá trình này có thể mất
  vài phút ..." with **no `message-content`**, so the driver's reader finds no words. At 73.5s the
  answer's `message-content` read "Video của bạn đã sẵn sàng!" and the player's time ("0:00 /
  0:00", then "0:00 / 0:10"), holding `generated-video` > `video-player` > `video` whose address is
  `contribution.usercontent.google.com/download?c=...&filename=...&opi=...`. Fetched inside the
  session: 200 `video/mp4`, 3,700,709 bytes, H.264 1280x720 with AAC, 10.0s. The page changed by
  itself, with no reload
- Gemini's video script (from a Gemini picture, through the web, 14:03) failed in 21s, "gemini's
  upload control did not open". The button's label was "Add files" on one load and "Upload &
  tools" on four others (13:59 to 14:57); the driver matches "Upload" or "Nội dung tải lên". Its
  place held: the one `button[aria-haspopup="menu"]` inside `simplified-input-menu` (one match on a
  new chat and on a thread page, 14:58). Once pressed, `input[type="file"][accept="image/*"]` is
  there at once, and a picture set on it was accepted (ProcessFile 200, nothing sent)
- In the platform, media of type `image` shows as a picture and anything else as a file card
  (`web/src/pages/Chat.jsx:42`, `web/src/pages/Gallery.jsx:45`); the api serves `.mp4` as
  `application/octet-stream` (`api/src/routes/media.py` CONTENT_TYPES has no video). The test
  browser plays a 64x64 H.264 mp4 (readyState 4, duration 1; measured with cloakbrowser)

Done means: asked for a video in a chat turn, Gemini's turn comes back with its words and the
video, which plays in the chat and in the gallery; a video that never comes fails and refunds
after `VIDEO_WAIT`; Gemini's video script uploads its picture whatever the button is called.

## 2. Non-goals

- ChatGPT's and Grok's videos; Gemini's own "Create video" tool in its menu; asking Gemini for a
  length (it makes about 10 seconds whatever is asked)
- A video feature, button or job kind in the web or the api: the video comes from a chat turn
- Posters, thumbnails, transcoding, range requests or streaming: the web loads the whole file, as
  it does a picture
- The admin usage page and the worker's image budget counting videos
- Gemini's daily video allowance (not measured; a refusal comes back as words, returned as words)
- One answer that both writes words and makes a video (not measured)
- The other parked Gemini points (its own error sentence taken as a reply, a stop before the send)

## 3. Invariants touched and risk tier

- **Quota.** A video turn is charged once, like any turn; a video that never comes fails and is
  refunded exactly once, through the existing settle
- **One job, one turn's answer.** The video is taken only from the answer after this turn's own
  question, by the rule its words already follow, never from an earlier turn of a reopened thread
- **A stop is honoured during the video wait**: the job ends cancelled and hands its thread back
  for removal, as it does during the reply
- Media belongs to the job's user and conversation (the api's insert, unchanged)

### Risk tier

**Tier 2** (a feature and its interface): one review round by a separate reviewer and one
design-review pass of the web; after fixes, acceptance with mutants, no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_gemini_driver.py   # N/N PASSED (111 before); the new checks red first on the driver as it stands
python acceptance.py                                         # 44/44 PASSED; the new check red first (the api serves the mp4 as application/octet-stream)
python acceptance.py && (cd web && npm run build) && ~/cloakbrowser-env/bin/python tests/ui_smoke.py   # once, at the end: 44/44, build exit 0, 55/55 (53 and two, red first)
```

Mutants on a copy, each red: the upload button matched by its old labels only; no video wait (an
answer without words fails at once); the player's time left in the reply's words; an earlier
turn's video taken; a video wait with no ceiling, or deaf to a stop; the api serving `.mp4` as
`application/octet-stream`; the web showing a video as a file card.

Real, the host worker real, through the web as a user, on the new code:
- one Gemini chat turn asking for a video is done with its words and one video (type `video`,
  `video/mp4`, starts with `ftyp`), which plays in the chat (duration above 0) and shows in the
  gallery. This is the second of the owner's one or two video turns
- one Gemini video script from a Gemini picture is done with a script

## 5. Blast radius

```
worker/src/providers/gemini.py
worker/src/providers/mock.py
tests/test_gemini_driver.py
tests/fixtures/gemini_video_thread.html
api/src/routes/media.py
acceptance.py
web/src/pages/Chat.jsx
web/src/pages/Gallery.jsx
web/src/components/MediaVideo.jsx
web/src/lib/strings.jsx
tests/ui_smoke.py
docs/research/2026-09-27-gemini.md
```

## 6. Reuse pointers

- `worker/src/providers/gemini.py`: `_attach` (the upload); `_run` after the stream (the words
  loop, pictures fetched inside the session through `self._context.request.get`);
  `ANSWER_AFTER_QUERY` and `MARK_QUERIES`; the `JobCancelled` handling that hands the thread back
- `tests/test_gemini_driver.py`: the fake `Page` (`answer`, `replies`, `file_input`,
  `process_file`), `Session.served`, `markup_cases` (the driver's scripts on a captured thread, in
  a real browser)
- `worker/src/providers/mock.py` `_store` and its phrases; `acceptance.py` `check_zip` (a media item
  fetched and its bytes read) and `REAL_SKIPS`
- `web/src/components/MediaImage.jsx` (a media file fetched with the token into a blob url),
  `web/src/components/FileCard.jsx` (download), `MediaCard` in `web/src/pages/Chat.jsx`
- `tests/ui_smoke.py`: "generated image renders in chat"
- `/tmp/gemini_video_watch.py`, `/tmp/gemini_video_capture.py`, `/tmp/gemini_upload_shape.py`:
  the measurements

## Tasks

### T1: Red checks for the driver
Copy the captured video turn (`/tmp/gemini_video_thread.html`, its video's address already a
placeholder) to `tests/fixtures/gemini_video_thread.html`. The fake page grows an upload button
(its label, its place; the image input only after a press) and a video turn as measured (a note
and no `message-content` until 74s, then words, the player's time and a video address; the session
serves the bytes). Checks: the picture is handed over under "Add files" and under "Upload &
tools"; the measured video turn succeeds with the words alone and one media of type `video`
holding the served bytes; a video that never comes fails after `VIDEO_WAIT` with words that say
so; an answer that shows nothing fails at once, as now; a reopened thread's earlier video is not
this turn's; a stop during the video wait cancels and hands the thread back; on the captured
markup the driver's script reads "Video của bạn đã sẵn sàng!" without the time and finds the
video's address.
**Files:** tests/test_gemini_driver.py, tests/fixtures/gemini_video_thread.html
**Acceptance:** the new checks red on the driver as it stands, the 111 others green

### T2: The driver
`UPLOAD_CONTROL`: the place first (`simplified-input-menu button[aria-haspopup="menu"]`), then the
labels seen ("Upload", "Add files", "Nội dung tải lên"); the image input awaited up to 5s after
the press. After the stream, an answer that shows a note but no words is waited on (phase "making
a video") up to `VIDEO_WAIT` = 300s, checking for a stop, until it holds words and a video; the
video is fetched inside the session and kept as `gemini-<hex>.mp4`, type `video`.
`ANSWER_AFTER_QUERY` also reports the note and the video's address, and leaves the player's text
out of the words.
**Files:** worker/src/providers/gemini.py
**Acceptance:** `tests/test_gemini_driver.py` N/N; `python acceptance.py` 43/43

### T3: The platform keeps and serves a video
The mock answers a phrase ("make a short video") with words and a one second mp4 (64x64 H.264,
1853 bytes, made with ffmpeg); the api serves `.mp4` as `video/mp4`; a gate check "a video the
provider makes is kept and served as a video" (type `video`, `video/mp4`, `ftyp`), skipped on real
providers ("costs one of the account's few videos a day; the plan's real turn proves it").
**Files:** worker/src/providers/mock.py, api/src/routes/media.py, acceptance.py
**Acceptance:** the check red first on the api as it stands; then `python acceptance.py` 44/44

### T4: The web plays it
`MediaVideo` (the file fetched with the token into a blob url, as `MediaImage` does) shows a
`<video controls>` with a download button, in the chat and in the gallery. ui_smoke: the mock's
video turn shows a video that loads (duration above 0) in the chat, and in the gallery.
**Files:** web/src/components/MediaVideo.jsx, web/src/pages/Chat.jsx, web/src/pages/Gallery.jsx,
web/src/lib/strings.jsx, tests/ui_smoke.py
**Acceptance:** the two checks red first; then `tests/ui_smoke.py` 55/55

### T5: Review, design review, mutants, the full gate, the real turns, Evidence
The measurements go into `docs/research/2026-09-27-gemini.md`; the tier 2 review and a
design-review pass; the mutants; the full gate once; the real video turn and the real video script
through the web; Evidence.
**Files:** docs/research/2026-09-27-gemini.md, whatever the review names inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-10-06 at **c691726**, clean tree, seven commits from d2d346d, the audit clean. Every
number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_gemini_driver.py` | **136/136 PASSED** at c691726. Red first: 116/127 at 6c728c0 (the eleven behaviour checks: the upload control did not open, the video turn failed after 15s as "neither words nor a picture", the player's time in the words); then the fix round's checks 128/135 on c1ba270 (seven: the placeholder pressed, "Gemini said" read as a note, the thread lost on a failed fetch, an http address fetched, a refusal thrown away after 315s) |
| `python acceptance.py` | **44/44 PASSED**; red first 43/44 before 0dc558e: the video kept as type video but served as application/octet-stream |
| `tests/ui_smoke.py` | **56/56 PASSED**; red first 53/55 at 0dc558e (a file card where a video belongs), then 53/56 before 3343c1f (no name on the player, no failed state) |
| **Full gate, once on the final tree, at c691726, the host worker in mock (18:28 to 18:36)** | `python acceptance.py` **44/44** exit 0; `npm run build` exit 0; `tests/ui_smoke.py` **56/56**, "no console errors" []; tree unchanged after |
| The first full gate, at 3343c1f (16:59 to 17:07) | **red**: 44/44, build exit 0, ui_smoke **55/56**: "no console errors" caught `Failed to load resource: net::ERR_FILE_NOT_FOUND` (below, Left open) |
| Mutants, each on a copy | round one, 12 of 12 red (`/tmp/run_video_mutants.py`; M4b first written so a later read undid it, rewritten as the real bug, red); round two, 12 of 12 red (`/tmp/run_review_mutants.py`: the reviewer's survivors, the wait pinned at 300s, no address in an error, the thread on a timeout, a video already there, the page put back as it was, no file before the ftyp check, the open wait, the placeholder, the control wait, the note's label, words for a video, plain http). The api's and the web's mutants are the red-first runs above |
| **Real, through the web as a user, the host worker real on 3343c1f, a headless browser (18:20 to 18:24)** | "Tạo video 10 giây về một chú chó con đang chơi với quả bóng đỏ trong vườn." on Gemini: **done in 106s** (phases waiting, reply started, making a video), the words "Video của bạn đã sẵn sàng!" and **one video, 6,089,287 bytes, 1280x720, 10.0s, that plays in the chat and in the gallery** (readyState 4, named, a Download link), no console error. "Video script" on a Gemini picture: **done in 42s, a 485 character script** (it had failed in 21s at 14:03) |

Review, tier 2:
- The code review: nothing blocking; five groups of points, all fixed in 00c8f54 except the
  unpinned one-second second read and the loosened place selectors (equivalent on the measured page:
  one button inside `simplified-input-menu`, 16:58)
- The design review: nothing blocking; fixed in 3343c1f: the gallery player on a phone (145px wide
  at 390, 110px at 320, where Chrome keeps only its menu; now 324 and 254), the failed state (it
  said "could not load image" in English; now "Không tải được video." in the player's place), the
  card's jump while loading, the player's name, a tall video's height. Left: the gallery tiles'
  footers do not line up, 26px tap targets (older, the whole app), the whole file loaded before it
  plays

Deviations:
- **The plan's premise about the upload button was half wrong.** The plan read "Add files" as one of
  the real button's labels. Measured during the review fixes (16:5x, read-only), it is a placeholder
  shown while the input area is not ready, outside `simplified-input-menu`; pressing it opened
  nothing in 6.3s; the real "Upload & tools" button replaced it 0.5 to 2.5s after the composer in
  four loads. The driver of c1ba270 would have pressed the placeholder. The check written in T1 on
  the plan's premise ("found by the label 'Add files'") was replaced by "the placeholder is never
  pressed, and the real button is waited for" (DECISIONS, 2026-10-06)
- The words without a video (a refusal after the note) are returned as the answer and charged like
  any answer, which the plan's non-goals already said; the driver of c1ba270 did not do it
- `tests/ui_smoke.py`'s three filters for the errors it causes on purpose were edited through the
  shell (in c691726), inside the radius; noted here
- The real turns ran in a headless browser, not the app's Browser pane, which had stopped drawing

Left open:
- **An intermittent console error**: `Failed to load resource: net::ERR_FILE_NOT_FOUND` on a blob
  address of the web, in 2 of 17 UI runs between 17:03 and 17:23 and in none of the 15 after (the
  final gate included). Four mechanisms were tried and none reproduced it: a detached video whose
  blob is revoked (5 delays, a 1KB and a 3.7MB clip), the page left mid-read, the chat and the
  gallery swapped with a video on screen, a page brought back from the background and unmounted at
  once. The cause is not proven; since c691726 the test keeps each console error with its address
  and its step, so the next one says where it came from
- Not measured: the pending state's own markup (only its text and the absent message-content were
  read), Gemini's daily video allowance and what it says when it runs out, an answer that writes and
  makes a video at once
- The worker's whole-file download of a video (6 MB here) before the player shows

Real Gemini turns spent by this plan: two videos (the probe's, 14:50, thread 5cbf5c7ea13d3b12, and
the proof's, 18:20, thread 4eb4bcfad516f66d), one video script (thread 7bdd49792accfd7d), and page
loads only for the other measurements.
