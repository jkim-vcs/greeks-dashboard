"""Black-Scholes Greeks for European options.

Kept dependency-free on purpose: the math is the lesson here.
Everything is for ONE LONG contract. For a short position, flip the signs
(which app.py does for you).

Conventions:
  S      = stock price
  K      = strike
  T      = time to expiry, in YEARS
  sigma  = implied volatility as a decimal (0.1843 = 18.43%)
  r      = risk-free rate as a decimal
  q      = dividend yield as a decimal
"""
import math


def _n(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _n_prime(x):
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _core(S, K, T, sigma, r, q):
    """Shared Black-Scholes ingredients: (d1, d2, sqrt_t, disc_q, disc_r)."""
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2, sqrt_t, math.exp(-q * T), math.exp(-r * T)


def _expired(S, K, kind):
    """Expired or degenerate: only intrinsic value is left."""
    if kind == "put":
        return {"delta": -1.0 if S < K else 0.0, "gamma": 0.0, "theta": 0.0,
                "vega": 0.0, "price": max(K - S, 0.0)}
    return {"delta": 1.0 if S > K else 0.0, "gamma": 0.0, "theta": 0.0,
            "vega": 0.0, "price": max(S - K, 0.0)}


def put_greeks(S, K, T, sigma, r=0.04, q=0.0):
    """Greeks for one LONG put. Theta per day; vega per 1 vol point."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return _expired(S, K, "put")
    d1, d2, sqrt_t, disc_q, disc_r = _core(S, K, T, sigma, r, q)
    theta = (
        -(S * disc_q * _n_prime(d1) * sigma) / (2 * sqrt_t)
        + r * K * disc_r * _n(-d2)
        - q * S * disc_q * _n(-d1)
    ) / 365.0
    return {
        "delta": disc_q * (_n(d1) - 1.0),
        "gamma": disc_q * _n_prime(d1) / (S * sigma * sqrt_t),
        "theta": theta,
        "vega": S * disc_q * _n_prime(d1) * sqrt_t / 100.0,
        "price": K * disc_r * _n(-d2) - S * disc_q * _n(-d1),
    }


def call_greeks(S, K, T, sigma, r=0.04, q=0.0):
    """Greeks for one LONG call. Theta per day; vega per 1 vol point."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return _expired(S, K, "call")
    d1, d2, sqrt_t, disc_q, disc_r = _core(S, K, T, sigma, r, q)
    theta = (
        -(S * disc_q * _n_prime(d1) * sigma) / (2 * sqrt_t)
        - r * K * disc_r * _n(d2)
        + q * S * disc_q * _n(d1)
    ) / 365.0
    return {
        "delta": disc_q * _n(d1),
        "gamma": disc_q * _n_prime(d1) / (S * sigma * sqrt_t),
        "theta": theta,
        "vega": S * disc_q * _n_prime(d1) * sqrt_t / 100.0,
        "price": S * disc_q * _n(d1) - K * disc_r * _n(d2),
    }


def greeks_for(kind):
    """Pick the pricer by position kind: greeks_for('call') -> call_greeks."""
    return call_greeks if kind == "call" else put_greeks
