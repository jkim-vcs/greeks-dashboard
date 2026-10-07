"""Live short-put dashboard.

Run:
    pip install -r requirements.txt
    flask run            # or: python app.py
Open:
    http://127.0.0.1:5000

One route: fetch live data -> do the Greek math -> render the verdict.
"""
from datetime import datetime, timezone

from flask import Flask, render_template

import greeks
import marketdata

app = Flask(__name__)

RISK_FREE_RATE = 0.04  # 4% — close enough for short-dated options

# ---------------------------------------------------------------------------
# YOUR POSITIONS — this is the file you edit as trades change.
# qty is negative for short. profit_target = your 50% rule buyback level.
# kind is "put" or "call" (default "put").
# ---------------------------------------------------------------------------
POSITIONS = [
    {
        "label": "KO Oct 23 $84 puts",
        "symbol": "KO",
        "expiry": "2026-10-23",   # YYYY-MM-DD; must be close to a listed expiry
        "strike": 84.0,
        "kind": "put",
        "qty": -2,                # short 2 contracts
        "sold": 0.55,             # credit received per share
        "profit_target": 0.27,    # 50% rule: buy back at half the credit
    },
    {
        "label": "BE Nov 22 $230 puts",
        "symbol": "BE",
        "expiry": "2026-11-20",   # YYYY-MM-DD; must be close to a listed expiry
        "strike": 230.0,
        "qty": -1,                # short 2 contracts
        "sold": 7.85,             # filled price
        "profit_target": 4,    # 50% rule: buy back at half the credit
    },
    # Add your next short put by copying the block above, e.g.:
    # {
    #     "label": "BE Oct 23 $205 put",
    #     "symbol": "BE",
    #     "expiry": "2026-10-23",
    #     "strike": 205.0,
    #     "kind": "put",
    #     "qty": -1,
    #     "sold": 2.50,
    #     "profit_target": 1.25,
    # },
    # A short call looks the same, with kind = "call":
    # {
    #     "label": "KO Nov 13 $94 calls",
    #     "symbol": "KO",
    #     "expiry": "2026-11-13",
    #     "strike": 94.0,
    #     "kind": "call",
    #     "qty": -2,
    #     "sold": 0.40,
    #     "profit_target": 0.20,
    # },
]


def analyze(pos):
    """Fetch live data, compute SHORT-side Greeks, answer the 3 questions."""
    n = abs(pos["qty"])
    kind = pos.get("kind", "put")
    snap = marketdata.get_snapshot(pos["symbol"], pos["expiry"], pos["strike"],
                                   kind=kind)

    # Long Greeks from Black-Scholes, flipped to the short side.
    # (Short put: delta +; short call: delta -. We judge risk on |delta|.)
    pricer = greeks.greeks_for(kind)
    long = pricer(
        S=snap["underlying"], K=snap["strike_found"], T=snap["T_years"],
        sigma=snap["iv"], r=RISK_FREE_RATE, q=snap["div_yield"],
    )
    g = {k: -v for k, v in long.items() if k != "price"}  # per-contract SHORT greeks

    mark = snap["mark"]
    pnl = (pos["sold"] - mark) * n * 100
    delta = abs(g["delta"])                       # e.g. 0.24
    theta_day = g["theta"] * n * 100              # dollars per day
    # Typical daily swing in dollars: delta share-equivalents x a 1% move.
    swing_day = delta * n * 100 * snap["underlying"] * 0.01

    answers = []
    # Q1 — profit target?
    hit = mark <= pos["profit_target"]
    answers.append({
        "q": "1. Buyback at or below $%.2f?" % pos["profit_target"],
        "a": "YES — take profit" if hit else "No (mark $%.2f)" % mark,
        "ok": hit, "action": True,
    })
    # Q2 — delta zone? (uses |delta| so puts and calls share one rule)
    if delta >= 0.35:
        zone, good, bad = "DANGER — %.2f" % delta, False, True
    elif delta >= 0.30:
        zone, good, bad = "Watch — %.2f" % delta, True, False
    else:
        zone, good, bad = "OK — %.2f" % delta, True, False
    answers.append({"q": "2. Delta under 0.35?", "a": zone,
                    "ok": good, "warn": (not good) or (delta >= 0.30 and not bad)})
    # Q3 — paycheck vs danger?
    healthy = theta_day >= 0.30 * swing_day
    answers.append({
        "q": "3. Paycheck healthy? ($%.2f/day vs ~$%.0f swing)" % (theta_day, swing_day),
        "a": "Yes — worth holding" if healthy else "Thin — risk outweighs pay",
        "ok": healthy,
    })

    if hit:
        verdict, color = "TAKE PROFIT — close it", "green"
    elif delta >= 0.35:
        verdict, color = "EXIT — trade broke, roll or close", "red"
    elif delta >= 0.30 or not healthy:
        verdict, color = "WATCH — hold, but eyes open", "yellow"
    else:
        verdict, color = "HOLD — theta is paying you", "green"

    return {
        "label": pos["label"], "symbol": pos["symbol"],
        "qty": n, "sold": pos["sold"], "target": pos["profit_target"],
        "underlying": snap["underlying"], "mark": mark, "pnl": round(pnl, 2),
        "delta": round(delta, 4), "theta_day": round(theta_day, 2),
        "gamma": round(g["gamma"], 4), "iv": round(snap["iv"] * 100, 2),
        "swing_day": round(swing_day, 2),
        "days_left": max(int(snap["T_years"] * 365), 0),
        "answers": answers, "verdict": verdict, "color": color,
        "as_of": snap["as_of"],
    }


@app.route("/")
def dashboard():
    cards = []
    for pos in POSITIONS:
        try:
            cards.append(analyze(pos))
        except Exception as e:  # one bad symbol shouldn't kill the page
            cards.append({"label": pos["label"], "error": str(e)})
    return render_template("dashboard.html", cards=cards,
                           now=datetime.now(timezone.utc).strftime("%H:%M UTC"))


if __name__ == "__main__":
    app.run(debug=True)
