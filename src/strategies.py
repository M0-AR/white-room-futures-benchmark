"""Four white-room archetypes + buy-and-hold baseline, all causal (no lookahead).

Conventions: signal[t] is computed from data <= t, executed at close[t+1].
Position in {-1,0,1}. ATR(14) for stops/targets. Daily-bar proxies of the
intraday ideas seen in the video transcript; intraday 60m frame reuses the
same functions when available.

A pedro_vp_scalper  — prior-20d volume-profile VAL/VAH/POC fade + expansion breakout
B andrea_fade       — Bollinger 2-sigma + RSI fade, only when ADX<20 (chop)
C imry_regime       — ADX/ATR regime router + absorption filter
D nafi_beginner     — low-frequency random + profit-stop & do-nothing
Z buy_hold          — baseline
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean().replace(0, np.nan)
    rs = up / dn
    return (100 - 100 / (1 + rs)).fillna(50)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["High"].diff()
    dn = -df["Low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([(df["High"] - df["Low"]), (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.rolling(n).mean().replace(0, np.nan)
    pdi = 100 * plus.rolling(n).mean() / atr_
    mdi = 100 * minus.rolling(n).mean() / atr_
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0)
    return dx.rolling(n).mean().fillna(0)


def rolling_vp_levels(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Approximate POC/VAH/VAL from price-volume histogram (24 bins). Causal via shift."""
    closes = df["Close"].values
    vols = df["Volume"].fillna(df["Volume"].median()).values
    poc = np.full(len(df), np.nan)
    vah = np.full(len(df), np.nan)
    val = np.full(len(df), np.nan)
    for i in range(lookback, len(df)):
        w = slice(i - lookback, i)
        p, v = closes[w], vols[w]
        lo, hi = p.min(), p.max()
        if hi <= lo:
            poc[i], vah[i], val[i] = p[-1], p[-1], p[-1]
            continue
        bins = np.linspace(lo, hi, 25)
        idx = np.clip(np.digitize(p, bins) - 1, 0, 23)
        agg = np.bincount(idx, weights=v, minlength=24)
        b = int(np.argmax(agg))
        poc[i] = (bins[b] + bins[b + 1]) / 2
        order = np.argsort(-agg)
        cum, tot, sel = 0.0, agg.sum(), {b}
        for o in order:
            if o in sel:
                cum += agg[o]
                continue
            sel.add(o)
            cum += agg[o]
            if cum / tot >= 0.70:
                break
        s = sorted(sel)
        val[i], vah[i] = (bins[s[0]] + bins[s[0] + 1]) / 2, (bins[s[-1]] + bins[s[-1] + 1]) / 2
    return pd.DataFrame({"POC": poc, "VAH": vah, "VAL": val}, index=df.index)


def pedro_vp_scalper(df: pd.DataFrame) -> pd.Series:
    vp = rolling_vp_levels(df)
    sig = pd.Series(0, index=df.index)
    cond_long = df["Close"] < vp["VAL"]
    cond_short = df["Close"] > vp["VAH"]
    sig[cond_long] = 1
    sig[cond_short] = -1
    # expansion breakout overlay: range > 1.5x median -> follow direction
    rng = (df["High"] - df["Low"])
    expand = rng > 1.5 * rng.rolling(20).median()
    mom = np.sign(df["Close"].diff().fillna(0))
    sig[expand & (sig == 0)] = mom[expand & (sig == 0)].astype(int)
    return sig.shift(1).fillna(0).astype(int)  # execute next bar


def andrea_fade(df: pd.DataFrame) -> pd.Series:
    sma = df["Close"].rolling(20).mean()
    sd = df["Close"].rolling(20).std()
    upper, lower = sma + 2 * sd, sma - 2 * sd
    r = rsi(df["Close"])
    chop = adx(df) < 20
    long = (df["Close"] < lower) & (r < 30) & chop
    short = (df["Close"] > upper) & (r > 70) & chop
    sig = pd.Series(0, index=df.index)
    sig[long] = 1
    sig[short] = -1
    return sig.shift(1).fillna(0).astype(int)


def imry_regime(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    a = adx(df)
    sma = df["Close"].rolling(20).mean()
    body = (df["Close"] - df["Open"]).abs()
    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    # absorption proxy: top-decile volume + bottom-quartile body/range -> stand aside
    vol_z = (df["Volume"] - df["Volume"].rolling(20).mean()) / df["Volume"].rolling(20).std().replace(0, np.nan)
    absorbed = (vol_z > 1.5) & ((body / rng) < 0.25)
    regime = pd.Series("chop", index=df.index)
    regime[a > 25] = "trend"
    regime[atr(df) > 1.5 * atr(df).rolling(60).median()] = "highvol"
    sig = pd.Series(0, index=df.index)
    is_range = regime == "chop"
    sig[is_range & (df["Close"] < sma)] = 1
    sig[is_range & (df["Close"] > sma)] = -1
    is_trend = regime == "trend"
    sig[is_trend & (df["Close"] > sma)] = 1
    sig[is_trend & (df["Close"] < sma)] = -1
    sig[absorbed | (regime == "highvol")] = 0
    return sig.shift(1).fillna(0).astype(int), regime


def nafi_beginner(df: pd.DataFrame, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    sig = pd.Series(0, index=df.index)
    # ~1 random round-trip every 20 bars, flat otherwise (do-nothing edge)
    for i in range(20, len(df), 20):
        sig.iloc[i] = int(rng.choice([-1, 1]))
        if i + 2 < len(df):
            sig.iloc[i + 2] = 0
    return sig  # already next-bar by construction spacing


def buy_hold(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1, index=df.index)


STRATEGIES = {
    "A_pedro_vp_scalper": pedro_vp_scalper,
    "B_andrea_fade": andrea_fade,
    "D_nafi_beginner": nafi_beginner,
    "Z_buy_hold": buy_hold,
}
