# Image API (`/v1/images`)

Make pictures with ChatGPT, Grok or Gemini from a program. You send a prompt, the provider you want
(ChatGPT unless you name another), and optionally one picture to use as the reference; the call
answers at once with a request id; you ask for the request's status until it is done; then you
download each picture it made. `GET /v1/providers` says which providers are there right now,
`GET /v1/account` how many credits are left today, and `POST /v1/images/{id}/cancel` cancels a
request sent by mistake.

A picture usually takes about a minute, sometimes up to five. Each request costs one credit, the
same as on the web, and a request that fails gives its credit back. Requests and their pictures
also show in your own chat list and gallery on the web.

## Your key

Open the web, click **API** in the top bar, give the key a name and press **Create key**. The key
(it starts with `aip_`) is shown **only once**: copy it then. The same page lists your keys and
revokes one; a revoked key stops working at once. You can have up to ten live keys.

Send the key on every call:

```
Authorization: Bearer aip_...
```

A key works only on `/v1`. It does not sign in to the web, and the web's login does not work
here. Keep it out of code you share; if it leaks, revoke it and make another.

## 0. Which providers

`GET /v1/providers` lists every provider: whether a worker serves it right now (`served`), whether
it makes pictures (`makes_pictures`) and whether it takes a reference picture (`takes_reference`).

```
curl -H "Authorization: Bearer $AIP_API_KEY" http://localhost:3000/v1/providers
```

```json
{"providers": [
  {"name": "chatgpt", "served": true, "makes_pictures": true, "takes_reference": true},
  {"name": "grok", "served": true, "makes_pictures": true, "takes_reference": false},
  {"name": "gemini", "served": true, "makes_pictures": true, "takes_reference": true}
]}
```

A provider that is not `served` answers a request with `503` until a worker serves it again.

Each entry also says how busy it is: `waiting`, the requests in its queue; `pictures_last_3h` and
`picture_budget`, what its worker has made of the pictures it allows itself in three hours (40 by
default, `IMAGE_BUDGET_3H`, so an account is not driven into a wall); and `budget_free_at` (UTC), set
only while that budget is spent. Past the budget a request is taken and charged but waits in the
queue until then; it still counts as `served`. The count starts again when the worker restarts.

## Your credits

`GET /v1/account` says how many credits are left today, the daily allowance, and when the balance
comes back (UTC). Worth asking before you send a set: each request takes one.

```
curl -H "Authorization: Bearer $AIP_API_KEY" http://localhost:3000/v1/account
```

```json
{"credits_left": 87, "credits_daily": 100, "refills_at": "2026-10-30T00:00:00Z"}
```

The balance comes back up to `credits_daily` on your first call of each UTC day, whatever the call
is. So this read already shows the new day's balance.

## 1. Send a request

**One conversation per key.** Every request of a key goes into that key's own conversation, and so
into one provider thread, for the day (UTC). The provider sees the key's earlier pictures of the
day. A new day, another provider and another key each start their own. The status answer names it
as `conversation_id`, and it shows on the web as "API key <name>, <provider>, <day>".

`POST /v1/images`, as `multipart/form-data`:

| Field | Required | What |
|---|---|---|
| `prompt` | yes | What to make, up to 8000 characters |
| `provider` | no | `chatgpt` (the default), `grok` or `gemini` |
| `continue_from` | no | The id of an earlier request of yours, made through `/v1` on the same provider, that ended `done`. The new request goes into that request's conversation, so the provider gets the prompt in the thread where it made that picture and can change it ("the same, at night") without the picture being sent back |
| `session` | no | A name, up to 64 characters, for a person or character (case and extra spaces do not count). The same name on the same key and provider goes into the same provider thread on any day; another name goes into a thread that sees none of its pictures. With no name, requests go into the key's thread for the day. Not with `continue_from`: a continued request stays in that request's session. |
| `image` | no | A picture file to use as a reference: PNG, JPEG or WEBP, at most 10 MB, at most 16384 pixels a side and 50 megapixels. `chatgpt` takes up to 4, each sent as its own `image` field, in the order they are used ("the character of the first in the scene of the second"); together they must fit the request's 10 MB. `gemini` takes one; Grok takes none |

