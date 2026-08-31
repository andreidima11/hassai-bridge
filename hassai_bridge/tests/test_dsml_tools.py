"""DSML tool-call recovery (DeepSeek markup leaked as text)."""

from services import dsml_tools as dsml

_SAMPLE = (
    '<｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="search_web"> '
    '<｜｜DSML｜｜parameter name="query" string="true">Romanian prime minister 2025'
    '</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke> </｜｜DSML｜｜tool_calls>'
)

_STANDARD = (
    '<｜DSML｜tool_calls>\n'
    '<｜DSML｜invoke name="search_web">\n'
    '<｜DSML｜parameter name="query" string="true">premier România</｜DSML｜parameter>\n'
    '</｜DSML｜invoke>\n'
    '</｜DSML｜tool_calls>'
)


def test_extract_doubled_separator_sample():
    cleaned, calls = dsml.extract_tool_calls(_SAMPLE)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "search_web"
    assert "Romanian prime minister 2025" in calls[0]["function"]["arguments"]
    assert "DSML" not in cleaned
    assert "search_web" not in cleaned


def test_extract_standard_dsml():
    cleaned, calls = dsml.extract_tool_calls(f"Before {_STANDARD} After")
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "search_web"
    assert "premier" in calls[0]["function"]["arguments"]
    assert cleaned == "Before  After" or "Before" in cleaned and "After" in cleaned
    assert "DSML" not in cleaned


def test_strip_without_invoke_left_over_tags():
    assert "DSML" not in dsml.strip_dsml(_SAMPLE)
    assert dsml.strip_dsml("hello") == "hello"


def test_recover_message_mutates_content():
    msg = {"role": "assistant", "content": _SAMPLE}
    calls = dsml.recover_message_tool_calls(msg)
    assert len(calls) == 1
    assert msg.get("tool_calls")
    assert "DSML" not in (msg.get("content") or "")


def test_recover_skips_when_tool_calls_already_present():
    msg = {
        "role": "assistant",
        "content": _SAMPLE,
        "tool_calls": [{
            "id": "c1",
            "type": "function",
            "function": {"name": "search_web", "arguments": '{"query":"x"}'},
        }],
    }
    calls = dsml.recover_message_tool_calls(msg)
    assert calls[0]["id"] == "c1"
    # Content still has DSML — recovery skipped; strip separately if needed.
    assert "DSML" in msg["content"]


def test_tool_call_ids_are_unique_across_extractions():
    a = dsml.extract_tool_calls(_SAMPLE)[1]
    b = dsml.extract_tool_calls(_SAMPLE)[1]
    assert a and b
    assert a[0]["id"] != b[0]["id"]
    assert a[0]["id"].startswith("dsml_")


def test_looks_like_dsml():
    assert dsml.looks_like_dsml(_SAMPLE) is True
    assert dsml.looks_like_dsml("normal answer") is False
