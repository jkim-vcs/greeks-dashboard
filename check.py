from greeks import put_greeks
from marketdata import get_quote

p = {"symbol": "KO", "expiry": "2026-10-23", "strike": 84.0}
q = get_quote(p)
print("inputs -> S:", q["price"], "IV:", q["iv"], "div_yield:", q["div_yield"], "T:", round(q["T"], 4))

g = put_greeks(q["price"], 84.0, q["T"], 0.04, q["iv"] or 0.30, q["div_yield"])
print("delta display:", round(g["delta"] * -2, 4), "(want ~0.42)")
print("gamma display:", round(g["gamma"] * -2, 4), "(want ~-0.19)")
print("theta display $/day:", round(g["theta"] * -2 * 100, 2), "(want ~6.17)")