```
curl -X POST http://localhost:3000/v1/images \
  -H "Authorization: Bearer $AIP_API_KEY" \
  -F "prompt=the same fox, at night, in the snow" \
  -F "provider=gemini" \
  -F "image=@fox.png"
```

Answer, `202`:

```json
{"id": "5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a", "status": "queued"}
```

The picture is checked by its content, not by its file name: its own header must say PNG, JPEG or
WEBP and give its size. With a picture, the provider is asked to use it as the reference for a new
image made from your prompt; Grok cannot be sent one.

## 2. Ask for the status

`GET /v1/images/{id}`. Ask every few seconds until `status` is `done`, `failed` or `cancelled`.

```
curl -H "Authorization: Bearer $AIP_API_KEY" http://localhost:3000/v1/images/5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a
```

```json
{
  "id": "5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a",
  "provider": "chatgpt",
  "continued_from": null,
  "session": null,
  "conversation_id": "0c1d2e3f4a5b4c6d8e9f0a1b2c3d4e5f",
  "status": "done",
  "text": "Here is the fox at night.",
  "error": null,
  "images": [
    {
      "id": "9b1d7e3c2a4f4e8d8c6b5a4f3e2d1c0b",
      "url": "/v1/images/5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a/files/9b1d7e3c2a4f4e8d8c6b5a4f3e2d1c0b",
      "content_type": "image/png",
      "bytes": 1843201
    }
  ],
  "budget_free_at": null,
  "created_at": "2026-10-09 04:44:17",
  "finished_at": "2026-10-09 04:45:21"
}
```

`budget_free_at` (UTC) is set only on a `queued` request held back by the worker's own picture budget
(`IMAGE_BUDGET_3H`, not a limit the provider reported): that of the account its conversation is on, even
while another account has room, or on no account yet, once every account's is spent. It waits until then.

| `status` | Meaning |
|---|---|
| `queued` | Waiting for the provider to be free |
| `running` | The provider is making it |
| `done` | Finished: `images` holds what was made, `text` any words the provider added |
| `failed` | Not made: `error` says why; the credit was given back |
| `cancelled` | Stopped before it finished; the credit was given back |

Times are UTC.

A request a provider answers in words alone, with no picture, ends `failed` with those words in `error`, and its credit comes back.

## Your sessions

`GET /v1/sessions` lists this key's named sessions, the last used first; `?provider=chatgpt` keeps to one provider.

```json
{"sessions": [{"name": "woman-a", "provider": "chatgpt", "conversation_id": "0c1d2e3f4a5b4c6d8e9f0a1b2c3d4e5f",
               "created_at": "2026-10-31 09:00:00", "requests": 3, "pictures": 3, "last_used": "2026-10-31 09:10:00"}]}
```

Separate sessions keep ChatGPT from seeing each other's pictures. They do not promise unlike faces when two
sessions share a reference picture or a near-identical prompt.

## 3. Download a picture

`GET` the `url` of each picture, with the same key. The answer is the picture file itself, with its
`Content-Type`.

```
curl -H "Authorization: Bearer $AIP_API_KEY" -o fox-night.png \
  http://localhost:3000/v1/images/5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a/files/9b1d7e3c2a4f4e8d8c6b5a4f3e2d1c0b
```

## 4. Cancel a request

`POST /v1/images/{id}/cancel` stops a request that is `queued` or `running` and gives its credit
back, once. The answer is the request's status, as `GET /v1/images/{id}` gives it. A request that
has already ended is left as it ended, and its status is answered unchanged. Asking again changes
nothing.

```
curl -X POST -H "Authorization: Bearer $AIP_API_KEY" \
  http://localhost:3000/v1/images/5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a/cancel
```

What happens to a request that is already running:

1. The request is `cancelled` and its credit is back at once.
2. Within a few seconds the worker learns of it. It stops waiting for the provider and keeps nothing
   that request makes.
3. With ChatGPT, the worker also presses the site's own Stop button. This ends a picture before it
   arrives, as measured on 2026-10-01 (`worker/src/providers/chatgpt.py`).

Measured on 2026-10-29 through this endpoint, on a request that had been running for 33 seconds:
the worker pressed Stop 3 seconds after the cancel, and the api refused the late result. No
picture was kept.

