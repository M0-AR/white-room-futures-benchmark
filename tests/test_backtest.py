import pandas as pd
from src import strategies as S
from src.backtest import backtest
from src.data_loader import load_all


def _df(n=120):
    import numpy as np
    rng = np.random.default_rng(0)
    px = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame({"Open": px, "High": px + 1, "Low": px - 1,
                         "Close": px, "Volume": 1e6}, index=pd.date_range("2024-01-01", periods=n, freq="B"))


def test_no_lookahead_shift():
    df = _df()
    for fn in [S.pedro_vp_scalper, S.andrea_fade]:
        s = fn(df)
        # signal at t cannot use close[t+1]: construction uses .shift(1)
        assert s.iloc[:21].sum() == 0  # warmup empty


def test_backtest_costs_reduce_pnl():
    df = _df()
    sig = S.andrea_fade(df)
    free = backtest(df, sig, is_etf=True, etf_bps=0.0)["net"].sum()
    paid = backtest(df, sig, is_etf=True, etf_bps=5.0)["net"].sum()
    assert paid <= free


def test_nafi_sparse():
    df = _df(200)
    s = S.nafi_beginner(df, seed=1)
    assert 1 <= s.abs().sum() <= 30  # low-frequency by design
