"""Native stock_quote / stock_history tools (yfinance)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

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


def test_quote_and_history_mocked():
    async def _run():
        with patch.object(st, "_quote_one_sync", return_value="Apple (AAPL): 100 USD"):
            text = await st.quote("AAPL,MSFT")
            assert "Apple (AAPL)" in text
        with patch.object(
            st,
            "_history_sync",
            return_value="AAPL history\ndate|open|high|low|close|volume\n2026-01-01|1|2|0.5|1.5|100",
        ):
            hist = await st.history("AAPL", period="1mo")
            assert "AAPL history" in hist

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
