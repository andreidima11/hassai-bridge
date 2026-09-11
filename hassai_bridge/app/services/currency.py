"""Currency exchange via fawazahmed0/exchange-api (CDN + Cloudflare fallback).

No API key. Daily rates including fiat, common crypto, and metals.
https://github.com/fawazahmed0/exchange-api
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

log = logging.getLogger("hassai.currency")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE_RE = re.compile(r"^[a-z0-9]{2,10}$")

# Common nicknames → ISO / API codes (lowercase).
_ALIASES = {
    "lei": "ron",
    "leu": "ron",
    "euro": "eur",
    "euros": "eur",
    "dollar": "usd",
    "dollars": "usd",
    "bucks": "usd",
    "pound": "gbp",
    "pounds": "gbp",
    "sterling": "gbp",
    "yen": "jpy",
    "yuan": "cny",
    "swiss": "chf",
    "bitcoin": "btc",
    "ether": "eth",
    "ethereum": "eth",
}

_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


def normalize_code(raw: str) -> str:
    s = (raw or "").strip().lower().replace(" ", "")
    if s in _ALIASES:
        return _ALIASES[s]
    if _CODE_RE.match(s):
        return s
    return ""


def normalize_date(raw: str | None) -> str:
    s = (raw or "latest").strip().lower() or "latest"
    if s == "latest":
        return "latest"
    if _DATE_RE.match(s):
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return s
        except ValueError:
            return ""
    return ""


def _urls(day: str, base: str) -> list[str]:
    endpoint = f"v1/currencies/{base}.min.json"
    return [
        f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{day}/{endpoint}",
        f"https://{day}.currency-api.pages.dev/{endpoint}",
    ]


async def fetch_base_rates(base: str, day: str = "latest") -> dict[str, Any]:
    """Return {date, base, rates: {code: float}} or raise."""
    base = normalize_code(base)
    day = normalize_date(day)
    if not base:
        raise ValueError("Invalid currency code.")
    if not day:
        raise ValueError("Invalid date (use latest or YYYY-MM-DD).")

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        for url in _urls(day, base):
            try:
                resp = await client.get(url, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    last_err = RuntimeError(f"HTTP {resp.status_code} from {url}")
                    continue
                data = resp.json()
                if not isinstance(data, dict):
                    last_err = RuntimeError("Unexpected JSON shape")
                    continue
                rates_raw = data.get(base)
                if not isinstance(rates_raw, dict):
                    last_err = RuntimeError(f"Missing rates for base {base}")
                    continue
                rates: dict[str, float] = {}
                for k, v in rates_raw.items():
                    try:
                        rates[str(k).lower()] = float(v)
                    except (TypeError, ValueError):
                        continue
                if base not in rates:
                    rates[base] = 1.0
                return {
                    "date": str(data.get("date") or (date.today().isoformat() if day == "latest" else day)),
                    "base": base,
                    "rates": rates,
                    "source": url,
                }
            except Exception as e:
                last_err = e
                log.debug("currency fetch failed %s: %s", url, e)
                continue
    raise RuntimeError(f"Currency API unavailable: {last_err}")


def _fmt_amount(n: float) -> str:
    if abs(n) >= 1000:
        return f"{n:,.2f}"
    if abs(n) >= 1:
        return f"{n:.4f}".rstrip("0").rstrip(".")
    if abs(n) >= 0.01:
        return f"{n:.6f}".rstrip("0").rstrip(".")
    return f"{n:.8f}".rstrip("0").rstrip(".")


async def convert(
    amount: float,
    from_currency: str,
    to_currency: str,
    *,
    day: str = "latest",
) -> str:
    src = normalize_code(from_currency)
    dst = normalize_code(to_currency)
    if not src or not dst:
        return "Error: need valid from/to currency codes (e.g. EUR, USD, RON)."
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Error: amount must be a number."
    if amount < 0:
        return "Error: amount must be non-negative."

    try:
        payload = await fetch_base_rates(src, day)
    except Exception as e:
        return f"Error: could not load rates for {src.upper()}: {e}"

    rates = payload["rates"]
    if dst not in rates:
        return (
            f"Error: {dst.upper()} is not in the rate table for {src.upper()} "
            f"on {payload['date']}."
        )
    rate = float(rates[dst])
    result = amount * rate
    return (
        f"{_fmt_amount(amount)} {src.upper()} = {_fmt_amount(result)} {dst.upper()} "
        f"(rate 1 {src.upper()} = {_fmt_amount(rate)} {dst.upper()}, date {payload['date']})."
    )


async def rates(
    base: str,
    quotes: list[str] | None = None,
    *,
    day: str = "latest",
) -> str:
    base_n = normalize_code(base)
    if not base_n:
        return "Error: need a valid base currency (e.g. EUR, USD, RON)."

    want: list[str] = []
    for q in quotes or []:
        code = normalize_code(str(q))
        if code and code != base_n and code not in want:
            want.append(code)
    if not want:
        # Sensible default basket for RO/EU users
        want = [c for c in ("ron", "usd", "eur", "gbp", "chf", "btc") if c != base_n]

    try:
        payload = await fetch_base_rates(base_n, day)
    except Exception as e:
        return f"Error: could not load rates for {base_n.upper()}: {e}"

    rates_map = payload["rates"]
    lines = [f"Rates for 1 {base_n.upper()} on {payload['date']}:"]
    missing: list[str] = []
    for code in want:
        if code not in rates_map:
            missing.append(code.upper())
            continue
        lines.append(f"- {code.upper()}: {_fmt_amount(float(rates_map[code]))}")
    if missing:
        lines.append(f"(missing: {', '.join(missing)})")
    return "\n".join(lines)


def parse_quotes_arg(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    s = str(raw).strip()
    if not s:
        return []
    return [p.strip() for p in re.split(r"[,;\s]+", s) if p.strip()]


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "currency_convert",
            "description": (
                "Convert an amount between currencies using live daily mid-market rates "
                "(fawazahmed0 exchange-api). Use for FX questions like "
                "'how much is 100 EUR in RON'. Supports fiat, common crypto (BTC, ETH), "
                "and metals. Prefer this over web search for exchange rates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Amount in the source currency.",
                    },
                    "from_currency": {
                        "type": "string",
                        "description": "Source currency code (EUR, USD, RON, BTC, …).",
                    },
                    "to_currency": {
                        "type": "string",
                        "description": "Target currency code.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Optional: 'latest' (default) or YYYY-MM-DD for a historical day.",
                    },
                },
                "required": ["amount", "from_currency", "to_currency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "currency_rates",
            "description": (
                "List exchange rates for 1 unit of a base currency into one or more quotes. "
                "Use when the user asks 'what's the EUR/RON rate' or wants several quotes at once. "
                "Prefer this over web search for FX rates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {
                        "type": "string",
                        "description": "Base currency code (e.g. EUR).",
                    },
                    "quotes": {
                        "type": "string",
                        "description": (
                            "Optional comma-separated quote codes (e.g. 'RON,USD,GBP'). "
                            "Default: RON,USD,EUR,GBP,CHF,BTC (excluding base)."
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": "Optional: 'latest' (default) or YYYY-MM-DD.",
                    },
                },
                "required": ["base"],
            },
        },
    },
]

TOOL_NAMES = frozenset({"currency_convert", "currency_rates"})
