"""Native stock_quote / stock_history tools (Yahoo chart API via httpx)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from services import secondary_routing as sr
from services import stocks as st
from services import toolkits as tk


def test_normalize_and_parse_symbols():
    assert st.normalize_ticker("aapl") == "AAPL"
    assert st.normalize_ticker("BTC-USD") == "BTC-USD"
    assert st.normalize_ticker("^GSPC") == "^GSPC"
    assert st.normalize_ticker("!!!") == ""
    assert st.parse_symbols_arg("AAPL, tsla; BTC-USD") == ["AAPL", "TSLA", "BTC-USD"]
    assert st.parse_symbols_arg(["msft", "MSFT", "aapl"]) == ["MSFT", "AAPL"]
    assert len(st.parse_symbols_arg(",".join(f"T{i}" for i in range(20)))) == 8


def test_tools_are_core_and_secondary_web():
    assert tk.is_core_tool("stock_quote") is True
    assert tk.is_core_tool("stock_history") is True
    assert tk.pack_for_tool("stock_quote") is None
    assert sr.tool_use_for_category("stock_history") == "web_search"


def _sample_chart(*, price=100.0, prev=95.0):
    return {
        "meta": {
            "symbol": "AAPL",
            "shortName": "Apple Inc.",
            "currency": "USD",
            "regularMarketPrice": price,
            "chartPreviousClose": prev,
            "regularMarketDayHigh": 101.0,
            "regularMarketDayLow": 94.0,
            "regularMarketVolume": 1_000_000,
        },
        "timestamp": [1_700_000_000, 1_700_086_400],
        "indicators": {
            "quote": [{
                "open": [94.0, 96.0],
                "high": [98.0, 101.0],
                "low": [93.0, 94.0],
                "close": [prev, price],
                "volume": [900_000, 1_000_000],
            }],
        },
    }


def test_quote_and_history_mocked():
    async def _run():
        with patch.object(st, "_fetch_chart", new=AsyncMock(return_value=_sample_chart())):
            text = await st.quote("AAPL")
            assert "Apple Inc. (AAPL): 100 USD" in text
            assert "change +5" in text
            hist = await st.history("AAPL", period="1mo")
            assert "AAPL history" in hist
            assert "date|open|high|low|close|volume" in hist

    asyncio.run(_run())


def test_history_rejects_bad_period():
    async def _run():
        out = await st.history("AAPL", period="nope")
        assert out.startswith("Error:")

    asyncio.run(_run())


def test_invoke_stock_quote(monkeypatch):
    from routers import chat as chat_mod

    async def _fake_quote(symbols):
        return f"ok {symbols}"

    monkeypatch.setattr(chat_mod.stocks_fx, "quote", _fake_quote)
    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "stock_quote",
            {"symbols": "AAPL"},
            search_enabled=False,
        )
    )
    assert used is False
    assert "ok AAPL" in text


def test_invoke_stock_history(monkeypatch):
    from routers import chat as chat_mod

    async def _fake_history(symbol, *, period="1mo", interval="1d", start=None, end=None):
        return f"hist {symbol} {period} {interval}"

    monkeypatch.setattr(chat_mod.stocks_fx, "history", _fake_history)
    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "stock_history",
            {"symbol": "TSLA", "period": "5d"},
            search_enabled=False,
        )
    )
    assert used is False
    assert "hist TSLA 5d" in text
