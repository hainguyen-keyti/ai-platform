#!/usr/bin/env python3
"""Make a picture with ChatGPT, Grok or Gemini through the platform's image API, the way a program would.

    export AIP_API_KEY=aip_...     # made on the web, page "API"; shown once
    python3 scripts/image_api_example.py --prompt "a red fox in the snow"
    python3 scripts/image_api_example.py --prompt "the same fox at night" --image fox.png --out pictures
    python3 scripts/image_api_example.py --provider grok --prompt "a lighthouse at sunset"
    python3 scripts/image_api_example.py --prompt "the fox of the first in the second's forest" --image fox.png --image forest.png
    python3 scripts/image_api_example.py --prompt "the same fox, asleep" --continue-from 5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a
    python3 scripts/image_api_example.py --account
    python3 scripts/image_api_example.py --cancel 5f0c2a9e1b8d4c7f9a3e6d2b1c0f8e7a

Standard library only. Sends the request, asks for its status every few seconds until it ends, then
saves each picture made into --out. --account prints the credits left today; --cancel cancels a
request sent earlier. The calls are described in docs/api-v1-images.md.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def call(method, url, key, body=None, content_type=None):
    """(status, body bytes); an error status is returned, not raised."""
    request = urllib.request.Request(url, data=body, method=method, headers={"Authorization": "Bearer " + key})
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def detail(raw):
    try:
        return json.loads(raw).get("detail") or raw.decode(errors="replace")
    except (ValueError, AttributeError):
        return raw.decode(errors="replace")


def form(prompt, images, provider=None, continue_from=None):
    """A multipart/form-data body with the prompt, the provider if named, the request it continues if
    any, and each picture given as an `image` file, in order."""
    boundary = uuid.uuid4().hex
    body = ('--{}\r\nContent-Disposition: form-data; name="prompt"\r\n\r\n'.format(boundary).encode()
            + prompt.encode() + b"\r\n")
    for name, value in (("provider", provider), ("continue_from", continue_from)):
        if value:
            body += ('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n'.format(boundary, name).encode()
                     + value.encode() + b"\r\n")
    for image in images or []:
        body += ('--{}\r\nContent-Disposition: form-data; name="image"; filename="{}"\r\n'
                 'Content-Type: {}\r\n\r\n'.format(
                     boundary, image.name, CONTENT_TYPES.get(image.suffix.lower(), "application/octet-stream")
                 ).encode() + image.read_bytes() + b"\r\n")
    return body + "--{}--\r\n".format(boundary).encode(), "multipart/form-data; boundary=" + boundary


def main():
    parser = argparse.ArgumentParser(description="Make a picture with ChatGPT, Grok or Gemini through /v1/images.")
    parser.add_argument("--api", default=os.environ.get("AIP_API_URL", "http://localhost:3000"),
                        help="the platform's api address (default: $AIP_API_URL or http://localhost:3000)")
    parser.add_argument("--prompt", help="what to make; required unless --account or --cancel")
    parser.add_argument("--account", action="store_true", help="print the credits left today, and stop")
    parser.add_argument("--cancel", metavar="REQUEST_ID", help="cancel a request sent earlier, and stop")
    parser.add_argument("--provider", choices=("chatgpt", "grok", "gemini"),
                        help="who makes it (default: the api's, chatgpt); grok takes no --image")
    parser.add_argument("--image", type=Path, action="append",
                        help="a PNG, JPEG or WEBP picture to use as a reference; up to 4 for chatgpt, in order")
    parser.add_argument("--continue-from", metavar="REQUEST_ID",
                        help="an earlier done request to continue, in the same provider thread")
    parser.add_argument("--out", type=Path, default=Path("."), help="where to save the pictures (default: here)")
    parser.add_argument("--wait", type=int, default=600, help="seconds to keep asking before giving up")
    args = parser.parse_args()

    key = os.environ.get("AIP_API_KEY")
    if not key:
        sys.exit("set AIP_API_KEY to a key made on the web's API page")
    api = args.api.rstrip("/")

    if args.account:
        status, raw = call("GET", api + "/v1/account", key)
        if status != 200:
            sys.exit("could not read the account ({}): {}".format(status, detail(raw)))
        account = json.loads(raw)
        print("{} of {} credits left today; they come back at {}".format(
            account["credits_left"], account["credits_daily"], account["refills_at"]))
        return
    if args.cancel:
        status, raw = call("POST", "{}/v1/images/{}/cancel".format(api, args.cancel), key)
        if status != 200:
            sys.exit("could not cancel {} ({}): {}".format(args.cancel, status, detail(raw)))
        print("request {} is {}".format(args.cancel, json.loads(raw)["status"]))
        return
    if not args.prompt:
        parser.error("--prompt is required unless --account or --cancel")

    body, content_type = form(args.prompt, args.image, args.provider, args.continue_from)
    status, raw = call("POST", api + "/v1/images", key, body, content_type)
    if status != 202:
        sys.exit("refused ({}): {}".format(status, detail(raw)))
    request_id = json.loads(raw)["id"]
    print("sent, request", request_id)

    deadline = time.time() + args.wait
    while True:
        status, raw = call("GET", "{}/v1/images/{}".format(api, request_id), key)
        if status != 200:
            sys.exit("could not read the request ({}): {}".format(status, detail(raw)))
        state = json.loads(raw)
        if state["status"] in ("done", "failed", "cancelled"):
            break
        if time.time() > deadline:
            sys.exit("still {} after {}s; ask again later: GET /v1/images/{}".format(
                state["status"], args.wait, request_id))
        time.sleep(3)

    if state["status"] != "done":
        sys.exit("{}: {}".format(state["status"], state.get("error") or "no reason given"))
    if state.get("text"):
        print("ChatGPT said:", state["text"])
    if not state["images"]:
        sys.exit("done, but no picture came back")
    args.out.mkdir(parents=True, exist_ok=True)
    for number, picture in enumerate(state["images"], 1):
        status, blob = call("GET", api + picture["url"], key)
        if status != 200:
            sys.exit("could not download {} ({})".format(picture["url"], status))
        path = args.out / "{}-{}{}".format(request_id[:8], number, SUFFIXES.get(picture["content_type"], ""))
        path.write_bytes(blob)
        print("saved", path)


if __name__ == "__main__":
    main()
