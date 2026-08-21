import asyncio

import pytest

from routers.chat import (
    TraceCancelled,
    _activity_status_payload,
    _check_trace,
    _register_session_job,
    _sanitize_trace_id,
    _session_job_running,
    _session_jobs,
    _trace_cancel,
    _trace_cancelled,
    _trace_done,
    _trace_push,
    _trace_start,
    _traces,
)


@pytest.fixture(autouse=True)
def _clean_traces():
    _traces.clear()
    _session_jobs.clear()
    yield
    _traces.clear()
    _session_jobs.clear()


def test_trace_cancel_marks_bucket_and_blocks_repeat():
    trace_id = "abcd1234efgh5678"
    assert _sanitize_trace_id(trace_id) == trace_id
    _trace_start(trace_id)
    assert _trace_cancel(trace_id) is True
    assert _trace_cancelled(trace_id) is True
    assert _trace_cancel(trace_id) is False
    with pytest.raises(TraceCancelled):
        asyncio.run(_check_trace(trace_id))
    _trace_done(trace_id)
    assert _trace_cancel(trace_id) is False
    assert _traces[trace_id]["status"] == "cancelled"


def test_check_trace_ignores_unknown_id():
    asyncio.run(_check_trace(""))


def test_session_job_register_and_release():
    sid = "sess-abc"
    tid = "abcd1234efgh5678"
    _trace_start(tid, session_id=sid, user_id="alice")
    _register_session_job(sid, tid)
    assert _session_job_running(sid) == tid
    _trace_done(tid)
    assert _session_job_running(sid) is None
    assert sid not in _session_jobs


def test_activity_status_includes_session_and_error():
    tid = "abcd1234efgh9999"
    _trace_start(tid, session_id="s1", user_id="u1")
    _trace_push(tid, {"id": "think-0", "name": "think", "status": "running", "detail": ""})
    payload = _activity_status_payload(_traces[tid], -1)
    assert payload["status"] == "running"
    assert payload["session_id"] == "s1"
    assert len(payload["events"]) == 1
    _trace_done(tid, error="boom")
    payload = _activity_status_payload(_traces[tid], -1)
    assert payload["done"] is True
    assert payload["status"] == "error"
    assert payload["error"] == "boom"
