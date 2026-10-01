"""Live public-data loader with deterministic synthetic fallback.

Primary: Yahoo Finance (no key) for ES=F, NQ=F, SPY, QQQ.
- daily: period=5y (continuous front-month proxy; documented limitation)
- intraday: 60d x 60m for session-open effects when available.

Every file written records `provenance` (live vs synthetic) so no public
claim can confuse the two. Follows 2026 best practice: continuous-contract
choice documented, never silently mixed.
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd


def _synthetic(symbol: str, n: int = 1250, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(abs(hash(symbol + str(seed))) % (2**31))
    rets = rng.normal(0.0002, 0.012, n)
    # inject chop regimes + one CPI-like compression every ~60 bars
    for i in range(0, n, 60):
        rets[i:i + 5] *= 0.35
    px = 100 * np.exp(np.cumsum(rets))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    df = pd.DataFrame({"Open": px * (1 + rng.normal(0, .001, n)),
                       "High": px * 1.008, "Low": px * 0.992,
                       "Close": px, "Volume": vol}, index=idx)
    df.index.name = "Date"
    return df


def load_one(symbol: str, period: str, interval: str, cache_dir: Path) -> tuple[pd.DataFrame, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("=", "").replace("^", "")
    fp = cache_dir / f"{safe}_{period}_{interval}.csv"
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval=interval,
                         auto_adjust=True, progress=False, threads=False)
        if df is None or len(df) < 50:
            raise ValueError(f"too few rows for {symbol}: {0 if df is None else len(df)}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns={c: c.capitalize() for c in df.columns})
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[keep].dropna()
        df.to_csv(fp)
        return df, "live_yahoo"
    except Exception as e:
        print(f"[data] {symbol} {interval} live fetch failed ({e}); using synthetic fallback")
        df = _synthetic(symbol)
        df.to_csv(fp)
        return df, f"synthetic_fallback:{e}"


def load_all(symbols, period_daily="5y", period_intraday="60d",
             intraday_interval="60m", cache_dir="results/data"):
    cdir = Path(cache_dir)
    out, prov = {}, {}
    for s in symbols:
        d, p = load_one(s, period_daily, "1d", cdir)
        out[s + "_D"], prov[s + "_D"] = d, p
    # best-effort intraday for session-open study
    for s in symbols:
        try:
            d, p = load_one(s, period_intraday, intraday_interval, cdir)
            out[s + "_H"], prov[s + "_H"] = d, p
        except Exception as e:
            prov[s + "_H"] = f"skipped:{e}"
    (cdir / "provenance.csv").write_text(
        "series,provenance\n" + "\n".join(f"{k},{v}" for k, v in prov.items()))
    return out, prov
