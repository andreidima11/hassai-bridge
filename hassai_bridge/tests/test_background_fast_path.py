"""Regression: reflex/slash replies must finish the background activity poll."""

from routers import chat as chat_router


def test_complete_background_fast_path_marks_trace_done():
    tid = "fastpath-test-trace"
    chat_router._traces.pop(tid, None)

    resp = chat_router._complete_background_fast_path(
        trace_id=tid,
        session_id="sess-1",
        user_id="user-1",
        model="hassai-bridge",
        content="Am stins lampa din living.",
        followups=[{
            "id": "undo_1",
            "label": "Anulează",
            "prompt": "/undo 1",
            "topic": "undo",
        }],
        provider_name="hassai-reflex",
    )

    assert resp.status_code == 202
    body = resp.body
    assert b"hassai.chat.job" in body

    payload = chat_router._activity_status_payload(chat_router._traces.get(tid), -1)
    assert payload["done"] is True
    assert payload["status"] == "done"
    names = [ev.get("name") for ev in payload["events"]]
    assert "assistant" in names
    assert "followups" in names
    assistant = next(ev for ev in payload["events"] if ev.get("name") == "assistant")
    assert "Am stins lampa" in assistant.get("detail", "")

    chat_router._traces.pop(tid, None)


def test_complete_background_fast_path_without_trace_returns_completion():
    resp = chat_router._complete_background_fast_path(
        trace_id="",
        session_id=None,
        user_id="user-1",
        model="hassai-bridge",
        content="ok",
    )
    assert resp.status_code == 200
    assert b"chat.completion" in resp.body
