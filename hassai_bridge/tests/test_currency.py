"""Currency convert / rates tools (fawazahmed0 exchange-api)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from services import currency as fx
from services import secondary_routing as sr
from services import toolkits as tk


def test_normalize_code_aliases():
    assert fx.normalize_code("EUR") == "eur"
    assert fx.normalize_code("lei") == "ron"
    assert fx.normalize_code("bitcoin") == "btc"
    assert fx.normalize_code("!!!") == ""


def test_normalize_date():
    assert fx.normalize_date("latest") == "latest"
    assert fx.normalize_date("2024-03-06") == "2024-03-06"
    assert fx.normalize_date("not-a-date") == ""


def test_tools_are_core_and_secondary_web():
    assert tk.is_core_tool("currency_convert") is True
    assert tk.is_core_tool("currency_rates") is True
    assert tk.pack_for_tool("currency_convert") is None
    assert sr.tool_use_for_category("currency_rates") == "web_search"


def test_parse_quotes_arg():
    assert fx.parse_quotes_arg("RON, USD;gbp") == ["RON", "USD", "gbp"]
    assert fx.parse_quotes_arg(["eur", "ron"]) == ["eur", "ron"]


def test_convert_and_rates_mocked():
    payload = {
        "date": "2026-09-11",
        "base": "eur",
        "rates": {"eur": 1.0, "ron": 5.0, "usd": 1.1},
        "source": "mock",
    }

    async def _fake(base, day="latest"):
        assert base == "eur"
        return payload

    async def _run():
        with patch.object(fx, "fetch_base_rates", side_effect=_fake):
            text = await fx.convert(100, "EUR", "RON")
            assert "100 EUR = 500 RON" in text
            assert "2026-09-11" in text
            rates = await fx.rates("EUR", ["RON", "USD"])
            assert "RON: 5" in rates
            assert "USD: 1.1" in rates

    asyncio.run(_run())


def test_invoke_currency_convert(monkeypatch):
    from routers import chat as chat_mod

    async def _fake_convert(amount, frm, to, *, day="latest"):
        return f"ok {amount} {frm}->{to} @{day}"

    monkeypatch.setattr(chat_mod.currency_fx, "convert", _fake_convert)

    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "currency_convert",
            {"amount": 10, "from_currency": "EUR", "to_currency": "RON"},
            search_enabled=False,
        )
    )
    assert used is False
    assert "10 EUR->RON" in text


def test_invoke_currency_rates(monkeypatch):
    from routers import chat as chat_mod

    async def _fake_rates(base, quotes=None, *, day="latest"):
        return f"rates {base} {quotes}"

    monkeypatch.setattr(chat_mod.currency_fx, "rates", _fake_rates)

    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "currency_rates",
            {"base": "USD", "quotes": "EUR,RON"},
            search_enabled=False,
        )
    )
    assert used is False
    assert "rates USD" in text
