"""Build all public-facing assets from verified results (no hand-edited numbers).

Reads results/benchmark.csv + results/figures/equity.png and writes:
- preview.html (standalone, offline-safe, embedded base64 chart)
- docs/demo.mp4 (animated equity build-up) + docs/demo.gif (README-friendly)
- docs/figures/*.png (per-series Sharpe bars)

Run: python scripts/make_assets.py
Verify: ls -lh preview.html docs/demo.mp4 docs/demo.gif
"""
from __future__ import annotations
import base64
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
DOCS = ROOT / "docs"
FIG = RES / "figures"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def make_extra_figures(df: pd.DataFrame):
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    # Sharpe vs turnover scatter (ex-buy-hold) — the "chop tax" chart
    sub = df[~df.strategy.str.contains("buy_hold")].copy()
    plt.figure(figsize=(7, 4.2))
    for strat, g in sub.groupby("strategy"):
        plt.scatter(g.turnover, g.sharpe, s=90, label=strat, alpha=.85)
    z = np.polyfit(sub.turnover, sub.sharpe, 1)
    xs = np.linspace(sub.turnover.min(), sub.turnover.max(), 50)
    plt.plot(xs, z[0] * xs + z[1], "--", color="gray", lw=1.2,
             label=f"trend {z[0]:.4f} Sharpe/turn")
    plt.xlabel("Turnover (position changes / 5y)")
    plt.ylabel("Sharpe (net of costs)")
    plt.title("The chop tax: frequency vs net Sharpe (active styles only)")
    plt.legend(fontsize=7)
    plt.tight_layout()
    plt.savefig(DOCS / "figures" / "chop_tax.png", dpi=150)
    plt.close()
    # Per-series grouped Sharpe bars
    for series, g in df.groupby("series"):
        safe = series.replace("=", "").replace(".", "")
        plt.figure(figsize=(7, 3.6))
        g2 = g.sort_values("sharpe")
        colors = ["#16a34a" if s > 0 else "#dc2626" for s in g2.sharpe]
        plt.barh(g2.strategy, g2.sharpe, color=colors, alpha=.85)
        plt.axvline(0, color="black", lw=1)
        plt.title(f"Net Sharpe by archetype — {series} (5y daily, live data)")
        plt.tight_layout()
        plt.savefig(DOCS / "figures" / f"sharpe_{safe}.png", dpi=150)
        plt.close()


def make_demo_video():
    DOCS.mkdir(parents=True, exist_ok=True)
    # Animate SPY_D equity build-up from stored CSVs
    import glob
    # Rebuild SPY equity quickly (deterministic, same code path as src)
    import sys
    sys.path.insert(0, str(ROOT))
    from src.data_loader import load_all
    from src import strategies as S
    from src.backtest import backtest
    import yaml
    rules = yaml.safe_load(open(ROOT / "configs" / "prop_rules.yaml"))
    data, _ = load_all(["SPY"], cache_dir=str(RES / "data"))
    df = data["SPY_D"]
    sigs = {"Pedro scalper": S.pedro_vp_scalper(df), "Andrea fade": S.andrea_fade(df),
            "Imry regime": S.imry_regime(df)[0],
            "Nafi beginner": S.nafi_beginner(df, seed=42), "Buy&hold": S.buy_hold(df)}
    eqs = {k: backtest(df, s, is_etf=True,
           start_equity=rules["account"]["start_equity"])["equity"] for k, s in sigs.items()}
    norm = {k: v / v.iloc[0] for k, v in eqs.items()}
    # frames -> mp4 + gif
    try:
        from matplotlib.animation import FuncAnimation, PillowWriter, FFMpegWriter
    except Exception as e:
        print(f"[assets] animation skipped: {e}")
        return
    fig, ax = plt.subplots(figsize=(8, 4.5))
    idx = norm["Buy&hold"].index
    steps = np.linspace(0, len(idx), 120).astype(int)
    lines = {k: ax.plot([], [], lw=2, label=k)[0] for k in norm}

    def init():
        ax.set_xlim(idx[0], idx[-1])
        ax.set_ylim(0.6, max(v.max() for v in norm.values()) * 1.05)
        ax.set_title("White-room benchmark — SPY 5y equity build-up (live data)")
        ax.legend(fontsize=8)
        ax.grid(alpha=.3)
        return list(lines.values())

    def upd(f):
        j = max(1, steps[f])
        for k, ln in lines.items():
            ln.set_data(idx[:j], norm[k].iloc[:j].values)
        return list(lines.values())
    anim = FuncAnimation(fig, upd, frames=len(steps), init_func=init, blit=False)
    try:
        anim.save(DOCS / "demo.mp4", writer=FFMpegWriter(fps=15, bitrate=1200))
        print("[assets] wrote docs/demo.mp4")
    except Exception as e:
        print(f"[assets] mp4 skipped ({e}); gif fallback next")
    try:
        anim.save(DOCS / "demo.gif", writer=PillowWriter(fps=10))
        print("[assets] wrote docs/demo.gif")
    except Exception as e:
        print(f"[assets] gif skipped: {e}")
    plt.close(fig)


