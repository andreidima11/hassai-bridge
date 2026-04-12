"""Yahoo Finance skill — get stock quotes by ticker symbol."""

from typing import Any, Dict

try:
    import yfinance as yf
except ImportError:
    yf = None


class YahooFinanceSkill:
    name = "yahoo_finance"
    description = "Get a real-time stock quote for a ticker symbol (e.g. AAPL, TSLA, MSFT)"

    @staticmethod
    def execute(input_data: Dict[str, Any]) -> Dict[str, Any]:
        if yf is None:
            return {"success": False, "message": "yfinance package is not installed. Run: pip install yfinance"}

        symbol = (input_data.get("symbol") or input_data.get("ticker") or "").strip().upper()
        if not symbol:
            return {"success": False, "message": "Missing 'symbol' parameter (e.g. AAPL)"}

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if not info or "shortName" not in info:
                return {"success": False, "message": f"No data found for ticker '{symbol}'"}

            name = info.get("shortName", symbol)
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            currency = info.get("currency", "USD")
            change = info.get("regularMarketChange")
            change_pct = info.get("regularMarketChangePercent")
            market_cap = info.get("marketCap")
            volume = info.get("regularMarketVolume")
            day_high = info.get("dayHigh")
            day_low = info.get("dayLow")

            parts = [f"{name} ({symbol}): {price} {currency}"]
            if change is not None and change_pct is not None:
                sign = "+" if change >= 0 else ""
                parts.append(f"Change: {sign}{change:.2f} ({sign}{change_pct:.2f}%)")
            if day_low and day_high:
                parts.append(f"Day range: {day_low} – {day_high}")
            if volume:
                parts.append(f"Volume: {volume:,}")
            if market_cap:
                if market_cap >= 1e12:
                    cap_str = f"{market_cap / 1e12:.2f}T"
                elif market_cap >= 1e9:
                    cap_str = f"{market_cap / 1e9:.2f}B"
                elif market_cap >= 1e6:
                    cap_str = f"{market_cap / 1e6:.2f}M"
                else:
                    cap_str = f"{market_cap:,.0f}"
                parts.append(f"Market cap: {cap_str} {currency}")

            return {
                "success": True,
                "message": " | ".join(parts),
                "data": {
                    "symbol": symbol,
                    "name": name,
                    "price": price,
                    "currency": currency,
                    "change": change,
                    "change_percent": change_pct,
                    "day_high": day_high,
                    "day_low": day_low,
                    "volume": volume,
                    "market_cap": market_cap,
                },
            }
        except Exception as e:
            return {"success": False, "message": f"Error fetching data for {symbol}: {e}"}
