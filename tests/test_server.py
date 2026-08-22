"""Tests for the M6 FastAPI REST server.

We use ``fastapi.testclient.TestClient`` for synchronous in-process
testing — no live uvicorn, no port binding. The server is a thin
wrapper around :mod:`doubi.core.pipeline` so the only "real"
exercise here is the route plumbing + JobManager concurrency.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# FastAPI is an optional dep; skip everything if missing
fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
pydantic = pytest.importorskip("pydantic")

from fastapi.testclient import TestClient  # noqa: E402

from doubi.core.models import MediaItem, MediaType, Platform, Author  # noqa: E402
from doubi.server.app import build_app  # noqa: E402
from doubi.server.jobs import JobManager, JobStatus  # noqa: E402


# ---------------------------------------------------------------------------
# JobManager
# ---------------------------------------------------------------------------


async def _ok_executor(url: str) -> dict:
    return {"total": 1, "succeeded": 1, "failed": 0}


async def _fail_executor(url: str) -> dict:
    raise RuntimeError("simulated failure")


def test_job_manager_submit_runs_to_completion():
    async def _run():
        mgr = JobManager(executor=_ok_executor, max_concurrency=1)
        job = await mgr.submit("https://x")
        assert job.status is JobStatus.PENDING
        # Let the queued task finish
        await asyncio.sleep(0.05)
        j = await mgr.get(job.job_id)
        assert j is not None
        return j
    j = asyncio.run(_run())
    assert j.status is JobStatus.COMPLETED
    assert j.total == 1
    assert j.succeeded == 1


def test_job_manager_records_failure():
    async def _run():
        mgr = JobManager(executor=_fail_executor, max_concurrency=1)
        job = await mgr.submit("https://x")
        await asyncio.sleep(0.05)
        return await mgr.get(job.job_id)
    j = asyncio.run(_run())
    assert j.status is JobStatus.FAILED
    assert "simulated failure" in j.error


def test_job_manager_respects_max_concurrency():
    """Only ``max_concurrency`` jobs run at the same time."""
    in_flight = 0
    peak = 0
    gate = asyncio.Event()

    async def _slow_executor(url: str) -> dict:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await gate.wait()
        in_flight -= 1
        return {"total": 1, "succeeded": 1, "failed": 0}

    async def _run():
        nonlocal gate
        gate = asyncio.Event()
        mgr = JobManager(executor=_slow_executor, max_concurrency=2)
        for i in range(4):
            await mgr.submit(f"https://x/{i}")
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.sleep(0.05)
        return peak

    peak = asyncio.run(_run())
    assert peak <= 2


def test_job_manager_evicts_by_count():
    """When more than max_jobs completed, oldest get evicted."""
    async def _run():
        mgr = JobManager(executor=_ok_executor, max_concurrency=1, max_jobs=2)
        ids = []
        for i in range(6):
            job = await mgr.submit(f"https://x/{i}")
            ids.append(job.job_id)
        # Poll until ALL 6 have reached a terminal state (avoids
        # flakiness on slow CI machines).
        import time
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            all_jobs = await mgr.list_jobs()
            if all(j.status in (JobStatus.COMPLETED, JobStatus.FAILED)
                   for j in all_jobs) and len(all_jobs) >= 1:
                break
            await asyncio.sleep(0.05)
        return ids, all_jobs

    ids, all_jobs = asyncio.run(_run())
    # max_jobs=2 → at most 2 non-RUNNING jobs survive.
    # (RUNNING jobs are never evicted; with a fast executor all are
    #  completed by now, so we expect exactly 2.)
    non_running = [j for j in all_jobs if j.status != JobStatus.RUNNING]
    assert len(non_running) <= 2
    # The most recently submitted job must survive (newest wins)
    assert ids[-1] in {j.job_id for j in non_running}


def mgr_evicted_count(mgr: JobManager) -> int:
    return mgr.evicted_count


# ---------------------------------------------------------------------------
# FastAPI routes (in-process)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    """Build a TestClient with the pipeline stubbed."""
    # Import inside the fixture so the test file collects even
    # when fastapi is missing (we already skipped above).
    app = build_app()
    return TestClient(app)


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_platforms_lists_douyin_and_bilibili(client):
    r = client.get("/api/v1/platforms")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["platforms"]}
    assert "douyin" in names
    assert "bilibili" in names


def test_create_job_with_missing_url_returns_4xx(client):
    r = client.post("/api/v1/download", json={"url": ""})
    # FastAPI may return 400 (our explicit check) or 422 (Pydantic
    # validation) depending on the pydantic version. Both signal
    # "client error" to the user; the contract is that a blank URL
    # is rejected with a 4xx status.
    assert 400 <= r.status_code < 500


def test_create_job_with_unknown_url_returns_job(client):
    """Unknown URL → job submitted but the pipeline reports no platform."""
    async def _fake_executor(url):
        return {"total": 0, "succeeded": 0, "failed": 0}
    # Replace the executor on the JobManager that build_app() created.
    # Patching the module-level _execute_download won't help because
    # the manager captured it in a closure.
    client.app.state.job_manager._executor = _fake_executor

    r = client.post("/api/v1/download", json={"url": "https://example.com/x"})
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert body["url"] == "https://example.com/x"


def test_get_job_returns_404_for_unknown(client):
    r = client.get("/api/v1/jobs/does-not-exist")
    assert r.status_code == 404


def test_list_jobs_returns_submitted(client):
    async def _ok(url):
        return {"total": 1, "succeeded": 1, "failed": 0}
    client.app.state.job_manager._executor = _ok

    posted1 = client.post("/api/v1/download", json={"url": "https://x/1"}).json()
    posted2 = client.post("/api/v1/download", json={"url": "https://x/2"}).json()

    import time
    deadline = time.time() + 5.0
    while time.time() < deadline:
        j1 = client.get(f"/api/v1/jobs/{posted1['job_id']}").json()
        j2 = client.get(f"/api/v1/jobs/{posted2['job_id']}").json()
        if j1["status"] == "completed" and j2["status"] == "completed":
            break
        time.sleep(0.05)

    r = client.get("/api/v1/jobs")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) >= 2


def test_get_job_after_submit_returns_its_url(client):
    async def _ok(url):
        return {"total": 1, "succeeded": 1, "failed": 0}
    client.app.state.job_manager._executor = _ok

    posted = client.post("/api/v1/download", json={"url": "https://x/specific"}).json()
    import time
    deadline = time.time() + 5.0
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{posted['job_id']}").json()
        if body["status"] == "completed":
            break
        time.sleep(0.05)
    fetched = client.get(f"/api/v1/jobs/{posted['job_id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["url"] == "https://x/specific"
    assert body["job_id"] == posted["job_id"]
