"""Provider price table, peak windows, and cost estimates.

Prices rot. DeepSeek alone changed its billing three times in eighteen months
(off-peak discounts in Feb 2025, removed Sep 2025, peak/off-peak split in
Aug 2026), so nothing here is treated as permanent truth:

* The numbers live in ``config.json`` (seeded from ``DEFAULT_PRICING``) and are
  editable from Settings, so a price change does not need a release.
* Peak windows are data too, never an ``if hour in (...)`` in code.
* Routing decisions rank providers by ``tier`` — a relative label that survives
  price changes. Absolute rates only refine that ranking and only when fresh.
* Anything shown to the user is an estimate, labelled with ``updated_at``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

# Relative cost buckets. Routing uses these; they stay correct even when the
# per-token rates are months out of date.
TIERS = ("free", "cheap", "mid", "premium")
_TIER_RANK = {name: i for i, name in enumerate(TIERS)}

# Price table older than this is no longer trusted for routing.
STALE_AFTER_DAYS = 90

# Seed only — copied into config on first read, then owned by the user.
# Rates are USD per 1M tokens, quoted at the provider's standard (peak where a
# provider splits rates) price.
DEFAULT_PRICING: dict = {
    "updated_at": "2026-08-16",
    "providers": {
        "local": {
            "tier": "free",
            "per_1m": {"cache_hit": 0.0, "cache_miss": 0.0, "output": 0.0},
        },
        "deepseek": {
            "tier": "cheap",
            # api-docs.deepseek.com/quick_start/pricing — off-peak is half price.
            "per_1m": {"cache_hit": 0.044, "cache_miss": 1.32, "output": 3.96},
            "peak_windows_utc": ["01:00-04:00", "06:00-10:00"],
            "peak_days": ["mon", "tue", "wed", "thu", "fri"],
            "off_peak_multiplier": 0.5,
        },
        "qwen": {
            "tier": "cheap",
            "per_1m": {"cache_hit": 0.08, "cache_miss": 0.4, "output": 1.2},
        },
        "glm": {
            "tier": "cheap",
            "per_1m": {"cache_hit": 0.11, "cache_miss": 0.6, "output": 2.2},
        },
        "gemini": {
            "tier": "mid",
            "per_1m": {"cache_hit": 0.08, "cache_miss": 0.3, "output": 2.5},
        },
        "grok": {
            "tier": "mid",
            "per_1m": {"cache_hit": 0.75, "cache_miss": 3.0, "output": 15.0},
        },
        "openai": {
            "tier": "premium",
            "per_1m": {"cache_hit": 0.125, "cache_miss": 1.25, "output": 10.0},
        },
    },
}

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _table(cfg: dict | None) -> dict:
    raw = (cfg or {}).get("pricing")
    return raw if isinstance(raw, dict) else DEFAULT_PRICING


def updated_at(cfg: dict | None) -> str:
    return str(_table(cfg).get("updated_at") or "").strip()


def is_stale(cfg: dict | None, *, now: float | None = None) -> bool:
    """True when the table is too old to steer routing (still fine to display)."""
    stamp = updated_at(cfg)
    if not stamp:
        return True
    try:
        when = datetime.strptime(stamp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    age_days = ((now or time.time()) - when.timestamp()) / 86400
    return age_days > STALE_AFTER_DAYS


def provider_pricing(provider: dict | None, cfg: dict | None = None) -> dict:
    """Price entry for a provider — per-provider override beats the type table."""
    if not isinstance(provider, dict):
        return {}
    own = provider.get("pricing")
    if isinstance(own, dict) and own:
        return own
    by_type = _table(cfg).get("providers") or {}
    entry = by_type.get(str(provider.get("type") or "").strip().lower())
    return entry if isinstance(entry, dict) else {}


def tier(provider: dict | None, cfg: dict | None = None) -> str:
    entry = provider_pricing(provider, cfg)
    name = str(entry.get("tier") or "").strip().lower()
    return name if name in _TIER_RANK else "mid"


def tier_rank(provider: dict | None, cfg: dict | None = None) -> int:
    """Cheapest first — the ordering routing relies on."""
    return _TIER_RANK.get(tier(provider, cfg), _TIER_RANK["mid"])


def _parse_hhmm(value: str) -> int | None:
    try:
        hh, mm = str(value).strip().split(":")
        minutes = int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None
    return minutes if 0 <= minutes <= 24 * 60 else None


def _in_window(minute_of_day: int, window: str) -> bool:
    parts = str(window or "").split("-")
    if len(parts) != 2:
        return False
    start, end = _parse_hhmm(parts[0]), _parse_hhmm(parts[1])
    if start is None or end is None:
        return False
    if start <= end:
        return start <= minute_of_day < end
    # Window wraps midnight (e.g. 16:30-00:30).
    return minute_of_day >= start or minute_of_day < end


def is_peak(provider: dict | None, cfg: dict | None = None, *, now: float | None = None) -> bool:
    """True when the provider is inside a configured peak window right now."""
    entry = provider_pricing(provider, cfg)
    windows = entry.get("peak_windows_utc") or []
    if not windows:
        return False
    moment = datetime.fromtimestamp(now if now is not None else time.time(), tz=timezone.utc)
    days = [str(d).strip().lower() for d in (entry.get("peak_days") or _DAYS)]
    if days and _DAYS[moment.weekday()] not in days:
        return False
    minute_of_day = moment.hour * 60 + moment.minute
    return any(_in_window(minute_of_day, w) for w in windows)


def effective_rates(
    provider: dict | None,
    cfg: dict | None = None,
    *,
    now: float | None = None,
) -> dict:
    """Per-1M rates with the off-peak discount applied when outside peak."""
    entry = provider_pricing(provider, cfg)
    rates = entry.get("per_1m") or {}
    out = {
        "cache_hit": float(rates.get("cache_hit") or 0.0),
        "cache_miss": float(rates.get("cache_miss") or 0.0),
        "output": float(rates.get("output") or 0.0),
    }
    if entry.get("peak_windows_utc") and not is_peak(provider, cfg, now=now):
        try:
            multiplier = float(entry.get("off_peak_multiplier") or 1.0)
        except (TypeError, ValueError):
            multiplier = 1.0
        out = {k: v * multiplier for k, v in out.items()}
    return out


def estimate_cost(
    provider: dict | None,
    usage: dict | None,
    cfg: dict | None = None,
    *,
    now: float | None = None,
) -> float:
    """Rough USD cost for one call. Display only — never billed against."""
    if not isinstance(usage, dict):
        return 0.0
    rates = effective_rates(provider, cfg, now=now)
    if not any(rates.values()):
        return 0.0

    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    hit = int(usage.get("cache_hit_tokens") or 0)
    miss = int(usage.get("cache_miss_tokens") or 0)
    if not (hit or miss):
        miss = prompt
    elif hit + miss < prompt:
        miss += prompt - (hit + miss)

    total = (
        hit * rates["cache_hit"]
        + miss * rates["cache_miss"]
        + completion * rates["output"]
    ) / 1_000_000
    return round(total, 6)


# A synthetic turn used to compare providers against each other. The absolute
# value is meaningless; only the ordering between providers matters.
_REFERENCE_TURN = {"prompt": 4000, "cached_share": 0.5, "output": 500}


def price_signal(
    provider: dict | None,
    cfg: dict | None = None,
    *,
    now: float | None = None,
) -> float | None:
    """Comparable cost for a typical turn, or None when prices can't be trusted.

    Returning None is deliberate: routing must degrade to tier ordering rather
    than pretend a stale or missing rate is accurate.
    """
    if is_stale(cfg, now=now):
        return None
    rates = effective_rates(provider, cfg, now=now)
    if not any(rates.values()):
        # A genuinely free local provider still deserves a real zero.
        return 0.0 if tier(provider, cfg) == "free" else None
    prompt = _REFERENCE_TURN["prompt"]
    hit = int(prompt * _REFERENCE_TURN["cached_share"])
    return estimate_cost(
        provider,
        {
            "prompt_tokens": prompt,
            "completion_tokens": _REFERENCE_TURN["output"],
            "cache_hit_tokens": hit,
            "cache_miss_tokens": prompt - hit,
        },
        cfg,
        now=now,
    )


def public_status(cfg: dict | None = None, *, now: float | None = None) -> dict:
    """Summary for Settings: how old the table is and who is on peak now."""
    table = _table(cfg)
    peaks = {}
    for ptype, entry in (table.get("providers") or {}).items():
        if entry.get("peak_windows_utc"):
            peaks[ptype] = is_peak({"type": ptype}, cfg, now=now)
    return {
        "updated_at": updated_at(cfg),
        "stale": is_stale(cfg, now=now),
        "stale_after_days": STALE_AFTER_DAYS,
        "on_peak": peaks,
    }
