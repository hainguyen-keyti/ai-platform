#!/usr/bin/env python3
"""A real account's picture budget outlives the worker: the times are kept where run-worker.sh says,
those older than the window drop off, and a worker told nothing neither reads nor writes them.
Prints N/N PASSED.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src import pool  # noqa: E402
from src.config import settings  # noqa: E402
from src.providers.base import GenerationResult, MediaArtifact  # noqa: E402

CHECKS = []


def record(name, passed, detail=""):
    CHECKS.append(passed)
    print("[{}] {}  {}".format("PASS" if passed else "FAIL", name, detail))


def picture():
    return GenerationResult(success=True, media=[MediaArtifact(filename="x.png", type="image")])


def main():
    home = Path(tempfile.mkdtemp(prefix="worker-pacing-", dir=str(Path.home() / ".cache")))
    budget = home / "pacing-chatgpt.json"

    settings.pacing_path = str(home)
    health = pool.ProviderHealth("chatgpt")
    record("a worker with no file starts at zero", health.images_in_window() == 0)
    health.note(picture(), 1.0)
    health.note(picture(), 1.0)
    record("a picture is written down at once", budget.exists() and len(json.loads(budget.read_text())) == 2)

    again = pool.ProviderHealth("chatgpt")
    record("a restarted worker still counts them", again.images_in_window() == 2, str(again.images_in_window()))

    settings.pacing_path = ""
    mock = pool.ProviderHealth("chatgpt")
    mock.note(picture(), 1.0)
    record("a worker not told where does not read the real account's count", mock.images_in_window() == 1,
           str(mock.images_in_window()))
    record("a worker not told where does not add to it", len(json.loads(budget.read_text())) == 2)

    settings.pacing_path = str(home)
    now = time.time()
    budget.write_text(json.dumps([now - pool.IMAGE_WINDOW_SECONDS - 60, now - 60]))
    aged = pool.ProviderHealth("chatgpt")
    record("a time older than the window is dropped on the way in", aged.images_in_window() == 1,
           str(aged.images_in_window()))
    aged.pacing["image_budget"] = 1
    record("a budget spent before the restart still holds the next job back", aged.hold_seconds() > 3600,
           "{:.0f}s".format(aged.hold_seconds()))

    aged.note(GenerationResult.failure("a failed turn", kind="provider_error"), 1.0)
    record("a failed turn is not a picture", len(json.loads(budget.read_text())) == 2)

    print("{}/{} PASSED".format(sum(CHECKS), len(CHECKS)))
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
