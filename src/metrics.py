"""Metrics + walk-forward efficiency (WFE) per 2026 best practice."""
from __future__ import annotations
import numpy as np
import pandas as pd


def summary(eq: pd.Series, net: pd.Series, start: float) -> dict:
    tot = float(eq.iloc[-1] / start - 1)
    ann = float((1 + tot) ** (252 / max(len(eq), 1)) - 1)
    vol = float(net.std() * np.sqrt(252)) if net.std() > 0 else 0.0
    sharpe = float(net.mean() / net.std() * np.sqrt(252)) if net.std() > 0 else 0.0
    downside = net[net < 0]
    sortino = float(net.mean() / downside.std() * np.sqrt(252)) if len(downside) > 1 and downside.std() > 0 else 0.0
    peak = eq.cummax()
    mdd = float(((eq - peak) / peak).min())
    wins = net[net > 0]
    losses = net[net < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf") if len(wins) else 0.0
    return {"total_return": tot, "ann_return": ann, "vol": vol, "sharpe": sharpe,
            "sortino": sortino, "max_drawdown": mdd,
            "profit_factor": pf, "win_rate": float((net > 0).mean()),
            "n_bars": len(eq), "end_equity": float(eq.iloc[-1])}


def walkforward(df, sig_fn, bt_fn, n_splits=5, is_ratio=0.70, **kw):
    n = len(df)
    oos_rets = []
    wfes = []
    for k in range(n_splits):
        a = int(k * n / n_splits)
        b = int(a + (n / n_splits) * is_ratio)
        c = int((k + 1) * n / n_splits)
        if c - b < 30 or b - a < 60:
            continue
        tr, te = df.iloc[a:b], df.iloc[b:c]
        s_tr = sig_fn(tr) if "seed" not in sig_fn.__code__.co_varnames else sig_fn(tr, seed=kw.get("seed", 42))
        s_te = sig_fn(te) if "seed" not in sig_fn.__code__.co_varnames else sig_fn(te, seed=kw.get("seed", 42))
        r_tr = bt_fn(tr, s_tr, **kw)["net"]
        r_te = bt_fn(te, s_te, **kw)["net"]
        m_tr, m_te = r_tr.mean(), r_te.mean()
        wfe = float(m_te / m_tr) if m_tr and m_tr != 0 else 0.0
        wfes.append(float(np.clip(wfe, -2, 2)))
        oos_rets.append(r_te)
    if not oos_rets:
        return {"wfe_mean": 0.0, "wfe_list": [], "oos_sharpe": 0.0}
    oos = pd.concat(oos_rets)
    oos_sh = float(oos.mean() / oos.std() * np.sqrt(252)) if oos.std() > 0 else 0.0
    return {"wfe_mean": float(np.mean(wfes)), "wfe_list": wfes, "oos_sharpe": oos_sh}
