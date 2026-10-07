# Short Put Dashboard

Your cheat sheet, live. Watches your short puts during market hours and answers
the same three questions as traffic lights: green = hold/take profit,
yellow = watch, red = exit.

## Run it

```bash
cd greeks-dashboard
python3 -m venv venv && source venv/bin/activate   # once
pip install -r requirements.txt                    # once
flask run                                          # every time
```

Open http://127.0.0.1:5000 in your browser. The page refreshes itself every
3 minutes. Quotes are ~15 minutes delayed (fine for keep-or-exit decisions,
not for scalping).

## Make it yours

- **Add a position:** copy a block in `POSITIONS` in `app.py`. `qty` is
  negative for short. `profit_target` is your 50%-rule buyback level.
- **Tweak the rules:** the verdict logic lives in `analyze()` in `app.py`
  (delta zones, paycheck ratio). Change the numbers, reload the page.
- **The math:** `greeks.py` is dependency-free Black-Scholes — read it,
  it's the whole options-pricing lesson in 60 lines.
- **The data:** `marketdata.py` is the only file that talks to Yahoo. If
  Yahoo changes something, fix it there; nothing else cares.

## How the verdict works

1. **Buyback ≤ target?** → TAKE PROFIT (your 50% rule, mechanical).
2. **Delta ≥ 0.35?** → EXIT. The trade broke; roll or close.
3. **Delta 0.30–0.35, or theta < 30% of a typical day's swing?** → WATCH.
4. Otherwise → HOLD, theta is paying you.

## Files

| file | what |
|---|---|
| `app.py` | Flask app: your positions + the 3-question verdict |
| `greeks.py` | Black-Scholes Greeks, no dependencies |
| `marketdata.py` | Yahoo Finance fetching (the only network code) |
| `templates/dashboard.html` | the page |
| `requirements.txt` | flask + yfinance |
