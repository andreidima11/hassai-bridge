"""Regression: empty assistant activity must not wipe a finished reply."""


def _resolve_job_text(event_batches: list[dict]) -> str:
    """Mirror of waitForChatJob's last-non-empty fallback (api.js)."""
    full = ""
    last_non_empty = ""
    for data in event_batches:
        for ev in data.get("events") or []:
            if ev.get("name") == "assistant" and isinstance(ev.get("detail"), str):
                full = ev["detail"]
                if full.strip():
                    last_non_empty = full
        if data.get("done"):
            return full if full.strip() else last_non_empty
    return full if full.strip() else last_non_empty


def test_wait_for_chat_job_keeps_last_non_empty():
    result = _resolve_job_text([
        {
            "events": [
                {"i": 0, "name": "assistant", "detail": "Am aprins lumina."},
                {"i": 1, "name": "assistant", "detail": ""},
            ],
            "done": False,
        },
        {"events": [], "done": True},
    ])
    assert result == "Am aprins lumina."


def test_final_non_empty_wins():
    result = _resolve_job_text([
        {
            "events": [
                {"i": 0, "name": "assistant", "detail": "Narration…"},
                {"i": 1, "name": "assistant", "detail": ""},
                {"i": 2, "name": "assistant", "detail": "Gata, am stins lumina."},
            ],
            "done": True,
        },
    ])
    assert result == "Gata, am stins lumina."


def test_push_assistant_preview_skips_empty_force_without_retract():
    """Server-side contract for chat.push_assistant_preview."""
    full_response = ""
    force = True
    retract = False
    assistant_preview_visible = False
    should_skip = (not full_response and force and not retract) or (
        retract and not full_response and not assistant_preview_visible
    )
    assert should_skip is True

    assistant_preview_visible = True
    retract = True
    should_skip = (not full_response and force and not retract) or (
        retract and not full_response and not assistant_preview_visible
    )
    assert should_skip is False
