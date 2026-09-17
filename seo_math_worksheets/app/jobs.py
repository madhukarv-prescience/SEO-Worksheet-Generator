"""
Background generation jobs.

One worksheet takes a few seconds. Twenty sources at three versions each
is a couple of hundred API calls — far past what a browser request will
wait for, and past what anyone should stare at a spinner for.

So bulk runs happen on a worker thread and the page polls for progress.
Batches are written to the database as each source finishes, which means
the Review screen fills in progressively instead of staying empty until
the whole run completes.

State lives in memory on purpose: a job is only meaningful while the
server that started it is up. If it restarts mid-run, whatever finished
is already saved in the database — only the progress bar is lost.
"""
from __future__ import annotations

import threading
import time
import uuid

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()

# A cap, not a limit of the machinery. Someone selecting "everything" with
# 700 sources in the library would otherwise start a run costing real money
# and taking hours, with no obvious way to tell it stopped.
MAX_SOURCES_PER_RUN = 25


def running_job() -> dict | None:
    """The bulk run currently in flight, if any.

    Two concurrent runs share one API rate limit and starve each other —
    the first real bulk test lost 10 variants to "the question writer is
    busy" purely because two jobs were racing. One at a time.
    """
    with _LOCK:
        for job in _JOBS.values():
            if job["status"] == "running":
                return dict(job)
    return None


def create(total: int, label: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "label": label,
            "total": total,
            "done": 0,
            "made": 0,
            "failed": [],
            "batch_ids": [],
            "status": "running",
            "current": "",
            "started_at": time.time(),
        }
    return job_id


def update(job_id: str, **fields) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(fields)


def step(job_id: str, batch_id: str | None, made: int,
          failed: str | None = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["done"] += 1
        job["made"] += made
        if batch_id:
            job["batch_ids"].append(batch_id)
        if failed:
            job["failed"].append(failed)


def finish(job_id: str, status: str = "done") -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["status"] = status
            job["current"] = ""
            job["finished_at"] = time.time()


def get(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def prune(max_age_seconds: int = 3600) -> None:
    """Drop finished jobs so the dict can't grow without bound."""
    cutoff = time.time() - max_age_seconds
    with _LOCK:
        for jid in [j for j, v in _JOBS.items()
                     if v.get("finished_at", 1e18) < cutoff]:
            _JOBS.pop(jid, None)
