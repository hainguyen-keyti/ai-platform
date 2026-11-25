#!/usr/bin/env python3
"""scripts/stall-watch.py keeps the seconds around a stall of the api, and only those (#41).

    python3 tests/test_stall_watch.py

A fake /health answers at once, then holds its answers for 8 s, then answers at once again. The watcher
runs against it with a 2 s threshold, 8 s kept before the slow request is seen (so about 5 s before the
stall began) and 3 s after; it must write exactly one record that starts at least 4 s before the stall, shows the request hanging, and ends after the api answered again. A folder that
already holds the most files allowed keeps the newest ones. Prints N/5 PASSED.
"""

import csv
import http.server
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class FakeHealth:
    """Answers /health at once, except between hold_from and hold_until, when it answers at hold_until."""

    def __init__(self):
        self.hold_from = self.hold_until = 0.0
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                now = time.time()
                if fake.hold_from <= now < fake.hold_until:
                    time.sleep(fake.hold_until - now)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:{}/health".format(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def main():
    out = Path(tempfile.mkdtemp(prefix="stall-watch-"))
    for i in range(3):
        old = out / "20200101T00000{}Z.csv".format(i)
        old.write_text("old\n")
        os.utime(old, (time.time() - 1000 + i, time.time() - 1000 + i))
    fake = FakeHealth()
    started = time.time()
    fake.hold_from, fake.hold_until = started + 8, started + 16
    watch = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "stall-watch.py"), "--url", fake.url, "--out", str(out),
         "--slow", "2", "--before", "8", "--after", "3", "--keep", "2", "--duration", "26"],
        capture_output=True, text=True, timeout=90)
    events = sorted(p for p in out.glob("*.csv") if not p.name.startswith("2020"))
    old_left = sorted(p.name for p in out.glob("2020*.csv"))
    record("the watcher ran to its end", watch.returncode == 0,
           "exit {} {}".format(watch.returncode, (watch.stderr or watch.stdout).strip()[-200:]))
    record("one stall gives exactly one record", len(events) == 1, [p.name for p in events])
    rows = list(csv.DictReader(open(events[0]))) if len(events) == 1 else []
    times = [float(r["at"]) for r in rows]
    hung = [float(r["health_in_flight_s"]) for r in rows]
    record("the record starts at least 4 s before the stall",
           bool(times) and times[0] <= fake.hold_from - 4,
           "first row {:.1f}s before the hold".format(fake.hold_from - times[0]) if times else "no rows")
    record("it shows the request hanging and ends at least 2 s after the api answered again",
           bool(times) and max(hung) >= 5 and times[-1] >= fake.hold_until + 2,
           "longest hang {}s, last row {:.1f}s after the release".format(
               max(hung) if hung else None, times[-1] - fake.hold_until if times else 0))
    record("with --keep 2 the folder keeps the two newest records",
           len(events) + len(old_left) == 2 and old_left == ["20200101T000002Z.csv"],
           "kept {} of ours and {}".format(len(events), old_left))
    print("{}/{} PASSED".format(sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
