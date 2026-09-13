"""Media library formatting + music intent priming."""

from __future__ import annotations

from services import deepseek as ds
from services import entity_tools as et
from services import ha_lifecycle_tools as hlt
from services import tool_awareness as taw


def test_format_media_search_compact():
    payload = {
        "result": [{
            "result_media": [
                {
                    "title": "Alone",
                    "artist": "Alan Walker",
                    "media_class": "track",
                    "media_content_type": "music",
                    "media_content_id": "spotify:track:abc",
                },
                {
                    "title": "Faded",
                    "media_class": "track",
                    "media_content_type": "music",
                    "media_content_id": "spotify:track:def",
                },
            ],
        }],
    }
    text = hlt.format_media_library(payload, kind="search", query="Alone")
    assert "Media search “Alone”" in text
    assert "spotify:track:abc" in text
    assert "ha_media_play" in text
    assert "Alone — Alan Walker" in text


def test_format_media_browse_children():
    payload = {
        "title": "Spotify",
        "children": [
            {
                "title": "Liked Songs",
                "media_class": "playlist",
                "media_content_type": "playlist",
                "media_content_id": "spotify:playlist:1",
            },
        ],
    }
    text = hlt.format_media_library(payload, kind="browse")
    assert "Liked Songs" in text
    assert "spotify:playlist:1" in text


def test_music_phrases_look_like_control():
    assert ds.looks_like_control("cântă Alone pe living")
    assert ds.looks_like_control("play music on the kitchen speaker")
    assert ds.looks_like_control("pune o piesă pe boxă")
    assert taw.should_skip_pack_router_for_control("cântă Alone pe living")


def test_playbook_mentions_media_search():
    text = taw.build_tool_playbook(["ha_media_search", "ha_media_play"])
    assert "ha_media_search" in text
    assert "ha_media_play" in text


def test_prompts_mention_music_flow():
    full = et.render_ha_agent_prompt("", ["ha_media_search", "ha_media_play"], compact=False)
    compact = et.render_ha_agent_prompt("", ["ha_media_search", "ha_media_play"], compact=True)
    assert "ha_media_search" in full
    assert "cântă" in full.lower() or "media_player" in full
    assert "ha_media_search" in compact or "music" in compact.lower() or "cântă" in compact.lower()
