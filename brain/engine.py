"""Backtest + walk-forward strategy selection."""
import os
from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

from strategies import ENABLED, PARAMS, STRATEGIES


@dataclass
class Config:
    tf: int = int(os.getenv("QX_TF", 15))               # candle size, seconds
    expiry_bars: int = int(os.getenv("QX_EXPIRY_BARS", 4))  # trade length = bars * tf
    payout: float = float(os.getenv("QX_PAYOUT", 0.85))     # e.g. 0.85 = 85%
    window: int = int(os.getenv("QX_WINDOW", 400))      # bars used for selection
    min_candles: int = int(os.getenv("QX_MIN_CANDLES", 150))
    min_train: int = int(os.getenv("QX_MIN_TRAIN", 12))
    min_test: int = int(os.getenv("QX_MIN_TEST", 6))


def build_df(candles):
    a = np.array(candles, dtype=float)
    return pd.DataFrame(
        {"open": a[:, 1], "high": a[:, 2], "low": a[:, 3], "close": a[:, 4]},
        index=pd.to_datetime(a[:, 0], unit="s"),
    )


def wilson_lb(w, n, z=1.64):
    if n == 0:
        return 0.0
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d


def outcomes(close, sig, k):
    d = sig.values
    idx = np.flatnonzero(d != 0)
    idx = idx[idx + k < len(close)]
    res = ((close[idx + k] - close[idx]) * d[idx]) > 0  # tie = loss
    return idx, res


def _stats(idx, res, lo, hi):
    m = (idx >= lo) & (idx < hi)
    n, w = int(m.sum()), int(res[m].sum())
    return {"n": n, "wins": w, "wr": round(w / n, 4) if n else None}


def analyze(df, cfg: Config):
    n, k = len(df), cfg.expiry_bars
    if n < cfg.min_candles:
        return {"status": "warming_up", "have": n, "need": cfg.min_candles}
    close = df.close.values
    start, end = max(60, n - cfg.window), n - k
    split = start + int(0.7 * (end - start))   # train = older 70%, test = newer 30%
    be = 1 / (1 + cfg.payout)

    rows = []
    for name, fn in STRATEGIES.items():
        if not ENABLED.get(name, True):
            continue
        sig = fn(df, **PARAMS.get(name, {})).fillna(0).astype(int)
        idx, res = outcomes(close, sig, k)
        tr, te = _stats(idx, res, start, split), _stats(idx, res, split, end)
        rows.append({"name": name, "train": tr, "test": te, "now": int(sig.iloc[-1]),
                     "lb": round(wilson_lb(tr["wins"], tr["n"]), 4)})

    elig = [r for r in rows if r["train"]["n"] >= cfg.min_train]
    best = max(elig, key=lambda r: r["lb"]) if elig else None  # chosen on TRAIN only

    if best is None:
        verdict, reason = False, "not enough historical setups yet"
    elif best["train"]["wr"] <= be:
        verdict, reason = False, "best strategy is below break-even on train"
    elif best["test"]["n"] < cfg.min_test:
        verdict, reason = False, "too few out-of-sample trades to confirm"
    elif best["test"]["wr"] <= be:
        verdict, reason = False, "best strategy fails out-of-sample (test)"
    else:
        verdict, reason = True, "passes train + out-of-sample test"

    side = best["now"] if verdict else 0
    return {
        "status": "ready",
        "signal": {1: "CALL", -1: "PUT", 0: "WAIT"}[side],
        "verdict": "TRADE" if verdict else "SKIP",
        "reason": reason,
        "strategy": best["name"] if best else None,
        "best": best,
        "breakeven": round(be, 4),
        "strategies": rows,
    }
