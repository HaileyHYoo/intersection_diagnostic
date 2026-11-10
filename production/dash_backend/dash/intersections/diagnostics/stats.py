"""Historical envelopes and the three comparison rules of the methodology.

- two_sided (Q1 volume, Q3A cycle length): abnormal when the current value is outside the 10th-90th
  percentile range AND differs from the usual value by at least the rule's percentage.
- poorer_only (Q3B cycle stability): abnormal only on the poorer side of the range; unusually good
  stability is never flagged.
- range_only (Q3C phase service): below the 10th percentile is LOW, above the 90th is HIGH; no
  percentage threshold.

The usual (reference) value is the mean of the historical observations, as in the chatbot's
operating-envelope checks. Percentiles use linear interpolation between ranks.
"""
from __future__ import annotations

from statistics import mean, median

NORMAL, ABNORMAL, INSUFFICIENT = "NORMAL", "ABNORMAL", "INSUFFICIENT DATA"


def quantile(values: list[float], q: float) -> float | None:
    v = sorted(values)
    if not v:
        return None
    pos = q * (len(v) - 1)
    lo = int(pos)
    frac = pos - lo
    return v[lo] if lo + 1 >= len(v) else v[lo] * (1 - frac) + v[lo + 1] * frac


def envelope(values: list[float], rules: dict) -> dict:
    """{n, usual, p10, p90}; usual and percentiles are None below the minimum observation count."""
    values = [v for v in values if v is not None]
    out = {"n": len(values), "usual": None, "p_low": None, "p_high": None}
    if len(values) < rules["history"]["min_observations"]:
        return out
    centre = median if rules.get("reference_value") == "median" else mean
    out.update(usual=centre(values), p_low=quantile(values, rules["percentiles"]["low"]),
               p_high=quantile(values, rules["percentiles"]["high"]))
    return out


def pct_difference(current: float, usual: float) -> float | None:
    return None if not usual else (current - usual) / abs(usual) * 100


def _result(status, current, env, direction=None, diff=None, reason=None) -> dict:
    return {"status": status, "current": current, "usual": env.get("usual"), "p_low": env.get("p_low"),
            "p_high": env.get("p_high"), "n_history": env.get("n", 0), "direction": direction,
            "pct_difference": diff, "reason": reason}


def _insufficient(current, env) -> dict | None:
    if current is None:
        return _result(INSUFFICIENT, None, env, reason="no current value for the analysis period")
    if env.get("usual") is None:
        return _result(INSUFFICIENT, current, env, reason=f"only {env.get('n', 0)} valid historical observations")
    return None


def two_sided(current: float | None, env: dict, min_pct: float) -> dict:
    missing = _insufficient(current, env)
    if missing:
        return missing
    diff = pct_difference(current, env["usual"])
    outside = current < env["p_low"] or current > env["p_high"]
    # With a usual value of zero the percentage is undefined; the range test alone decides.
    big = diff is None or abs(diff) >= min_pct
    direction = "HIGH" if current > env["usual"] else "LOW"
    status = ABNORMAL if outside and big else NORMAL
    return _result(status, current, env, direction if status == ABNORMAL else None, diff)


def poorer_only(current: float | None, env: dict, higher_is_better: bool) -> dict:
    missing = _insufficient(current, env)
    if missing:
        return missing
    poorer = current < env["p_low"] if higher_is_better else current > env["p_high"]
    diff = pct_difference(current, env["usual"])
    return _result(ABNORMAL if poorer else NORMAL, current, env, "POORER" if poorer else None, diff)


def range_only(current: float | None, env: dict) -> dict:
    missing = _insufficient(current, env)
    if missing:
        return missing
    diff = pct_difference(current, env["usual"])
    if current < env["p_low"]:
        return _result(ABNORMAL, current, env, "LOW", diff)
    if current > env["p_high"]:
        return _result(ABNORMAL, current, env, "HIGH", diff)
    return _result(NORMAL, current, env, None, diff)
