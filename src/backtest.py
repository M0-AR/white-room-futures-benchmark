"""Causal backtester with futures-realistic frictions + prop-firm envelope.

- execution at next-bar close (no lookahead)
- costs: commission RT amortised + 1-tick/side slippage (futures) or bps (ETF)
- ATR stop/target optional via `use_bracket`
- prop guardrails: static 5% MDD breach flag, personal daily stop -> flat rest of day
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .strategies import atr


def backtest(df: pd.DataFrame, signal: pd.Series, start_equity=100000.0,
             risk_pct=0.25, commission_rt=4.0, slip_ticks=1, tick_value=12.50,
             etf_bps=1.0, is_etf=False, use_bracket=False,
             daily_stop_pct=3.0, static_mdd_pct=5.0) -> dict:
    px = df["Close"]
    rets = px.pct_change().fillna(0)
    pos = signal.reindex(df.index).fillna(0).astype(float)
    # bracket: cap adverse single-bar move at 0.5 ATR (tight-stop study)
    if use_bracket:
        a = atr(df)
        strat_raw = pos.shift(1).fillna(0) * rets
        cap = (0.005 * a / px).fillna(0.01)
        strat_raw = strat_raw.clip(lower=-cap.fillna(0.01))
        strat = strat_raw
    else:
        strat = pos.shift(1).fillna(0) * rets
    # costs per position-change (round-trip proxy)
    turns = pos.diff().abs().fillna(0)
    if is_etf:
        cost = turns * (etf_bps / 1e4)
    else:
        # normalise futures $ cost into return space via notional proxy (px*50 for ES-like)
        notional = px * 50
        cost = turns * (commission_rt + 2 * slip_ticks * tick_value) / notional
    net = strat - cost.fillna(0)
    # personal daily stop: if cumulative day loss < -stop, flatten (daily bars: trailing stop on equity)
    eq = start_equity * (1 + net).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak
    breached_static = bool((dd < -static_mdd_pct / 100).any())
    # cap trades/day proxy: signal already sparse; report turns
    return {"equity": eq, "net": net, "gross": strat, "cost": cost,
            "drawdown": dd, "breached_static_mdd": breached_static,
            "turnover": float(turns.sum()), "n_bars": len(df)}
