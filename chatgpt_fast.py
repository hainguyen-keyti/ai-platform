#!/usr/bin/env python3
"""
ChatGPT Fast Client - gọi qua server đang chạy.

Yêu cầu server đang chạy:
    python chatgpt_server.py &

Usage:
    python chatgpt_fast.py "Hello!"
"""

import json
import sys
import urllib.request

SERVER_URL = "http://localhost:5123"


def chat(message: str) -> str:
    data = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "")
    except urllib.error.URLError as e:
        if "Connection refused" in str(e):
            print("Server chưa chạy. Start server trước:", file=sys.stderr)
            print("  ~/cloakbrowser-env/bin/python ~/Sources/RE/chatgpt/chatgpt_server.py &", file=sys.stderr)
            sys.exit(1)
        raise


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    message = " ".join(sys.argv[1:])
    result = chat(message)
    print(result)


if __name__ == "__main__":
    main()
