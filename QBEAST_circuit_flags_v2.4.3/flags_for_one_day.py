"""
QBEAST AI - the 4 flags for ONE stock on ONE day (after the exchange closes)
=============================================================================
Each flag has its own independent call. Every call receives history UP TO AND INCLUDING
the day being evaluated - nothing later - so the answer for day t is exactly what was
known at the close of day t. Parameters come from qbeast_flags_config.json.

    get_price_band(stock_hist)                 -> "5" / "10" / "20" / "2" / "UNKNOWN"
    get_circuit(stock_hist)                    -> "UPPER" / "LOWER" / ""
    get_mwcb(index_hist)                       -> "LOWER_10" / "UPPER_20" / ""
    get_staircase(stock_hist)                  -> "CLIMBING" / "FALLING" / "BUILDING" / ""
    get_trade_blocked(stock_hist, index_hist)  -> "NO" or "STAIRCASE" / "CHRONIC" / "MWCB_DAY" (joined by +)

Run (PowerShell, in the bundle folder):
    python flags_for_one_day.py --symbol INDOTHAI                         # latest day in the file (live)
    python flags_for_one_day.py --symbol INDOTHAI --date 2021-12-24       # one past day
    python flags_for_one_day.py --symbol INDOTHAI --from 2021-12-15 --to 2022-01-20 --verify   # daily loop
Use in Python:
    from flags_for_one_day import get_staircase
    get_staircase(stock[stock.date <= day])
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit_liquidity_flags as C  # noqa: E402
import flags_io as IO  # noqa: E402
from flags_config import FlagsConfig, load_config  # noqa: E402

_CFG: FlagsConfig | None = None


def _cfg(cfg: FlagsConfig | None) -> FlagsConfig:
    global _CFG
    if cfg is not None:
        return cfg
    if _CFG is None:
        _CFG = load_config()
    return _CFG


def _mw_by_date(index_hist: pd.DataFrame, cfg: FlagsConfig) -> pd.DataFrame:
    idx = index_hist if "index_name" in index_hist.columns else index_hist.assign(index_name="NIFTY50")
    return C.aggregate_mwcb_by_date(C.compute_mwcb_flag(idx, **cfg.mwcb_kwargs("eod")))


# ======================================================================================
# The independent calls. Input: history up to and including the day being evaluated.
# ======================================================================================
def get_price_band(stock_hist: pd.DataFrame, band_hist: pd.DataFrame | None = None,
                   cfg: FlagsConfig | None = None) -> str:
    """FLAG 1 - band % in force today. With point-in-time band data (symbol, date, upper_band_pct,
    lower_band_pct) -> compute_price_band_flag; without -> inferred causally by Flag 2."""
    cfg = _cfg(cfg)
    if band_hist is not None:
        b = C.compute_price_band_flag(band_hist).iloc[-1]
        return C._band_label(b["upper_band_pct"], b["lower_band_pct"])
    circ = C.compute_circuit_hit_flag(stock_hist, mode="eod", circuit_params=cfg.circuit)
    return C.four_flag_columns(circ).PRICE_BAND.iloc[-1]


def get_circuit(stock_hist: pd.DataFrame, cfg: FlagsConfig | None = None) -> str:
    """FLAG 2 - did the stock close locked at its upper / lower circuit today?"""
    cfg = _cfg(cfg)
    circ = C.compute_circuit_hit_flag(stock_hist, mode="eod", circuit_params=cfg.circuit)
    return C.four_flag_columns(circ).CIRCUIT.iloc[-1]


def get_mwcb(index_hist: pd.DataFrame, cfg: FlagsConfig | None = None) -> str:
    """FLAG 3 - market-wide circuit breaker today (NIFTY 50 history up to today)."""
    cfg = _cfg(cfg)
    idx = index_hist if "index_name" in index_hist.columns else index_hist.assign(index_name="NIFTY50")
    mw = C.compute_mwcb_flag(idx, **cfg.mwcb_kwargs("eod"))
    return C.four_flag_columns(mw).MWCB.iloc[-1]


def get_staircase(stock_hist: pd.DataFrame, cfg: FlagsConfig | None = None) -> str:
    """FLAG 4 - is the stock a staircase as of today's close?"""
    cfg = _cfg(cfg)
    circ = C.compute_circuit_hit_flag(stock_hist, mode="eod", circuit_params=cfg.circuit)
    stair = C.compute_staircase_flag(circ, cfg.staircase)
    return C.four_flag_columns(stair).STAIRCASE.iloc[-1]


