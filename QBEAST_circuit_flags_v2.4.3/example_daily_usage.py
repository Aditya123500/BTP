"""
QBEAST AI - three equivalent ways to use the flags in a daily, causal backtest
===============================================================================
  A. DAILY LOOP, literal   : every day call the functions on data UP TO TODAY and read the last row.
                             Easiest to reason about; slow (re-reads history) -> checks / a few stocks.
  B. DAILY LOOP, streaming : one tracker per stock, feed ONE bar per day. Same answers as A,
                             constant work per day -> 1,200+ stocks, Paper and Live.
  C. BATCH ONCE            : one call on full history, then on day t read ONLY row t.
                             Allowed because row t is computed from bars <= t only.
This script runs all three for one stock and checks that they agree.

Run (PowerShell, in the bundle folder):
    python example_daily_usage.py --symbol INDOTHAI
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit_liquidity_flags as C  # noqa: E402
import flags_io as IO  # noqa: E402
from daily_backtest_loop import label  # noqa: E402
from flags_config import load_config  # noqa: E402

COLS = IO.OUTCOLS


def mw_by_date(index_hist: pd.DataFrame, cfg) -> pd.DataFrame:
    return C.aggregate_mwcb_by_date(C.compute_mwcb_flag(index_hist.assign(index_name="NIFTY50"), **cfg.mwcb_kwargs()))


def run_literal(stock, index, cfg, last_n: int) -> pd.DataFrame:
    rows = []
    for t in range(max(0, len(stock) - last_n), len(stock)):
        today = stock.date.iloc[t]
        idx = index[index.date <= today]                                  # <= today only
        v = IO.eod_flags(stock.iloc[: t + 1], cfg, pd.DatetimeIndex(idx.date), mw_by_date(idx, cfg))
        rows.append(v.iloc[-1][["date"] + COLS].to_dict())
    return pd.DataFrame(rows)


def run_streaming(stock, index, cfg) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(index.date)
    tracker = cfg.tracker(stock.symbol.iloc[0], calendar=calendar)
    mw = mw_by_date(index, cfg).set_index("date")
    rows = []
    for bar in stock.to_dict("records"):                                   # ---- the daily loop ----
        f = tracker.update_eod(bar)                                        # this bar + memory of earlier bars
        lvl = int(mw.mwcb_level.get(bar["date"], 0))
        d = mw.mwcb_dir.get(bar["date"]) if lvl else None
        rows.append({"date": bar["date"], **label(f, lvl, d, bool(cfg.gate["block_on_mwcb_day"]))})
        # >>> the strategy decides here using ONLY rows[-1]; orders fill at the next bar's open <<<
    return pd.DataFrame(rows)


def run_batch(stock, index, cfg) -> pd.DataFrame:
    return IO.eod_flags(stock, cfg, pd.DatetimeIndex(index.date), mw_by_date(index, cfg))[["date"] + COLS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--symbol", default="INDOTHAI")
    ap.add_argument("--check-days", type=int, default=60, help="days recomputed with the literal loop A")
    a = ap.parse_args()
    cfg = load_config(a.config)
    data = cfg.data_dir(a.data)
    stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / f"{a.symbol}.csv")
    index = IO.load_eod(cfg.sub("indices_eod_subdir", data) / cfg.paths["mwcb_index_files"]["NIFTY50"])

    B = run_streaming(stock, index, cfg)
    Cb = run_batch(stock, index, cfg)
    A = run_literal(stock, index, cfg, a.check_days)
    same_bc = B[COLS].reset_index(drop=True).equals(Cb[COLS].reset_index(drop=True))
    same_ab = A[COLS].reset_index(drop=True).equals(B[COLS].tail(len(A)).reset_index(drop=True))
    print(f"{a.symbol}: {len(stock)} days | streaming == batch: {same_bc} | "
          f"literal daily == streaming (last {len(A)} days): {same_ab}")
    print(f"staircase days: {B.STAIRCASE.isin(['CLIMBING', 'FALLING']).sum()} | "
          f"blocked days: {(B.TRADE_BLOCKED != 'NO').sum()}")
    sel = B[B.STAIRCASE != ""]
    print(sel.head(12).to_string(index=False) if len(sel) else "(no staircase activity for this stock)")
    if not (same_bc and same_ab):
        sys.exit(1)


if __name__ == "__main__":
    main()
