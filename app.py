"""Live short-put dashboard.

Run:
    pip install -r requirements.txt
    flask run            # or: python app.py
Open:
    http://127.0.0.1:5000

One route: fetch live data -> do the Greek math -> render the verdict.
"""
import json
import os
from datetime import datetime, timezone

from flask import Flask, redirect, render_template, request, url_for

import greeks
import marketdata

app = Flask(__name__)

RISK_FREE_RATE = 0.04  # 4% — close enough for short-dated options

# ---------------------------------------------------------------------------
# POSITIONS come from the trade log (trades.json): each STO opens a dashboard
# position, each BTC closes (part of) it. The 50% rule target is automatic.
# ---------------------------------------------------------------------------
def open_positions():
    """Build dashboard positions from unclosed STO lots in the trade log."""
    lots = []  # [key, remaining qty, price]
    for t in load_trades():
        key = (t["symbol"], t["expiry"], float(t["strike"]), t["kind"])
        if t["action"] == "STO":
            lots.append([key, t["qty"], t["price"]])
        else:  # BTC closes oldest matching lots first
            need = t["qty"]
            for lot in lots:
                if need <= 0 or lot[1] <= 0 or lot[0] != key:
                    continue
                m = min(need, lot[1])
                lot[1] -= m
                need -= m
    groups = {}
    for key, qty, price in lots:
        if qty <= 0:
            continue
        g = groups.setdefault(key, {"qty": 0, "cost": 0.0})
        g["qty"] += qty
        g["cost"] += qty * price
    limits = load_limits()
    positions = []
    for (symbol, expiry, strike, kind), g in groups.items():
        avg = g["cost"] / g["qty"]
        exp = datetime.strptime(expiry, "%Y-%m-%d")
        pkey = position_key(symbol, expiry, strike, kind)
        positions.append({
            "label": "%s %s %d $%g %s" % (symbol, exp.strftime("%b"), exp.day, strike, kind.capitalize()),
            "symbol": symbol,
            "expiry": expiry,
            "strike": strike,
            "kind": kind,
            "qty": -g["qty"],              # negative = short
            "sold": round(avg, 4),         # weighted-average credit
            "profit_target": round(avg * 0.5, 2),  # 50% rule, automatic
            "key": pkey,
            "buy_limit": limits.get(pkey),  # resting buy order, or None
        })
    return positions


# ---------------------------------------------------------------------------
# TRADE LOG — STO/BTC entries stored in trades.json (git-ignored: personal data).
# ---------------------------------------------------------------------------
TRADES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")


def load_trades():
    try:
        with open(TRADES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


# ---------------------------------------------------------------------------
# RESTING BUY LIMITS — John's actual working buyback orders, marked by dragging
# the amber tick on a card's profit bar. Keyed "SYM|expiry|strike|kind".
# Stored in limits.json (git-ignored: personal data), like trades.json.
# ---------------------------------------------------------------------------
LIMITS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "limits.json")


