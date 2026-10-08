# Image API (`/v1/images`)

Make pictures with ChatGPT from a program. You send a prompt, and optionally one picture to use as
the reference; the call answers at once with a request id; you ask for the request's status until
it is done; then you download each picture it made.

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

A key works only on `/v1/images`. It does not sign in to the web, and the web's login does not work
here. Keep it out of code you share; if it leaks, revoke it and make another.

## 1. Send a request

`POST /v1/images`, as `multipart/form-data`:

| Field | Required | What |
|---|---|---|
| `prompt` | yes | What to make, up to 8000 characters |
| `image` | no | One picture file to use as the reference: PNG, JPEG or WEBP, at most 10 MB, at most 16384 pixels a side and 50 megapixels. Send one; if several are sent, the last one is used |

```
curl -X POST http://localhost:3000/v1/images \
  -H "Authorization: Bearer $AIP_API_KEY" \
  -F "prompt=the same fox, at night, in the snow" \
  -F "image=@fox.png"
```

Answer, `202`:

```json
{"id": "5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a", "status": "queued"}
```

The picture is checked by its content, not by its file name: its own header must say PNG, JPEG or
WEBP and give its size. With a picture, ChatGPT is asked to use it as the reference for a new image
made from your prompt.

## 2. Ask for the status

`GET /v1/images/{id}`. Ask every few seconds until `status` is `done`, `failed` or `cancelled`.

```
curl -H "Authorization: Bearer $AIP_API_KEY" http://localhost:3000/v1/images/5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a
```

```json
{
  "id": "5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a",
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
| `queued` | Waiting for ChatGPT to be free |
| `running` | ChatGPT is making it |
| `done` | Finished: `images` holds what was made, `text` any words ChatGPT added |
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

## Errors

Every error answers JSON with a `detail`: a sentence, or for a missing or malformed field (`422`) a
list naming the field. A refused request costs nothing and keeps nothing.

| Status | When |
|---|---|
| `401` | No key, an unknown or revoked key, or a web login token |
| `402` | No credit left today |
| `404` | No such request or picture, it is someone else's, or it was not made through `/v1` |
| `413` | The request is over 10 MB (checked before the key), or the picture is over 10 MB, 16384 pixels a side or 50 megapixels |
| `415` | The file is not a PNG, JPEG or WEBP picture whose size can be read (an empty file too) |
| `422` | No prompt, a prompt that is empty or too long, or `image` sent as text instead of a file |
| `503` | ChatGPT is not available right now; try again later |

## A ready example

`scripts/image_api_example.py` does all three steps with the Python standard library:

```
export AIP_API_KEY=aip_...
python3 scripts/image_api_example.py --prompt "a red fox in the snow"
python3 scripts/image_api_example.py --prompt "the same fox at night" --image fox.png --out pictures
```

It prints the request id, waits for the result, and saves each picture into `--out`. `--api` (or
`AIP_API_URL`) sets the address when the platform is not on `http://localhost:3000`.