def get_trade_blocked(stock_hist: pd.DataFrame, index_hist: pd.DataFrame, cfg: FlagsConfig | None = None) -> str:
    """The gate: "NO" = tradable at the next open; otherwise do not buy / sell / exit."""
    cfg = _cfg(cfg)
    calendar = pd.DatetimeIndex(index_hist.date)          # trading days up to today (for missing-session counts)
    return IO.eod_flags(stock_hist, cfg, calendar, _mw_by_date(index_hist, cfg))[C.GATE_COLUMN].iloc[-1]


def flags_for_day(stock: pd.DataFrame, index: pd.DataFrame, day, cfg: FlagsConfig | None = None) -> dict:
    """All flags for `day`, each from its own call, using rows <= day only."""
    cfg = _cfg(cfg)
    day = pd.Timestamp(day)
    s = stock[stock.date <= day]
    n = index[index.date <= day]
    if s.empty or s.date.iloc[-1] != day:
        return {"date": day.date(), "note": "no bar for this stock on this day"}
    return {
        "date": day.date(),
        "close": s.close.iloc[-1],
        "PRICE_BAND": get_price_band(s, cfg=cfg),
        "CIRCUIT": get_circuit(s, cfg),
        "MWCB": get_mwcb(n, cfg),
        "STAIRCASE": get_staircase(s, cfg),
        "TRADE_BLOCKED": get_trade_blocked(s, n, cfg),
    }


def main():
    ap = argparse.ArgumentParser(description="The 4 flags for one stock on one day (or a range of days).")
    ap.add_argument("--config", default=None, help="config JSON (default: qbeast_flags_config.json next to this file)")
    ap.add_argument("--data", default=None, help="data folder (default: paths.data_dir in the config)")
    ap.add_argument("--symbol", required=True, help="e.g. INDOTHAI (file <symbol>.csv in the EOD folder)")
    ap.add_argument("--date", default=None, help="one day, e.g. 2021-12-24 (default: the latest bar)")
    ap.add_argument("--from", dest="d_from", default=None, help="start of a daily range")
    ap.add_argument("--to", dest="d_to", default=None, help="end of a daily range")
    ap.add_argument("--verify", action="store_true", help="range mode: check against a full-history batch run")
    a = ap.parse_args()

    cfg = load_config(a.config)
    data = cfg.data_dir(a.data)
    spath = cfg.sub("stocks_eod_subdir", data) / f"{a.symbol}.csv"
    ipath = cfg.sub("indices_eod_subdir", data) / cfg.paths["mwcb_index_files"]["NIFTY50"]
    for p in (spath, ipath):
        if not p.exists():
            sys.exit(f"ERROR: file not found: {p}")
    stock = IO.load_eod(spath)
    index = IO.load_eod(ipath).assign(index_name="NIFTY50")

    if a.d_from or a.d_to:                                  # ---- daily iterative loop ----
        lo = pd.Timestamp(a.d_from) if a.d_from else stock.date.iloc[0]
        hi = pd.Timestamp(a.d_to) if a.d_to else stock.date.iloc[-1]
        days = stock.date[(stock.date >= lo) & (stock.date <= hi)]
        if days.empty:
            sys.exit("ERROR: no bars in that date range")
        out = pd.DataFrame([flags_for_day(stock, index, d, cfg) for d in days])   # each day: data <= that day
        pd.set_option("display.width", 200)
        print(out.to_string(index=False))
        if a.verify:
            full = IO.eod_flags(stock, cfg, pd.DatetimeIndex(index.date), _mw_by_date(index, cfg))
            full = full[full.date.isin(days)].reset_index(drop=True)
            ok = all(out[c].tolist() == full[c].tolist() for c in IO.OUTCOLS)
            print(f"\n[VERIFY] daily independent calls == full-history batch: {ok}")
    else:                                                   # ---- one day ----
        day = pd.Timestamp(a.date) if a.date else stock.date.iloc[-1]
        f = flags_for_day(stock, index, day, cfg)
        print(f"\n{a.symbol} flags at the close of {f['date']}:")
        for k, v in f.items():
            if k != "date":
                print(f"   {k:14s} {v if v != '' else '-'}")
        if f.get("TRADE_BLOCKED") not in (None, "NO"):
            print("   -> do NOT buy, sell or exit this stock at the next open (MtM continues)")
        elif "TRADE_BLOCKED" in f:
            print("   -> tradable at the next open")


if __name__ == "__main__":
    main()
