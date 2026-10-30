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
  "created_at": "2026-10-09 04:44:17",
  "finished_at": "2026-10-09 04:45:21"
}
```

| `status` | Meaning |
|---|---|
| `queued` | Waiting for the provider to be free |
| `running` | The provider is making it |
| `done` | Finished: `images` holds what was made, `text` any words the provider added |
| `failed` | Not made: `error` says why; the credit was given back |
| `cancelled` | Stopped before it finished; the credit was given back |

Times are UTC.

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

## Errors

Every error answers JSON with a `detail`: a sentence, or, when a field is missing or of the wrong
kind, a list naming the field. A refused request costs nothing and keeps nothing.

| Status | When |
|---|---|
| `400` | The form itself cannot be read, `provider` is not `chatgpt`, `grok` or `gemini`, a picture was sent to `grok`, more than one to `gemini`, or more than 4 to `chatgpt` |
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