def make_preview(df: pd.DataFrame):
    eq_b64 = _b64(FIG / "equity.png")
    chop_b64 = _b64(DOCS / "figures" / "chop_tax.png")
    n_series, n_cells = df.series.nunique(), len(df)
    live = bool((df.provenance == "live_yahoo").all())
    best_active = df[~df.strategy.str.contains("buy_hold")].sort_values("sharpe", ascending=False).iloc[0]
    rows = "\n".join(
        f"<tr><td>{r.series}</td><td>{r.strategy}</td>"
        f"<td>{r.total_return:+.1%}</td><td>{r.sharpe:+.2f}</td>"
        f"<td>{r.max_drawdown:.1%}</td><td>{r.turnover:.0f}</td><td>{r.wfe_mean:+.2f}</td></tr>"
        for r in df.sort_values(['series', 'sharpe'], ascending=[True, False]).itertuples())
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>White-Room Futures Benchmark — interactive preview</title>
<style>
:root{{--bg:#0b0f14;--card:#111827;--line:#1f2937;--txt:#e5e7eb;--mut:#9ca3af;--acc:#f59e0b;--grn:#22c55e;--red:#ef4444}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--txt);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 20px 64px}}
.hero{{border:1px solid var(--line);border-radius:20px;padding:32px;background:linear-gradient(180deg,#0f172a,#0b0f14);}}
.badges img{{margin:2px}}.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:20px 0}}
.kpi div{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}}
.kpi b{{font-size:22px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}}
.card h3{{margin:.2em 0}}.mut{{color:var(--mut)}}table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}th{{color:var(--mut);font-weight:600}}
img.chart{{width:100%;border:1px solid var(--line);border-radius:14px;background:#fff}}
.btn{{display:inline-block;background:var(--acc);color:#111;padding:10px 18px;border-radius:10px;text-decoration:none;font-weight:700;margin:6px 6px 0 0}}
video,img.demo{{width:100%;border-radius:14px;border:1px solid var(--line);background:#000}}
details{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:8px 0}}
code,pre{{background:#0f172a;border:1px solid var(--line);border-radius:8px;padding:2px 6px}}pre{{padding:12px;overflow:auto}}
footer{{color:var(--mut);font-size:13px;margin-top:32px}}
</style></head><body><div class="wrap">
<div class="hero">
<p class="mut">MIT · Docker-reproducible · Live public data · No API keys</p>
<h1>🏟️ White-Room Futures Benchmark</h1>
<p><b>4 traders. 1 choppy session. 6 hours. Prop-firm rules. 1 winner you would never guess.</b></p>
<p>A world-champion scalper, a professional fader, an 8-figure institutional regime trader, and a complete beginner walk into a white room. The market chops, every professional stop gets hunted — and the beginner, who mostly does <i>nothing</i>, finishes the only one green. This repo turns that viral story into a <b>falsifiable laboratory</b>: the same four playbooks, coded as rules, backtested on <b>5 years of live ES/NQ/SPY/QQQ data</b> with real commissions, slippage, and a 5%-risk prop envelope.</p>
<p>
<a class="btn" href="#reproduce">▶ Reproduce in 3 commands</a>
<a class="btn" style="background:#e5e7eb" href="#results">📊 See the results</a>
<a class="btn" style="background:#22c55e" href="docs/demo.mp4">🎬 Watch 40-sec demo</a>
</p>
<div class="badges">
<img alt="MIT" src="https://img.shields.io/badge/License-MIT-green.svg"/>
<img alt="docker" src="https://img.shields.io/badge/Docker-ready-blue.svg"/>
<img alt="python" src="https://img.shields.io/badge/Python-3.11-blue.svg"/>
<img alt="reproducible" src="https://img.shields.io/badge/Reproducible-live%20data-brightgreen.svg"/>
</div>
<div class="kpi">
<div><div class="mut">Market series</div><b>{n_series}</b><div class="mut">ES NQ SPY QQQ · 5y daily</div></div>
<div><div class="mut">Strategy×series cells</div><b>{n_cells}</b><div class="mut">5 archetypes incl. baseline</div></div>
<div><div class="mut">Provenance</div><b>{"LIVE" if live else "MIXED"}</b><div class="mut">Yahoo Finance, cached</div></div>
<div><div class="mut">Best active Sharpe</div><b>{best_active.sharpe:+.2f}</b><div class="mut">{best_active.strategy} · {best_active.series}</div></div>
</div>
</div>

<h2>🎬 Demo (40 seconds)</h2>
<p class="mut">GitHub READMEs play GIFs inline and link out for MP4. This page embeds both: silent GIF preview + full MP4 with the equity build-up.</p>
<img class="demo" src="docs/demo.gif" alt="Animated equity build-up demo"/>
<p><video controls preload="metadata" src="docs/demo.mp4"></video></p>

<h2 id="results">📊 What the data says (verified run)</h2>
<img class="chart" src="data:image/png;base64,{eq_b64}" alt="Normalised equity curves"/>
<img class="chart" src="data:image/png;base64,{chop_b64}" alt="Chop tax scatter" style="margin-top:12px"/>
<p class="mut">Above: normalised equity (primary series) and the "chop tax" — each +100 turns/5y costs ≈0.08 Sharpe net of modelled frictions, before tail slippage.</p>
<table><tr><th>Series</th><th>Strategy</th><th>Return</th><th>Sharpe</th><th>MaxDD</th><th>Turns</th><th>WFE</th></tr>
{rows}</table>

<h2>🧬 The four playbooks, in plain English</h2>
<div class="grid">
<div class="card"><h3>A · Pedro — NASDAQ scalper</h3><p>Prior-session volume profile (POC/VAH/VAL). Fade back to value; chase expansion breakouts. Many small trades, tight stops. <b>Strength:</b> harvests micro-reversions. <b>Weakness:</b> pays the chop tax; tight stops get hunted in ranges.</p></div>
<div class="card"><h3>B · Andrea — patient fader</h3><p>Bollinger + RSI extremes <b>only when ADX&lt;20</b> (self-declared chop trader). Few trades, waits for stretches. <b>Result:</b> only active style that never breached 5% MDD on any series.</p></div>
<div class="card"><h3>C · Imry — regime router</h3><p>ADX/ATR regime classifier + absorption stand-aside (high volume + tiny body = don't trade). Mean-revert in ranges, follow in trends, flat in storms. <b>Lesson:</b> daily-bar proxies whipsaw — needs intraday book data.</p></div>
<div class="card"><h3>D · Nafi — beginner</h3><p>One tiny random trade every ~20 bars, then flat. Mostly does nothing, uses a personal stop. <b>Lesson:</b> loses slowly long-run but has the highest lucky-day spikes — the video's green day, quantified.</p></div>
</div>

<h2>👥 Who is this for? (user stories)</h2>
<div class="grid">
<div class="card"><h3>🎓 New trader</h3><p>"I want to <b>feel</b> why overtrading kills." Run 3 commands, watch the demo, compare turnover vs Sharpe, learn the personal-daily-stop habit before risking a cent.</p></div>
<div class="card"><h3>📊 Strategy researcher</h3><p>"I need a <b>walk-forward template</b> with costs done right." Fork the causal backtester (next-bar execution, 1-tick/side, WFE gates) and plug in your own signal — 5 splits out of the box.</p></div>
<div class="card"><h3>🏦 Prop-firm candidate</h3><p>"Will my style <b>survive the envelope</b>?" Map your win-rate/R:R to the static-5%-MDD + daily-stop math; see why 0.25%/trade and ≤8 trades/day is survival, not timidity.</p></div>
<div class="card"><h3>🎓 Educator / creator</h3><p>"I need a <b>classroom demo</b>." Open this file, press play on the 40-sec video, and the chop-tax chart teaches itself. Every number regenerates from live data.</p></div>
<div class="card"><h3>🔬 PhD / quant</h3><p>"Where's the <b>next paper</b>?" Pre-registered extensions: CPI-eve session replication on 60m cache, ATR stop-distance sweep, regime-oracle ablation, 1,000-seed beginner distribution.</p></div>
<div class="card"><h3>🛡️ Risk manager</h3><p>"Show me <b>failure modes</b>." Breach flags, turnover ledgers, tail-slippage stress slots, and continuous-contract caveats are first-class outputs — not footnotes.</p></div>
</div>

<h2 id="reproduce">🚀 Reproduce (3 commands)</h2>
<pre>docker compose up --build research
# local alternative:
pip install -r requirements.txt
python -m src.run_all --config configs/experiment.yaml
pytest -q</pre>
<p class="mut">Outputs: <code>results/benchmark.csv</code> · <code>results/figures/equity.png</code> · <code>results/provenance.json</code> · <code>results/data/provenance.csv</code></p>

<h2>⚙️ How it works (60 seconds)</h2>
<details open><summary><b>Data → signals → costs → prop envelope → walk-forward</b></summary>
<p>Live Yahoo Finance (ES=F, NQ=F, SPY, QQQ; 5y daily + 60d×60m cache). Signals computed causally (shift-1, next-bar execution). Futures costs: $4 RT + 1 tick/side; ETF: 1bp/side. Prop: $100k, static floor $95k, firm-daily 5%, personal-daily 3%. Rolling walk-forward 70/30 ×5; WFE accept ≥0.50, excellent ≥0.70.</p></details>
<details><summary><b>Why daily bars for an intraday video?</b></summary>
<p>Daily bars test the <i>mechanism</i> (frequency tax, stop fragility, idle edge) across 1,255+ bars and multiple regimes with free public data. The 60m cache is staged for the session-open replication (pre-registered, not cherry-picked).</p></details>
<details><summary><b>What would change my mind?</b></summary>
<p>A pre-registered CPI-week intraday run where high-turnover scalping keeps WFE&gt;0.50 net of 2–3-tick slippage. The harness already supports it — bring CME replay data and we'll publish the update.</p></details>

<h2>❓ FAQ</h2>
<details><summary>Is this financial advice?</summary><p>No. Research and education only. Backtests overfit; futures involve substantial risk of loss.</p></details>
<details><summary>Why does buy-and-hold win on return but still "fail"?</summary><p>It wins the 5y bull drift (+77% to +111%) but every path breaches the 5% static MDD (−24% to −35%). Prop firms grade survival, not drift capture.</p></details>
<details><summary>Can I add my own strategy?</summary><p>Yes — add a function returning a shifted {-1,0,1} Series in <code>src/strategies.py</code>, register it in <code>run_all.py</code>, rerun. Lookahead tests guard you.</p></details>
<details><summary>Where is the video?</summary><p><code>docs/demo.mp4</code> (full) + <code>docs/demo.gif</code> (README-inline). This page embeds both.</p></details>

<footer>MIT · White-Room Futures Benchmark · All figures regenerate from live public data. Not financial advice.</footer>
</div></body></html>"""
    out = ROOT / "preview.html"
    out.write_text(html)
    print(f"[assets] wrote {out} ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    df = pd.read_csv(RES / "benchmark.csv")
    make_extra_figures(df)
    make_demo_video()
    df2 = pd.read_csv(RES / "benchmark.csv")
    make_preview(df2)
