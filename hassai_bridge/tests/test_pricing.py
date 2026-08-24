"""Price table: peak windows, staleness, tiers, cost estimates."""

from __future__ import annotations

from datetime import datetime, timezone

from services import pricing


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


FRESH = {"pricing": {**pricing.DEFAULT_PRICING, "updated_at": "2026-08-16"}}


def test_deepseek_peak_windows_follow_the_published_schedule():
    ds = {"type": "deepseek"}
    # Monday 02:00 UTC — inside 01:00-04:00.
    assert pricing.is_peak(ds, FRESH, now=_ts("2026-08-17T02:00:00"))
    # Monday 04:00 UTC — the boundary is off-peak.
    assert not pricing.is_peak(ds, FRESH, now=_ts("2026-08-17T04:00:00"))
    # Monday 06:30 UTC — inside 06:00-10:00.
    assert pricing.is_peak(ds, FRESH, now=_ts("2026-08-17T06:30:00"))
    # Monday 10:00 UTC — off-peak again.
    assert not pricing.is_peak(ds, FRESH, now=_ts("2026-08-17T10:00:00"))


def test_deepseek_weekend_is_never_peak():
    ds = {"type": "deepseek"}
    # Saturday 02:00 UTC — inside the window but outside peak days.
    assert not pricing.is_peak(ds, FRESH, now=_ts("2026-08-22T02:00:00"))


def test_off_peak_halves_the_rates():
    ds = {"type": "deepseek"}
    peak = pricing.effective_rates(ds, FRESH, now=_ts("2026-08-17T02:00:00"))
    off = pricing.effective_rates(ds, FRESH, now=_ts("2026-08-17T12:00:00"))
    assert off["output"] == peak["output"] * 0.5
    assert off["cache_miss"] == peak["cache_miss"] * 0.5


def test_providers_without_peak_windows_are_flat():
    openai = {"type": "openai"}
    a = pricing.effective_rates(openai, FRESH, now=_ts("2026-08-17T02:00:00"))
    b = pricing.effective_rates(openai, FRESH, now=_ts("2026-08-17T12:00:00"))
    assert a == b
    assert not pricing.is_peak(openai, FRESH, now=_ts("2026-08-17T02:00:00"))


def test_wrapping_window_crosses_midnight():
    provider = {
        "type": "custom",
        "pricing": {
            "tier": "cheap",
            "per_1m": {"cache_hit": 1.0, "cache_miss": 1.0, "output": 1.0},
            "peak_windows_utc": ["16:30-00:30"],
            "off_peak_multiplier": 0.5,
        },
    }
    assert pricing.is_peak(provider, FRESH, now=_ts("2026-08-17T23:00:00"))
    assert pricing.is_peak(provider, FRESH, now=_ts("2026-08-17T00:10:00"))
    assert not pricing.is_peak(provider, FRESH, now=_ts("2026-08-17T12:00:00"))


def test_cache_hits_dominate_the_cost_estimate():
    ds = {"type": "deepseek"}
    now = _ts("2026-08-17T12:00:00")
    cached = pricing.estimate_cost(
        ds,
        {"prompt_tokens": 10000, "completion_tokens": 0,
         "cache_hit_tokens": 10000, "cache_miss_tokens": 0},
        FRESH, now=now,
    )
    uncached = pricing.estimate_cost(
        ds,
        {"prompt_tokens": 10000, "completion_tokens": 0,
         "cache_hit_tokens": 0, "cache_miss_tokens": 10000},
        FRESH, now=now,
    )
    # The published spread is 30x — far bigger than the 2x peak spread.
    assert uncached > cached * 20


def test_missing_cache_split_counts_the_prompt_as_a_miss():
    ds = {"type": "deepseek"}
    now = _ts("2026-08-17T12:00:00")
    cost = pricing.estimate_cost(ds, {"prompt_tokens": 1000, "completion_tokens": 0}, FRESH, now=now)
    rates = pricing.effective_rates(ds, FRESH, now=now)
    assert cost == round(1000 * rates["cache_miss"] / 1_000_000, 6)


def test_stale_table_disables_price_signal_but_not_tiers():
    stale = {"pricing": {**pricing.DEFAULT_PRICING, "updated_at": "2020-01-01"}}
    ds = {"type": "deepseek"}
    assert pricing.is_stale(stale)
    assert pricing.price_signal(ds, stale) is None
    # Tier ordering survives — that is what routing falls back to.
    assert pricing.tier_rank(ds, stale) < pricing.tier_rank({"type": "openai"}, stale)


def test_unparseable_or_missing_date_counts_as_stale():
    assert pricing.is_stale({"pricing": {"updated_at": "not-a-date"}})
    assert pricing.is_stale({"pricing": {}})


def test_per_provider_override_wins_over_type_table():
    provider = {"type": "deepseek", "pricing": {"tier": "premium", "per_1m": {"output": 99.0}}}
    assert pricing.tier(provider, FRESH) == "premium"
    assert pricing.effective_rates(provider, FRESH)["output"] == 99.0


def test_local_provider_is_free_and_comparable():
    local = {"type": "local"}
    assert pricing.tier(local, FRESH) == "free"
    assert pricing.price_signal(local, FRESH, now=_ts("2026-08-17T12:00:00")) == 0.0
