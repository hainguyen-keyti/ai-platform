import threading

import httpx

from src.config import settings


class Runner(threading.Thread):
    """Pulls jobs from the API and posts results back.

    The worker holds no database handle: the API owns all state, which is what
    lets the worker sit outside Docker today and on another host later.
    """

    def __init__(self, pool):
        super().__init__(name="job-runner", daemon=True)
        self.pool = pool
        self._stop = threading.Event()
        self.processed = 0
        self.failed = 0
        self.last_error = None

    def stop(self):
        self._stop.set()

    def run(self):
        headers = {"X-Worker-Token": settings.worker_token}
        with httpx.Client(base_url=settings.api_url, headers=headers, timeout=30.0) as client:
            while not self._stop.is_set():
                job = None
                try:
                    job = self._claim(client)
                except Exception as exc:
                    self.last_error = "claim failed, {}: {}".format(type(exc).__name__, exc)

                if job is None:
                    self._stop.wait(settings.poll_interval)
                    continue

                try:
                    self._handle(client, job)
                except Exception as exc:
                    self.last_error = "handle failed, {}: {}".format(type(exc).__name__, exc)
                    self.failed += 1

    def _claim(self, client):
        response = client.post("/internal/jobs/claim")
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def _handle(self, client, job):
        result = self.pool.execute(job["provider"], job["feature"], job.get("payload") or {})
        body = {
            "status": "done" if result.success else "failed",
            "text": result.text,
            "media": [
                {"filename": m.filename, "type": m.type, "metadata": m.metadata}
                for m in result.media
            ],
            "error": result.error,
        }
        response = client.post("/internal/jobs/{}/result".format(job["id"]), json=body)
        response.raise_for_status()
        if result.success:
            self.processed += 1
        else:
            self.failed += 1
            self.last_error = result.error
