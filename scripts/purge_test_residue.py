#!/usr/bin/env python3
"""Remove the platform's own test residue from the shared ChatGPT account.

    ~/cloakbrowser-env/bin/python scripts/purge_test_residue.py <list.json>          # dry run
    ~/cloakbrowser-env/bin/python scripts/purge_test_residue.py <list.json> --yes    # delete

The list is a JSON object {"threads": [ids], "memories": [ids]} prepared and reviewed by a
person (docs/agent/residue-to-delete-2026-09-24.json is the one from 2026-09-24). A dry run reads
the list and prints the counts; nothing is sent. With --yes, threads are hidden with
PATCH /backend-api/conversation/<id> {"is_visible": false} (measured 2026-09-24: 200, then the
thread answers 404) and memories with DELETE /backend-api/memories/<id>, one request per second,
each status printed; the run stops at the first 401. It uses the saved provider session in
storage/sessions, so stop the host worker first. This is the owner's action to run, on purpose.
"""

import json
import re
import sys
import tempfile
import time
from pathlib import Path

# Ids go into request paths; anything that is not a plain id is refused up front.
ID_SHAPE = re.compile(r"^[0-9a-fA-F-]{8,64}$")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

REQUEST = """
async ([url, token, method, body]) => {
    const opts = {method: method, credentials: "include",
                  headers: {Authorization: "Bearer " + token}};
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = body; }
    const r = await fetch(url, opts);
    return {status: r.status};
}
"""


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(paths) != 1:
        sys.exit(__doc__)
    plan = json.loads(Path(paths[0]).read_text())
    threads = [str(x) for x in plan.get("threads") or []]
    memories = [str(x) for x in plan.get("memories") or []]
    odd = [x for x in threads + memories if not ID_SHAPE.match(x)]
    if odd:
        sys.exit("refusing: {} id(s) are not plain ids, for example {!r}".format(len(odd), odd[0][:40]))
    print("{} threads, {} memories".format(len(threads), len(memories)))
    if "--yes" not in sys.argv:
        print("dry run: no request made; add --yes to delete them")
        return 0

    from src.providers.chatgpt import ChatGPTProvider

    provider = ChatGPTProvider(Path(tempfile.mkdtemp(prefix="purge-")), ROOT / "storage" / "sessions")
    provider.start()
    removed = failed = 0
    try:
        page = provider._open()
        # A fresh browser's first read answers empty (2026-10-31: this script said log in, signed in all along).
        token = provider._session_token(page, 20)
        if not token:
            sys.exit("no session token: log in first with scripts/login_provider.py chatgpt")
        work = [("thread", i, "/backend-api/conversation/{}".format(i), "PATCH",
                 json.dumps({"is_visible": False})) for i in threads]
        work += [("memory", i, "/backend-api/memories/{}".format(i), "DELETE", None) for i in memories]
        for kind, ident, url, method, body in work:
            got = page.evaluate(REQUEST, [url, token, method, body])
            status = got.get("status")
            done = status in (200, 204) or (kind == "thread" and status == 404)
            removed += 1 if done else 0
            failed += 0 if done else 1
            print("[{}] {} {} -> {}".format("ok" if done else "FAIL", kind, ident[:8], status), flush=True)
            if status == 401:
                print("the session was rejected; stopping here")
                break
            time.sleep(1.0)
    finally:
        provider.stop()
    print("done: {} removed, {} failed".format(removed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
