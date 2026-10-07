"""Live market data via yfinance (free, no API key). Quotes are ~15 min delayed.

If Yahoo ever changes its API and this breaks, this is the only file
you need to fix: everything else reads the dict returned by get_snapshot().
"""
from datetime import datetime, timezone

import yfinance as yf


def _dividend_yield(ticker, symbol):
    """Annual dividend yield as a decimal. Falls back to a guess, then 0."""
    try:
        y = ticker.info.get("dividendYield")
        if y:
            y = float(y)
            if y > 1.0:
                # yfinance sometimes returns a percentage (e.g. 2.36)
                # instead of a decimal (0.0236) -- normalize it
                y /= 100.0
            return y
    except Exception:
        pass
    return {"KO": 0.028}.get(symbol, 0.0)  # extend as you add symbols


def _resolve_expiry(ticker, wanted):
    """Use the listed expiry closest to the one asked for."""
    listed = ticker.options or []
    if wanted in listed:
        return wanted
    if not listed:
        raise ValueError("no option expiries listed")
    return min(listed, key=lambda e: abs(
        (datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(wanted, "%Y-%m-%d")).days))


def get_snapshot(symbol, expiry, strike, kind="put"):
    """Returns dict: underlying, bid, ask, mark, iv, expiry used, time_to_expiry."""
    t = yf.Ticker(symbol)

    try:
        underlying = float(t.fast_info["last_price"])
    except Exception:
        underlying = float(t.history(period="1d")["Close"].iloc[-1])

    use_expiry = _resolve_expiry(t, expiry)
    chain = t.option_chain(use_expiry)
    contracts = chain.calls if kind == "call" else chain.puts
    row = contracts[contracts["strike"] == float(strike)]
    if row.empty:  # fall back to nearest strike rather than crashing
        row = contracts.iloc[[(contracts["strike"] - float(strike)).abs().argmin()]]
    r = row.iloc[0]

    bid = float(r["bid"] or 0)
    ask = float(r["ask"] or 0)
    last = float(r.get("lastPrice") or 0)
    mark = round((bid + ask) / 2, 2) if (bid and ask) else round(last, 2)
    iv = float(r["impliedVolatility"] or 0)  # decimal, e.g. 0.1843

    exp = datetime.strptime(use_expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    T = max((exp - now).total_seconds() / (365.0 * 86400.0), 1e-6)

    return {
        "symbol": symbol,
        "underlying": round(underlying, 2),
        "bid": bid,
        "ask": ask,
        "mark": mark,
        "iv": iv,
        "expiry": use_expiry,
        "strike_found": float(r["strike"]),
        "T_years": T,
        "div_yield": _dividend_yield(t, symbol),
        "as_of": now.strftime("%Y-%m-%d %H:%M UTC"),
    }
