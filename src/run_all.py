"""Orchestrator: live-data verify -> 4 archetypes + baseline -> tables/figures."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import yaml
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .data_loader import load_all
from .strategies import pedro_vp_scalper, andrea_fade, imry_regime, nafi_beginner, buy_hold
from .backtest import backtest
from .metrics import summary, walkforward


def run_one(df, name, sig, cfg, is_etf):
    bt = backtest(df, sig, start_equity=cfg["account"]["start_equity"],
                  risk_pct=cfg["account"]["risk_per_trade_pct"],
                  commission_rt=cfg["costs"]["commission_rt_per_contract"],
                  slip_ticks=cfg["costs"]["slippage_ticks_per_side"],
                  tick_value=cfg["costs"]["es_tick_value"],
                  etf_bps=cfg["costs"]["etf_slippage_bps_per_side"],
                  is_etf=is_etf,
                  static_mdd_pct=cfg["account"]["static_max_drawdown_pct"])
    m = summary(bt["equity"], bt["net"], cfg["account"]["start_equity"])
    m.update({"breached_static_mdd": bt["breached_static_mdd"], "turnover": bt["turnover"]})
    return bt, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/experiment.yaml")
    args = ap.parse_args()
    cfg_all = yaml.safe_load(open(args.config))
    rules = yaml.safe_load(open("configs/prop_rules.yaml"))
    outdir = Path(cfg_all["experiment"]["outdir"])
    (outdir / "figures").mkdir(parents=True, exist_ok=True)
    data, prov = load_all(cfg_all["data"]["symbols"],
                          cfg_all["data"]["period_daily"],
                          cfg_all["data"]["period_intraday"],
                          cfg_all["data"]["intraday_interval"],
                          cfg_all["data"]["cache_dir"])
    rows = []
    curves = {}
    for key, df in sorted(data.items()):
        if not key.endswith("_D"):
            continue
        sym = key[:-2]
        is_etf = not sym.endswith("=F")
        sigs = {"A_pedro_vp_scalper": pedro_vp_scalper(df),
                "B_andrea_fade": andrea_fade(df),
                "D_nafi_beginner": nafi_beginner(df, seed=cfg_all["experiment"]["seed"]),
                "Z_buy_hold": buy_hold(df)}
        c_sig, _reg = imry_regime(df)
        sigs["C_imry_regime"] = c_sig
        for name, sig in sigs.items():
            bt, m = run_one(df, name, sig, rules, is_etf)
            wf = walkforward(df, {"A_pedro_vp_scalper": pedro_vp_scalper,
                                  "B_andrea_fade": andrea_fade,
                                  "C_imry_regime": lambda d, seed=42: imry_regime(d)[0],
                                  "D_nafi_beginner": lambda d, seed=42: nafi_beginner(d, seed=seed),
                                  "Z_buy_hold": buy_hold}[name],
                             lambda d, s, **k: backtest(d, s, is_etf=is_etf,
                                start_equity=rules["account"]["start_equity"]),
                             n_splits=rules["walkforward"]["n_splits"],
                             is_ratio=rules["walkforward"]["in_sample_ratio"],
                             seed=cfg_all["experiment"]["seed"])
            m.update({"series": key, "strategy": name, "provenance": prov.get(key, "?"),
                      "wfe_mean": wf["wfe_mean"], "oos_sharpe": wf["oos_sharpe"]})
            rows.append(m)
            curves[f"{key}:{name}"] = bt["equity"]
    res = pd.DataFrame(rows).sort_values(["series", "sharpe"], ascending=[True, False])
    res.to_csv(outdir / "benchmark.csv", index=False)
    # equity figure for primary series (prefer SPY_D live, else first)
    prim = "SPY_D" if any("SPY_D" in c for c in curves) else sorted(curves)[0].split(":")[0]
    plt.figure(figsize=(10, 5))
    for k, eq in curves.items():
        if k.startswith(prim):
            (eq / eq.iloc[0]).plot(label=k.split(":")[1])
    plt.legend(fontsize=7)
    plt.title(f"White-room benchmark — normalised equity ({prim}, {prov.get(prim,'?')})")
    plt.tight_layout()
    plt.savefig(outdir / "figures" / "equity.png", dpi=150)
    # hidden-pattern note: chop-hit test
    note = {"hypotheses": {
        "H1_do_nothing_beats_overtrade_in_chop": "compare turnover vs sharpe; B/C should beat A net of costs in chop",
        "H2_tight_stops_chopped": "bracket variant (see tests) underperforms in ADX<20",
        "H3_regime_filter_rescues_MR": "C_imry_regime WFE > B_andrea_fade WFE"}}
    json.dump({"provenance": prov, "hypotheses": note}, open(outdir / "provenance.json", "w"), indent=2)
    print(res.to_string(index=False))
    print(f"\n[wrote] {outdir/'benchmark.csv'} + figures/equity.png + provenance.json")


if __name__ == "__main__":
    main()
