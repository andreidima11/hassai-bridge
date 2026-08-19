import asyncio

import pytest

from routers.chat import (
    TraceCancelled,
    _check_trace,
    _sanitize_trace_id,
    _trace_cancel,
    _trace_cancelled,
    _trace_done,
    _trace_start,
)


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


def test_check_trace_ignores_unknown_id():
    asyncio.run(_check_trace(""))