def load_limits():
    try:
        with open(LIMITS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_limits(limits):
    with open(LIMITS_FILE, "w") as f:
        json.dump(limits, f, indent=2)


def position_key(symbol, expiry, strike, kind):
    return "%s|%s|%s|%s" % (symbol, expiry, strike, kind)


def with_pnl(trades):
    """Attach realized P&L to each BTC by FIFO-matching against open STO lots.

    Each BTC row also gets t["closes"]: the STO lots it closed, so the log
    can show the link (qty @ price + STO date). t["unmatched"] is BTC qty
    with no matching STO.
    """
    open_lots = []
    out = []
    for t in trades:
        t = dict(t)
        t["_id"] = len(out)  # stable row id, survives the date sort
        key = (t["symbol"], t["expiry"], float(t["strike"]), t["kind"])
        if t["action"] == "STO":
            open_lots.append({"key": key, "qty": t["qty"], "price": t["price"],
                              "date": t["date"], "id": t["_id"]})
            t["pnl"], t["pnl_cls"] = None, ""
            t["closes"], t["unmatched"] = [], 0
        else:
            need, realized = t["qty"], 0.0
            closes = []
            for lot in open_lots:
                if need <= 0 or lot["qty"] <= 0 or lot["key"] != key:
                    continue
                m = min(need, lot["qty"])
                realized += (lot["price"] - t["price"]) * m * 100
                lot["qty"] -= m
                need -= m
                closes.append({"qty": m, "price": lot["price"],
                               "date": lot["date"], "id": lot["id"]})
            if need < t["qty"]:
                t["pnl"], t["pnl_cls"] = round(realized, 2), "pos" if realized >= 0 else "neg"
            else:
                t["pnl"], t["pnl_cls"] = None, ""
            t["closes"], t["unmatched"] = closes, need
        out.append(t)
    return out


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
    pos.setdefault("profit_target", round(pos["sold"] * 0.5, 2))  # tolerate dicts without it
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
    # Q3 — paycheck vs danger? (pay_pct = paycheck as % of typical daily swing)
    pay_pct = (theta_day / swing_day * 100) if swing_day else 0
    healthy = theta_day >= 0.30 * swing_day
    answers.append({
        "q": "3. Paycheck healthy? ($%.2f/day vs ~$%.0f swing, %.0f%%)" % (theta_day, swing_day, pay_pct),
        "a": "Yes — worth holding" if healthy else "Thin — risk outweighs pay",
        "ok": healthy,
    })

    # Progress toward max profit: captured P&L as % of the premium collected.
    # 100% = the option expires worthless and you keep it all.
    # (Your 50% rule = close when this bar reaches ~50%.)
    max_profit = pos["sold"] * n * 100
    profit_pct = max(0.0, min(1.0, pnl / max_profit)) * 100 if max_profit > 0 else 0.0

    if hit:
        verdict, color = "TAKE PROFIT — Close it", "green"
    elif delta >= 0.35:
        verdict, color = "EXIT — Trade broke, roll or close", "red"
    elif delta >= 0.30 or not healthy:
        verdict, color = "WATCH — Hold, but eyes open", "yellow"
    else:
        verdict, color = "HOLD — Theta is paying you", "green"

    # Resting buy-order tick position (None = no order marked).
    buy_limit = pos.get("buy_limit")
    limit_pct = None
    if buy_limit is not None and pos["sold"] > 0:
        limit_pct = max(0.0, min(100.0, (pos["sold"] - buy_limit) / pos["sold"] * 100))

    return {
        "label": pos["label"], "symbol": pos["symbol"],
        "qty": n, "sold": pos["sold"], "target": pos["profit_target"],
        "key": pos["key"], "buy_limit": buy_limit, "limit_pct": limit_pct,
        "underlying": snap["underlying"], "mark": mark, "pnl": round(pnl, 2),
        "delta": round(delta, 4), "theta_day": round(theta_day, 2),
        "gamma": round(g["gamma"], 4), "iv": round(snap["iv"] * 100, 2),
        "swing_day": round(swing_day, 2),
        "max_profit": round(max_profit, 2),
        "profit_pct": round(profit_pct, 1),
        "days_left": max(int(snap["T_years"] * 365), 0),
        "answers": answers, "verdict": verdict, "color": color,
        "as_of": snap["as_of"],
    }


@app.route("/")
def dashboard():
    cards = []
    for pos in open_positions():
        try:
            cards.append(analyze(pos))
        except Exception as e:  # one bad symbol shouldn't kill the page
            cards.append({"label": pos["label"], "error": str(e)})
    return render_template("dashboard.html", cards=cards,
                           now=datetime.now(timezone.utc).strftime("%H:%M UTC"),
                           today=datetime.now(timezone.utc).strftime("%Y-%m-%d"))


@app.route("/limit", methods=["POST"])
def set_limit():
    """Save or clear a resting buy limit for a position (from the bar tick)."""
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("key", "")
    price = data.get("price")
    limits = load_limits()
    if price is None:
        limits.pop(key, None)
    else:
        try:
            price = round(float(price), 2)
        except (TypeError, ValueError):
            return "Invalid price.", 400
        if price < 0:
            return "Price can't be negative.", 400
        limits[key] = price
    save_limits(limits)
    return "OK"


@app.route("/log", methods=["GET", "POST"])
def trade_log():
    """Log STO/BTC trades; BTC rows show realized P&L matched FIFO to STOs."""
    if request.method == "POST":
        try:
            entry = {
                "date": request.form["date"],
                "action": request.form["action"],
                "symbol": request.form["symbol"].strip().upper(),
                "expiry": request.form["expiry"],
                "strike": float(request.form["strike"]),
                "kind": request.form["kind"],
                "qty": int(request.form["qty"]),
                "price": float(request.form["price"]),
                "notes": request.form.get("notes", "").strip(),
            }
        except (KeyError, ValueError):
            return "Missing or invalid field — go back and fix the form.", 400
        if not entry["date"] or not entry["symbol"] or not entry["expiry"]:
            return "Date, symbol and expiry are required.", 400
        if entry["action"] not in ("STO", "BTC") or entry["kind"] not in ("put", "call"):
            return "Action must be STO/BTC and type put/call.", 400
        if entry["qty"] <= 0 or entry["price"] < 0:
            return "Qty must be positive and price can't be negative.", 400
        trades = load_trades()
        trades.append(entry)
        save_trades(trades)
        return redirect(url_for("dashboard"))
    trades = with_pnl(load_trades())
    # newest date first; later-entered rows first on same date
    trades = [t for _, t in sorted(enumerate(trades),
                                   key=lambda p: (p[1]["date"], p[0]),
                                   reverse=True)]
    total = round(sum(t["pnl"] for t in trades if t["pnl"] is not None), 2)
    n_sto = sum(1 for t in trades if t["action"] == "STO")
    n_btc = sum(1 for t in trades if t["action"] == "BTC")
    return render_template(
        "log.html", trades=trades, total=total, n_sto=n_sto, n_btc=n_btc,
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


if __name__ == "__main__":
    app.run(debug=True)
