#!/usr/bin/env python3
"""Keeps a per-second record of the machine around any stall of the api (issue #41).

The api and Docker stood still for minutes on 2026-11-17 and SQLite reported "database is locked", and a
replay did not bring it back, so the next one must leave its own record. Every second this samples the api's
/health (from a thread of its own, so a hung request is seen as hanging), the load, the memory left, swap in
and out, the kernel's pressure stall information and the browsers' processes, and keeps the last --before
seconds in memory. When /health takes longer than --slow seconds or fails, those seconds go to a file named
by the time, and the record goes on until --after seconds past the last slow one. Only the newest --keep files
stay. Standard library only; started as the user service aip-stall-watch (scripts/install-stall-watch.sh).
"""
import argparse
import csv
import os
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["at", "health_s", "health_status", "health_in_flight_s", "load1", "mem_avail_mb", "swap_free_mb",
          "pswpin_s", "pswpout_s", "psi_mem", "psi_cpu", "psi_io", "chrome_procs", "chrome_rss_mb"]


def meminfo():
    values = {}
    for line in open("/proc/meminfo"):
        key, rest = line.split(":", 1)
        values[key] = int(rest.split()[0]) // 1024
    return values.get("MemAvailable", ""), values.get("SwapFree", "")


def swaps():
    values = dict(line.split() for line in open("/proc/vmstat") if line.startswith("pswp"))
    return int(values.get("pswpin", 0)), int(values.get("pswpout", 0))


def pressure(kind):
    try:
        return float(open("/proc/pressure/{}".format(kind)).readline().split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        return ""


def browsers():
    count = rss = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if "chrom" not in open("/proc/{}/comm".format(pid)).read():
                continue
            count += 1
            for line in open("/proc/{}/status".format(pid)):
                if line.startswith("VmRSS:"):
                    rss += int(line.split()[1]) // 1024
        except OSError:
            continue
    return count, rss


class Health:
    """Asks /health once a second from its own thread; a request that hangs is seen while it hangs."""

    def __init__(self, url):
        self.url, self.lock = url, threading.Lock()
        self.last_s, self.last_status, self.since = "", "", None
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            started = time.time()
            with self.lock:
                self.since = started
            try:
                with urllib.request.urlopen(self.url, timeout=300) as answer:
                    status = answer.status
            except Exception as exc:
                status = type(exc).__name__
            with self.lock:
                self.last_s, self.last_status, self.since = round(time.time() - started, 3), status, None
            time.sleep(max(0.0, 1 - (time.time() - started)))

    def read(self):
        with self.lock:
            hanging = round(time.time() - self.since, 1) if self.since else 0
            return self.last_s, self.last_status, hanging


def prune(out, keep):
    kept = sorted(out.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in kept[keep:]:
        old.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:3000/health")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "storage" / "diagnostics"
                                             / "stall-watch"))
    parser.add_argument("--slow", type=float, default=5.0, help="seconds of /health that count as a stall")
    parser.add_argument("--before", type=int, default=120, help="seconds kept before a stall")
    parser.add_argument("--after", type=int, default=60, help="seconds kept after the last slow second")
    parser.add_argument("--keep", type=int, default=50, help="records kept, newest first")
    parser.add_argument("--duration", type=float, default=0, help="stop after this many seconds (0: never)")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    health, recent = Health(args.url), deque(maxlen=args.before)
    record = writer = None
    last_slow = 0.0
    swapped = swaps()
    started = next_tick = time.time()
    while not args.duration or time.time() - started < args.duration:
        now = time.time()
        health_s, status, hanging = health.read()
        swap_now = swaps()
        avail, swap_free = meminfo()
        procs, rss = browsers()
        row = [round(now, 2), health_s, status, hanging, open("/proc/loadavg").read().split()[0], avail, swap_free,
               swap_now[0] - swapped[0], swap_now[1] - swapped[1], pressure("memory"), pressure("cpu"),
               pressure("io"), procs, rss]
        swapped = swap_now
        slow = hanging > args.slow or (health_s != "" and health_s > args.slow) or status not in ("", 200)
        if slow:
            last_slow = now
        if record is None and slow:
            name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".csv"
            record = open(out / name, "w", newline="")
            writer = csv.writer(record)
            writer.writerow(FIELDS)
            writer.writerows(recent)
        if record is not None:
            writer.writerow(row)
            record.flush()
            if now - last_slow >= args.after:
                record.close()
                record = None
                prune(out, args.keep)
        recent.append(row)
        next_tick += 1
        time.sleep(max(0.0, next_tick - time.time()))
    if record is not None:
        record.close()
        prune(out, args.keep)


if __name__ == "__main__":
    main()