Only requests made through `/v1` can be cancelled here, by their owner: another person's request, a
picture made on the web and a chat turn answer `404`, as they do on a read.

## Video scripts

`POST /v1/scripts` with JSON writes a shot-by-shot script for an AI video model; `GET /v1/script-targets` lists the models and what each takes.

| Field | Required | What |
|---|---|---|
| `brief` | yes | The story, up to 8000 characters |
| `target` | yes | `flow`, `minimax_h3` or `wan`; or `production`, a director's whole film for no particular tool |
| `provider` | no | Who writes it: `grok` (the default), `chatgpt` or `gemini` |
| `scenes`, `total_seconds` | no | How many scenes, and about how long in all |
| `language` | no | The language of the dialogue, `vi` by default. The prompts are in English |
| `session` | no | A name, as for pictures: the same name goes into the same provider thread |

It answers `202` with an `id`. `GET /v1/scripts/{id}` gives `status` and, once `done`, `script`: `title`, `target`, `total_seconds`, `direction` (`concept`, `hook`, `visual_style`, `palette`), `characters`, and `scenes`, each with
`number`, `duration_seconds`, `description`, `camera`, `color`, `lighting`, `sound` (not for `wan`, which is silent), `dialogue`, `image_prompt`, `video_prompt`, and `negative_prompt` for `wan`. A reply that is not valid or does not fit the target ends `failed`
with the reason in `error`, and its credit comes back. `POST /v1/scripts/{id}/cancel` cancels one.

With `target` `production` the `script` is instead `title`, `total_seconds`, `concept` (`idea`, `audience`, `message`, `tone`, `visual_style`, `palette`, `synopsis`), `characters`, `settings`, `post`
(`pacing`, `transitions`, `color_grade`, `music`, `sound_mix`, `subtitles`, `format`) and `scenes` (`title`, `location`, `purpose`, `description`), each with `shots` of 0.5 to 60 seconds:
`number`, `duration_seconds`, `start_seconds`, `end_seconds`, `shot_size`, `angle`, `lens`, `movement`, `composition`, `action`, `lighting`, `color`, `sound`, `transition`, `dialogue`, `voice_over`, `on_screen_text`.
The film must run within 15% of `total_seconds`, and every text comes in `language`.

## Errors

Every error answers JSON with a `detail`: a sentence, or, when a field is missing or of the wrong
kind, a list naming the field. A refused request costs nothing and keeps nothing.

| Status | When |
|---|---|
| `400` | The form itself cannot be read, `provider` is not `chatgpt`, `grok` or `gemini`, a picture was sent to `grok`, more than one to `gemini`, more than 4 to `chatgpt`, a `session` is blank, or `session` came with `continue_from` |
| `401` | No key, an unknown or revoked key, or a web login token |
| `402` | No credit left today |
| `404` | No such request or picture, it is someone else's, or it was not made through `/v1` (on a read, a cancel, and the request `continue_from` names alike) |
| `409` | `continue_from` names a request that has not ended `done`, or one on another provider |
| `413` | The whole request is over 10 MB and 256 KB (checked before the key, as it arrives), or the picture is over 10 MB, 16384 pixels a side or 50 megapixels |
| `415` | The file is not a PNG, JPEG or WEBP picture whose size can be read (an empty file too) |
| `422` | No prompt or a prompt too long (a list), a prompt of only spaces (a sentence), or `image` sent as text instead of a file (a list) |
| `503` | The provider is not available right now; try again later |

## A ready example

`scripts/image_api_example.py` does all three steps with the Python standard library:

```
export AIP_API_KEY=aip_...
python3 scripts/image_api_example.py --prompt "a red fox in the snow"
python3 scripts/image_api_example.py --prompt "the same fox at night" --image fox.png --out pictures
python3 scripts/image_api_example.py --provider grok --prompt "a lighthouse at sunset"
python3 scripts/image_api_example.py --account
python3 scripts/image_api_example.py --cancel 5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a
```

It prints the request id, waits for the result, and saves each picture into `--out`. `--account`
prints the credits left today, and `--cancel` cancels a request sent earlier. `--api` (or
`AIP_API_URL`) sets the address when the platform is not on `http://localhost:3000`.
