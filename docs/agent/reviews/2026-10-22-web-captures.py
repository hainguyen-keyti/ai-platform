#!/usr/bin/env python3
"""Screenshots of the states the web plan (2026-10-22) adds, for its design review. Every api call is
answered inside the browser (a made-up token, no account), so only the web on WEB_URL is needed.

    ~/cloakbrowser-env/bin/python docs/agent/reviews/2026-10-22-web-captures.py
"""
import json
import os
import struct
import zlib
from pathlib import Path
from urllib.parse import urlparse

import cloakbrowser

WEB_URL = os.environ.get("WEB_URL", "http://localhost:5173")
API_URL = os.environ.get("API_URL", "http://localhost:3000")
OUT = Path(__file__).with_name("2026-10-22-captures")
STAMP = "2026-10-22 10:00:00"
JSON = {"access-control-allow-origin": "*", "content-type": "application/json"}
ME = {"id": "u1", "email": "design.review@example.com", "name": "Design", "role": "user",
      "quota_remaining": 42, "quota_daily": 100}
PROVIDERS = {"providers": [{"name": p, "served": True} for p in ("chatgpt", "grok", "gemini")]}


def png(width, height):
    raw = b"".join(b"\x00" + b"\x80\x80\xff" * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def message(mid, role, content):
    return {"id": mid, "role": role, "content": content, "created_at": STAMP, "media": []}


def tile(n):
    return {"id": "g{}".format(n), "type": "image", "provider": "chatgpt", "prompt": "picture {}".format(n),
            "filename": "g{}.png".format(n), "conversation_id": None, "metadata": {}, "created_at": STAMP}


def page_for(browser, state, width, lang):
    context = browser.new_context(viewport={"width": width, "height": 844 if width < 768 else 900})
    context.add_init_script("localStorage.setItem('token', 'capture-token'); localStorage.setItem('lang', {!r});"
                            .format(lang))

    def answer(route):
        request = route.request
        url = urlparse(request.url)
        path, method = url.path, request.method
        if method == "OPTIONS":
            route.fulfill(status=204, headers={"access-control-allow-origin": "*",
                                               "access-control-allow-headers": "*",
                                               "access-control-allow-methods": "*"}, body="")
            return
        if path == "/auth/me":
            if state.get("me_down"):
                route.abort()
                return
            body = ME
        elif path == "/providers":
            body = PROVIDERS
        elif path == "/conversations" and method == "GET":
            body = {"items": [{"id": cid, "provider": "chatgpt", "title": c["title"], "created_at": STAMP,
                               "updated_at": STAMP} for cid, c in state.get("convs", {}).items()]}
        elif path.startswith("/conversations/") and method == "GET":
            cid = path.rsplit("/", 1)[-1]
            c = state["convs"][cid]
            body = {"id": cid, "provider": "chatgpt", "title": c["title"], "created_at": STAMP,
                    "updated_at": STAMP, "orphan_media": [], "messages": c["messages"]}
        elif path == "/chat" and method == "POST":
            if state.get("chat_status"):
                route.fulfill(status=state["chat_status"], headers=JSON,
                              body=json.dumps({"detail": state.get("chat_detail", "refused")}))
                return
            sent = json.loads(request.post_data)
            cid = sent.get("conversation_id") or state["new_conv"]
            state["convs"].setdefault(cid, {"title": sent["message"][:40], "messages": []})
            state["convs"][cid]["messages"].append(message("u{}".format(len(state["convs"][cid]["messages"])),
                                                           "user", sent["message"]))
            body = {"job_id": "cap-job", "conversation_id": cid}
        elif path == "/jobs/cap-job":
            job = state["job"]
            body = {"id": "cap-job", "status": job["status"], "phase": job.get("phase"),
                    "error": job.get("error"), "error_kind": job.get("error_kind")}
        elif path == "/media" and method == "GET":
            if state.get("media_status"):
                route.fulfill(status=state["media_status"], headers=JSON, body=json.dumps({"detail": "database is locked"}))
                return
            query = dict(p.split("=", 1) for p in url.query.split("&") if "=" in p)
            offset, limit = int(query.get("offset", 0)), int(query.get("limit", 100))
            items = state.get("media", [])
            body = {"total": len(items), "items": items[offset:offset + limit]}
        elif path.startswith("/media/") and path.endswith("/file"):
            route.fulfill(status=200, headers={"access-control-allow-origin": "*", "content-type": "image/png"},
                          body=png(64, 64))
            return
        else:
            route.fulfill(status=404, headers=JSON, body=json.dumps({"detail": "not answered by the capture"}))
            return
        route.fulfill(status=200, headers=JSON, body=json.dumps(body))

    view = context.new_page()
    view.route(API_URL + "/**", answer)
    view.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
    return context, view


def snap(view, name):
    view.wait_for_timeout(600)
    view.screenshot(path=str(OUT / "{}.png".format(name)))
    print(name)


def main():
    OUT.mkdir(exist_ok=True)
    browser = cloakbrowser.launch(headless=True)
    words = {"en": ("Send", "gallery", "input[placeholder^='Type a message']"),
             "vi": ("Gửi", "thư viện", "input[placeholder^='Nhập tin nhắn']")}
    try:
        for width in (1280, 390):
            for lang in ("en", "vi"):
                send, gallery, composer = words[lang]
                tag = "{}-{}".format(width, lang)

                context, view = page_for(browser, {"me_down": True}, width, lang)
                view.wait_for_selector("[data-testid=retry-connection]", timeout=15000)
                snap(view, "a-retry-" + tag)
                context.close()

                context, view = page_for(browser, {"convs": {}, "media": [tile(n) for n in range(137)]}, width, lang)
                view.click("nav button:has-text('{}')".format(gallery), timeout=15000)
                view.wait_for_selector("[data-testid=gallery-more]", timeout=15000)
                view.evaluate("() => { const g = document.querySelector('main .overflow-y-auto:not(.hidden *)');"
                              " if (g) g.scrollTop = g.scrollHeight; }")
                snap(view, "b-gallery-more-" + tag)
                context.close()

                state = {"convs": {}, "new_conv": "c1", "job": {"status": "running", "phase": "picture appeared"}}
                context, view = page_for(browser, state, width, lang)
                view.wait_for_selector(composer, timeout=15000)
                view.fill(composer, "draw a lighthouse at dusk")
                view.click("button:has-text('{}')".format(send))
                view.wait_for_selector("[data-testid=typing-phase]", timeout=15000)
                snap(view, "c-phase-" + tag)
                state["job"] = {"status": "failed", "error_kind": "provider_error",
                                "error": "TimeoutError: Locator.inner_text: Timeout 30000ms exceeded."}
                view.wait_for_selector("header .text-red-600", timeout=15000)
                snap(view, "d-turn-failed-" + tag)
                state["chat_status"], state["chat_detail"] = 402, "quota exhausted"
                view.fill(composer, "one more")
                view.click("button:has-text('{}')".format(send))
                snap(view, "e-no-credit-" + tag)
                context.close()

                context, view = page_for(browser, {"convs": {}, "media_status": 500}, width, lang)
                view.click("nav button:has-text('{}')".format(gallery), timeout=15000)
                view.wait_for_selector("main .text-red-600", timeout=15000)
                snap(view, "f-gallery-error-" + tag)
                context.close()

        for width in (1280, 390):
            for lang in ("en", "vi"):
                send, gallery, composer = words[lang]
                state = {"convs": {"a": {"title": "alpha", "messages": [message("a1", "user", "question alpha")]},
                                   "b": {"title": "bravo", "messages": [message("b1", "user", "question bravo"),
                                                                        message("b2", "assistant", "answer bravo")]}},
                         "new_conv": "a", "job": {"status": "running", "phase": "reply started"}}
                context, view = page_for(browser, state, width, lang)
                pick = "[data-testid=conversation-item] button:has-text('{}')"
                if width < 768:
                    view.click("[data-testid=open-conversations]", timeout=15000)
                view.locator(pick.format("alpha")).first.click(timeout=15000)
                view.wait_for_selector("text=question alpha", timeout=15000)
                view.fill(composer, "and another thing")
                view.click("button:has-text('{}')".format(send))
                view.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
                if width < 768:
                    view.click("[data-testid=open-conversations]", timeout=15000)
                view.locator(pick.format("bravo")).first.click()
                view.wait_for_selector("text=answer bravo", timeout=15000)
                snap(view, "g-job-elsewhere-{}-{}".format(width, lang))
                context.close()
    finally:
        browser.close()


if __name__ == "__main__":
    main()
