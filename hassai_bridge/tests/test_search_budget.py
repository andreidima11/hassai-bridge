"""Max SearXNG searches per user prompt."""

from services import searxng


def test_max_searches_default_and_clamp():
    assert searxng.max_searches_per_prompt({}) == 3
    assert searxng.max_searches_per_prompt({"searxng": {"max_searches_per_prompt": 5}}) == 5
    assert searxng.max_searches_per_prompt({"searxng": {"max_searches_per_prompt": 0}}) == 1
    assert searxng.max_searches_per_prompt({"searxng": {"max_searches_per_prompt": 99}}) == 10
    assert searxng.max_searches_per_prompt({"searxng": {"max_searches_per_prompt": "x"}}) == 3
