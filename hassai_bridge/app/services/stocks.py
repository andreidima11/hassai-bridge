"""Stock / market quotes via Yahoo Finance chart API (httpx).

No API key and no yfinance — Alpine add-on images cannot reliably install
pandas/curl_cffi. Prefer these tools over web search for ticker prices.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger("hassai.stocks")

_TICKER_RE = re.compile(r"^[A-Za-z0-9.^_=/-]{1,24}$")
_MAX_QUOTES = 8
_MAX_HISTORY_ROWS = 30
_VALID_PERIODS = frozenset({
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max",
})
_VALID_INTERVALS = frozenset({
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo",
})

_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HASSAI-Bridge/1.0)",
    "Accept": "application/json",
}


def normalize_ticker(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not s or not _TICKER_RE.match(s):
        return ""
    return s


def parse_symbols_arg(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[,;\s]+", str(raw).strip())
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        t = normalize_ticker(p)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= _MAX_QUOTES:
            break
    return out


def _fmt_price(n: float | None) -> str:
    if n is None:
        return "?"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "?"
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _fmt_pct(n: float | None) -> str:
    if n is None:
        return ""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _fmt_cap(n: float | None) -> str:
    if n is None:
        return ""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    if v >= 1e12:
        return f"{v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{v / 1e6:.2f}M"
    return f"{v:,.0f}"


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


async def _fetch_chart(
    symbol: str,
    *,
    interval: str = "1d",
    range_: str | None = "5d",
    period1: int | None = None,
    period2: int | None = None,
) -> dict[str, Any]:
    enc = quote(symbol, safe="")
    params: dict[str, str] = {
        "interval": interval,
        "includePrePost": "false",
        "events": "div,splits",
    }
    if period1 is not None:
        params["period1"] = str(int(period1))
        params["period2"] = str(int(period2 or datetime.now(tz=timezone.utc).timestamp()))
    else:
        params["range"] = range_ or "5d"

    urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}",
        f"https://query2.finance.yahoo.com/v8/finance/chart/{enc}",
    ]
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        for url in urls:
            try:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    last_err = RuntimeError(f"HTTP {resp.status_code}")
                    continue
                data = resp.json()
                chart = (data or {}).get("chart") or {}
                err = chart.get("error")
                if err:
                    last_err = RuntimeError(str(err.get("description") or err))
                    continue
                results = chart.get("result")
                if not isinstance(results, list) or not results:
                    last_err = RuntimeError("empty chart result")
                    continue
                row = results[0]
                if not isinstance(row, dict):
                    last_err = RuntimeError("bad chart result")
                    continue
                return row
            except Exception as e:
                last_err = e
                log.debug("yahoo chart failed %s %s: %s", symbol, url, e)
                continue
    raise RuntimeError(f"Yahoo Finance unavailable for {symbol}: {last_err}")


def _bars_from_chart(row: dict[str, Any]) -> list[dict[str, Any]]:
    timestamps = row.get("timestamp") or []
    indicators = row.get("indicators") or {}
    quotes = (indicators.get("quote") or [{}])[0] or {}
    opens = quotes.get("open") or []
    highs = quotes.get("high") or []
    lows = quotes.get("low") or []
    closes = quotes.get("close") or []
    volumes = quotes.get("volume") or []
    out: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        close = _num(closes[i] if i < len(closes) else None)
        if close is None:
            continue
        try:
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
        except Exception:
            d = str(ts)
        out.append({
            "date": d,
            "open": _num(opens[i] if i < len(opens) else None),
            "high": _num(highs[i] if i < len(highs) else None),
            "low": _num(lows[i] if i < len(lows) else None),
            "close": close,
            "volume": _num(volumes[i] if i < len(volumes) else None),
        })
    return out


async def _quote_one(symbol: str) -> str:
    try:
        row = await _fetch_chart(symbol, interval="1d", range_="5d")
    except Exception as e:
        return f"Error: could not load quote for '{symbol}': {e}"

    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    bars = _bars_from_chart(row)
    name = str(meta.get("shortName") or meta.get("longName") or symbol)
    currency = str(meta.get("currency") or "")
    price = _num(meta.get("regularMarketPrice") or meta.get("currentTradingPeriod"))
    if price is None and bars:
        price = bars[-1]["close"]
    prev = _num(meta.get("chartPreviousClose") or meta.get("previousClose"))
    if prev is None and len(bars) >= 2:
        prev = bars[-2]["close"]
    day_high = _num(meta.get("regularMarketDayHigh"))
    day_low = _num(meta.get("regularMarketDayLow"))
    if day_high is None and bars:
        day_high = bars[-1].get("high")
    if day_low is None and bars:
        day_low = bars[-1].get("low")
    volume = _num(meta.get("regularMarketVolume"))
    if volume is None and bars:
        volume = bars[-1].get("volume")
    market_cap = _num(meta.get("marketCap"))

    if price is None:
        return f"Error: no quote data for '{symbol}'."

    change = None
    change_pct = None
    if prev is not None and prev:
        change = price - prev
        change_pct = (change / prev) * 100.0

    cur = f" {currency}" if currency else ""
    parts = [f"{name} ({symbol}): {_fmt_price(price)}{cur}"]
    if change is not None:
        sign = "+" if change >= 0 else ""
        pct = _fmt_pct(change_pct)
        parts.append(f"change {sign}{_fmt_price(change)}" + (f" ({pct})" if pct else ""))
    if day_low is not None and day_high is not None:
        parts.append(f"day {_fmt_price(day_low)}–{_fmt_price(day_high)}")
    if volume is not None:
        try:
            parts.append(f"vol {int(volume):,}")
        except (TypeError, ValueError):
            pass
    cap = _fmt_cap(market_cap)
    if cap:
        parts.append(f"mkt cap {cap}{cur}")
    return " | ".join(parts)


async def _history_one(
    symbol: str,
    *,
    period: str,
    interval: str,
    start: str | None,
    end: str | None,
) -> str:
    kwargs: dict[str, Any] = {"interval": interval}
    if start:
        try:
            p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return "Error: start must be YYYY-MM-DD."
        p2 = int(datetime.now(tz=timezone.utc).timestamp())
        if end:
            try:
                p2 = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                return "Error: end must be YYYY-MM-DD."
        kwargs["period1"] = p1
        kwargs["period2"] = p2
        kwargs["range_"] = None
        label = f"{start}" + (f"→{end}" if end else "→now")
    else:
        kwargs["range_"] = period
        label = period

    try:
        row = await _fetch_chart(symbol, **kwargs)
    except Exception as e:
        return f"Error: could not load history for {symbol}: {e}"

    bars = _bars_from_chart(row)
    if not bars:
        return f"Error: no history for '{symbol}' ({label})."

    shown = bars[-_MAX_HISTORY_ROWS:]
    lines = [
        f"{symbol} history interval={interval} ({label}, {len(shown)} bars):",
        "date|open|high|low|close|volume",
    ]
    for b in shown:
        vol = b.get("volume")
        try:
            vol_s = f"{int(vol):,}" if vol is not None else ""
        except (TypeError, ValueError):
            vol_s = ""
        lines.append(
            f"{b['date']}|{_fmt_price(b.get('open'))}|{_fmt_price(b.get('high'))}|"
            f"{_fmt_price(b.get('low'))}|{_fmt_price(b.get('close'))}|{vol_s}"
        )
    if len(bars) > _MAX_HISTORY_ROWS:
        lines.append(f"… showing last {_MAX_HISTORY_ROWS} of {len(bars)} bars")
    return "\n".join(lines)


async def quote(symbols: list[str] | str | None) -> str:
    tickers = parse_symbols_arg(symbols)
    if not tickers:
        return "Error: need at least one ticker (e.g. AAPL, TSLA, BTC-USD)."
    parts = await asyncio.gather(*[_quote_one(t) for t in tickers])
    return "\n".join(parts)


async def history(
    symbol: str,
    *,
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> str:
    ticker = normalize_ticker(symbol)
    if not ticker:
        return "Error: need a valid ticker (e.g. AAPL)."

    start_s = (start or "").strip() or None
    end_s = (end or "").strip() or None
    if start_s:
        try:
            date.fromisoformat(start_s)
        except ValueError:
            return "Error: start must be YYYY-MM-DD."
        if end_s:
            try:
                date.fromisoformat(end_s)
            except ValueError:
                return "Error: end must be YYYY-MM-DD."
        period_s = ""
    else:
        period_s = (period or "1mo").strip().lower() or "1mo"
        if period_s not in _VALID_PERIODS:
            return (
                f"Error: period must be one of {', '.join(sorted(_VALID_PERIODS))}."
            )

    interval_s = (interval or "1d").strip().lower() or "1d"
    if interval_s not in _VALID_INTERVALS:
        return f"Error: interval must be one of {', '.join(sorted(_VALID_INTERVALS))}."

    return await _history_one(
        ticker,
        period=period_s or "1mo",
        interval=interval_s,
        start=start_s,
        end=end_s,
    )


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "stock_quote",
            "description": (
                "Get live/last market quotes from Yahoo Finance for one or more tickers "
                "(stocks, ETFs, indices, crypto pairs like BTC-USD). "
                "Prefer this over web search for prices. Examples: AAPL, TSLA, ^GSPC, EURUSD=X."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "string",
                        "description": (
                            "Comma-separated tickers (max 8), e.g. 'AAPL,MSFT' or 'BTC-USD'."
                        ),
                    },
                },
                "required": ["symbols"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_history",
            "description": (
                "OHLCV history for one Yahoo Finance ticker. "
                "Use for 'how did AAPL do this month' / charts / trend questions. "
                "Prefer this over web search for historical prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol (e.g. AAPL).",
                    },
                    "period": {
                        "type": "string",
                        "description": (
                            "Lookback when start is omitted: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max. "
                            "Default 1mo."
                        ),
                    },
                    "interval": {
                        "type": "string",
                        "description": "Bar size: 1d (default), 1h, 1wk, …",
                    },
                    "start": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD (overrides period).",
                    },
                    "end": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD end date with start.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
]

TOOL_NAMES = frozenset({"stock_quote", "stock_history"})
