"""Stock / market quotes via yfinance (Yahoo Finance unofficial API).

No API key. Prefer these tools over web search for ticker prices.
https://github.com/ranaroussi/yfinance
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any

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


def _quote_one_sync(symbol: str) -> str:
    try:
        import yfinance as yf
    except ImportError:
        return "Error: yfinance is not installed."

    ticker = yf.Ticker(symbol)
    name = symbol
    currency = ""
    price = None
    prev = None
    change = None
    change_pct = None
    day_high = None
    day_low = None
    volume = None
    market_cap = None

    try:
        fi = ticker.fast_info
        # fast_info may be object or dict depending on yfinance version
        def _get(key: str):
            if fi is None:
                return None
            if isinstance(fi, dict):
                return fi.get(key)
            return getattr(fi, key, None)

        price = _get("last_price") or _get("lastPrice") or _get("regular_market_price")
        prev = _get("previous_close") or _get("previousClose")
        currency = str(_get("currency") or "") or ""
        day_high = _get("day_high") or _get("dayHigh")
        day_low = _get("day_low") or _get("dayLow")
        volume = _get("last_volume") or _get("lastVolume") or _get("three_month_average_volume")
        market_cap = _get("market_cap") or _get("marketCap")
    except Exception as e:
        log.debug("fast_info failed for %s: %s", symbol, e)

    if price is None:
        try:
            hist = ticker.history(period="5d", interval="1d", auto_adjust=True)
            if hist is not None and not hist.empty:
                last = hist.iloc[-1]
                price = float(last.get("Close"))
                if len(hist) >= 2:
                    prev = float(hist.iloc[-2].get("Close"))
                day_high = float(last.get("High")) if last.get("High") == last.get("High") else day_high
                day_low = float(last.get("Low")) if last.get("Low") == last.get("Low") else day_low
                vol = last.get("Volume")
                if vol == vol:  # not NaN
                    volume = int(vol)
        except Exception as e:
            log.debug("history fallback failed for %s: %s", symbol, e)

    if price is None or (name == symbol and not currency):
        try:
            info = ticker.info or {}
            if isinstance(info, dict) and info:
                name = str(info.get("shortName") or info.get("longName") or symbol)
                currency = currency or str(info.get("currency") or "")
                if price is None:
                    price = (
                        info.get("currentPrice")
                        or info.get("regularMarketPrice")
                        or info.get("previousClose")
                    )
                if prev is None:
                    prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
                if change is None:
                    change = info.get("regularMarketChange")
                if change_pct is None:
                    change_pct = info.get("regularMarketChangePercent")
                day_high = day_high or info.get("dayHigh")
                day_low = day_low or info.get("dayLow")
                volume = volume or info.get("regularMarketVolume")
                market_cap = market_cap or info.get("marketCap")
        except Exception as e:
            log.debug("info fallback failed for %s: %s", symbol, e)

    if price is None:
        return f"Error: no quote data for '{symbol}'."

    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return f"Error: no quote data for '{symbol}'."

    if change is None and prev is not None:
        try:
            prev_f = float(prev)
            change = price_f - prev_f
            if prev_f:
                change_pct = (change / prev_f) * 100.0
        except (TypeError, ValueError):
            pass

    cur = f" {currency}" if currency else ""
    parts = [f"{name} ({symbol}): {_fmt_price(price_f)}{cur}"]
    if change is not None:
        try:
            ch = float(change)
            sign = "+" if ch >= 0 else ""
            pct = _fmt_pct(change_pct)
            parts.append(f"change {sign}{_fmt_price(ch)}" + (f" ({pct})" if pct else ""))
        except (TypeError, ValueError):
            pass
    if day_low is not None and day_high is not None:
        parts.append(f"day {_fmt_price(float(day_low))}–{_fmt_price(float(day_high))}")
    if volume is not None:
        try:
            parts.append(f"vol {int(volume):,}")
        except (TypeError, ValueError):
            pass
    cap = _fmt_cap(float(market_cap) if market_cap is not None else None)
    if cap:
        parts.append(f"mkt cap {cap}{cur}")
    return " | ".join(parts)


def _history_sync(
    symbol: str,
    *,
    period: str,
    interval: str,
    start: str | None,
    end: str | None,
) -> str:
    try:
        import yfinance as yf
    except ImportError:
        return "Error: yfinance is not installed."

    ticker = yf.Ticker(symbol)
    kwargs: dict[str, Any] = {"interval": interval, "auto_adjust": True}
    if start:
        kwargs["start"] = start
        if end:
            kwargs["end"] = end
    else:
        kwargs["period"] = period

    try:
        hist = ticker.history(**kwargs)
    except Exception as e:
        return f"Error: could not load history for {symbol}: {e}"

    if hist is None or hist.empty:
        return f"Error: no history for '{symbol}' ({period or start})."

    rows = hist.tail(_MAX_HISTORY_ROWS)
    lines = [
        f"{symbol} history interval={interval} "
        f"({start or period}" + (f"→{end}" if end else "") + f", {len(rows)} bars):",
        "date|open|high|low|close|volume",
    ]
    for idx, row in rows.iterrows():
        try:
            if hasattr(idx, "date"):
                d = idx.date().isoformat()
            else:
                d = str(idx)[:10]
        except Exception:
            d = str(idx)[:10]
        vol = row.get("Volume")
        try:
            vol_s = f"{int(vol):,}" if vol == vol else ""
        except (TypeError, ValueError):
            vol_s = ""
        lines.append(
            f"{d}|{_fmt_price(float(row.get('Open')))}|{_fmt_price(float(row.get('High')))}|"
            f"{_fmt_price(float(row.get('Low')))}|{_fmt_price(float(row.get('Close')))}|{vol_s}"
        )
    if len(hist) > _MAX_HISTORY_ROWS:
        lines.append(f"… showing last {_MAX_HISTORY_ROWS} of {len(hist)} bars")
    return "\n".join(lines)


async def quote(symbols: list[str] | str | None) -> str:
    tickers = parse_symbols_arg(symbols)
    if not tickers:
        return "Error: need at least one ticker (e.g. AAPL, TSLA, BTC-USD)."
    parts = await asyncio.gather(*[
        asyncio.to_thread(_quote_one_sync, t) for t in tickers
    ])
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

    return await asyncio.to_thread(
        _history_sync,
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
