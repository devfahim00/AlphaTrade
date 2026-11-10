"""Indicators + 3 strategies.
Each strategy: df (open/high/low/close, DatetimeIndex) -> Series {+1 CALL, -1 PUT, 0 none}.
Signal at bar i uses only data up to bar i (no look-ahead)."""
import numpy as np
import pandas as pd


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn)).fillna(50)


def stoch(df, k=14, d=3):
    ll, hh = df.low.rolling(k).min(), df.high.rolling(k).max()
    kk = 100 * (df.close - ll) / (hh - ll).replace(0, np.nan)
    return kk, kk.rolling(d).mean()


def atr(df, n=14):
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _to_sig(call, put):
    return call.fillna(False).astype(int) - put.fillna(False).astype(int)


def sr_price_action(df, lookback=40, tol=0.25):
    """Rejection candle (pin bar / engulfing) at prior swing high/low."""
    a = atr(df)
    res = df.high.rolling(lookback).max().shift(1)
    sup = df.low.rolling(lookback).min().shift(1)
    top = df[["open", "close"]].max(axis=1)
    bot = df[["open", "close"]].min(axis=1)
    rng = (df.high - df.low).replace(0, np.nan)
    bear_pin = (df.high - top) >= 0.6 * rng
    bull_pin = (bot - df.low) >= 0.6 * rng
    po, pc = df.open.shift(1), df.close.shift(1)
    bear_eng = (pc > po) & (df.close < df.open) & (df.open >= pc) & (df.close <= po)
    bull_eng = (pc < po) & (df.close > df.open) & (df.open <= pc) & (df.close >= po)
    put = (df.high >= res - tol * a) & (bear_pin | bear_eng)
    call = (df.low <= sup + tol * a) & (bull_pin | bull_eng)
    return _to_sig(call, put)


def trend_pullback(df, htf_mult=5, fast=20, slow=50):
    """Higher-TF EMA trend + pullback to EMA20 on the base TF, entry with the trend."""
    e_f, e_s = ema(df.close, fast), ema(df.close, slow)
    tf = df.index.to_series().diff().median()
    h = df.close.resample(tf * htf_mult).last().dropna()
    ht = np.sign(ema(h, fast) - ema(h, slow)).shift(1)  # completed HTF bars only
    ht = ht.reindex(df.index, method="ffill").fillna(0)
    up, dn = (ht > 0) & (e_f > e_s), (ht < 0) & (e_f < e_s)
    call = up & (df.low <= e_f) & (df.close > e_f) & (df.close > df.open)
    put = dn & (df.high >= e_f) & (df.close < e_f) & (df.close < df.open)
    return _to_sig(call, put)


def rsi_stoch_reversal(df, lo=35, hi=65, trend_cap=1.5):
    """Counter-trade RSI + stochastic cross, skipped when the trend is strong."""
    r = rsi(df.close)
    k, d = stoch(df)
    strong = ((ema(df.close, 20) - ema(df.close, 50)).abs() / atr(df)) > trend_cap
    call = (r < lo) & (k.shift(1) <= d.shift(1)) & (k > d) & (k < 35) & ~strong
    put = (r > hi) & (k.shift(1) >= d.shift(1)) & (k < d) & (k > 65) & ~strong
    return _to_sig(call, put)


STRATEGIES = {
    "sr_price_action": sr_price_action,
    "trend_pullback": trend_pullback,
    "rsi_stoch_reversal": rsi_stoch_reversal,
}
