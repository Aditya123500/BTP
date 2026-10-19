"""
QBEAST AI - true day-by-day causal loop over the whole universe
================================================================
How a backtest (and Paper / Live) calls the flags:

    for each trading day t (in date order):
        for each stock that traded on day t:
            flags = tracker[stock].update_eod(today's bar)      # uses bars <= t only
            if TRADE_BLOCKED != "NO":  no new buy, no new sell, no exit (MtM continues)
            else:                      the strategy may trade; the order fills at t+1 open

Flag 1 Price Band + Flag 2 Circuit + Flag 4 Staircase (+ chronic illiquidity) come from
CircuitLiquidityTracker.update_eod(); Flag 3 MWCB comes from the index row of day t.
Parameters come from qbeast_flags_config.json. Put your strategy into strategy_hook().

Run (PowerShell, in the bundle folder):
    python daily_backtest_loop.py                                     # paths + workers from the config
    python daily_backtest_loop.py --data "E:\\Downloads\\Final_Data" --workers 25 --verify
        --verify compares every stock-day with run_four_flags.py output (run that first)

Outputs (<data>\\_daily_loop_out):
    daily_flags_all.csv.gz      one row per stock per day: PRICE_BAND, CIRCUIT, MWCB, STAIRCASE, TRADE_BLOCKED
    daily_summary.csv           per day: stocks traded, blocked, staircase-tagged, MWCB level
    trackers_state.pkl          tracker state after the last day (reload to continue in Paper / Live)
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit_liquidity_flags as C  # noqa: E402
import flags_io as IO  # noqa: E402
from flags_config import load_config, mp_context  # noqa: E402

COLS = IO.OUTCOLS


# ------------------------------------------------------------------ strategy placeholder
def strategy_hook(day, symbol: str, bar: dict, flags: dict, blocked: bool) -> None:
    """Called once per stock per day AFTER that day's flags are known (close of `day`).
    Replace with your logic. If `blocked` is True you must not open, add to or exit
    a position in `symbol`; mark-to-market continues. Orders fill at the next bar's open."""
    return None


# ------------------------------------------------------------------ labels (same rules as C.four_flag_columns)
def _band(f: dict) -> str:
    u, l, src, hit = f.get("band_upper_used"), f.get("band_lower_used"), f.get("band_source"), f.get("band_hit_dir")
    if src == "given":
        return C._band_label(u, l)
    v = l if hit == "lower" else (u if C._num(u) else l)
    return C._band_label(v, v)


def label(f: dict, mwcb_level: int, mwcb_dir, block_on_mwcb_day: bool = True) -> dict:
    """Tracker output of one bar -> the 5 readable columns."""
    d = f.get("circuit_locked_dir")
    if isinstance(d, str):
        circuit = d.upper() + ("_1TICK" if f.get("tick_degenerate") else "")
    elif f.get("upside_locked"):
        circuit = "UPSIDE_LOCKED"
    else:
        circuit = ""
    st = f.get("staircase_state")
    if st in (C.CONFIRMED, C.COOLING):
        stair = str(f.get("staircase_dir") or "TAGGED").upper()
    elif st == C.BUILDING:
        stair = "BUILDING"
    else:
        stair = ""
    mw = f"{str(mwcb_dir).upper()}_{mwcb_level}" if mwcb_level > 0 and isinstance(mwcb_dir, str) else ""
    reasons = [r for r, on in (("STAIRCASE", f.get("staircase")), ("CHRONIC", f.get("chronic_illiquid")),
                               ("MWCB_DAY", block_on_mwcb_day and mwcb_level > 0),
                               ("STEP_STAIRCASE", f.get("step_staircase"))) if on]          # v2.4.3: + STEP
    sst = f.get("step_state")                                                                # v2.4.3 view column
    step = (str(f.get("step_dir") or "TAGGED").upper() if sst in (C.STEP_TAGGED, C.STEP_COOLING)
            else ("BUILDING" if sst == C.STEP_BUILDING else ""))
    return {"PRICE_BAND": _band(f), "CIRCUIT": circuit, "MWCB": mw, "STAIRCASE": stair,
            "TRADE_BLOCKED": "+".join(reasons) if reasons else "NO", "STEP": step}


def _load(p: str) -> pd.DataFrame | None:
    try:
        d = IO.load_eod(p)
        return d if len(d) >= 2 else None
    except Exception as e:  # noqa: BLE001
        print(f"   !! {Path(p).stem}: {type(e).__name__}: {e}", flush=True)
        return None


def main():
    ap = argparse.ArgumentParser(description="Day-by-day causal flag loop over the whole universe.")
    ap.add_argument("--config", default=None, help="config JSON (default: qbeast_flags_config.json next to this file)")
    ap.add_argument("--data", default=None, help="data folder (default: paths.data_dir in the config)")
    ap.add_argument("--out", default=None, help="output folder (default: <data>\\_daily_loop_out)")
    ap.add_argument("--workers", type=int, default=None, help="processes for loading files (default: config)")
    ap.add_argument("--limit", type=int, default=0, help="first N stock files only (smoke test)")
    ap.add_argument("--verify", action="store_true", help="compare with run_four_flags.py output")
    a = ap.parse_args()

    cfg = load_config(a.config)
    data = cfg.data_dir(a.data)
    if not data.exists():
        sys.exit(f"ERROR: data folder not found: {data}  (use --data or set paths.data_dir in the config)")
    workers = a.workers or cfg.run["workers"]
    out = cfg.output_dir(data, "_daily_loop_out", a.out)
    out.mkdir(parents=True, exist_ok=True)
    block_mw = bool(cfg.gate["block_on_mwcb_day"])
    t0 = time.time()
    print(f"QBEAST daily loop | circuit_liquidity_flags v{C.__version__} | pandas {pd.__version__}")
    print(cfg.summary())

    # ---- market-wide: calendar + MWCB per day
    mkt = IO.load_market(cfg, data)
    mw = mkt.mw_daily.set_index("date") if mkt.mw_daily is not None else pd.DataFrame(columns=["mwcb_level", "mwcb_dir"])
    mw_level = mw["mwcb_level"].to_dict()
    mw_dir = mw["mwcb_dir"].to_dict()

    # ---- load stock bars (parallel), arrange by day
    files = sorted(cfg.sub("stocks_eod_subdir", data).glob("*.csv"))
    if a.limit:
        files = files[: a.limit]
    print(f"loading {len(files)} stock files with {workers} workers ...", flush=True)
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context(cfg)) as ex:
        dfs = [d for d in ex.map(_load, map(str, files), chunksize=8) if d is not None]
    if not dfs:
        sys.exit("ERROR: no stock files could be loaded")
    keep = ["symbol", "date", "open", "high", "low", "close", "volume", "exchange", "source", "_gap_filled",
            "upper_band_pct", "lower_band_pct", "prev_close"]
    allbars = pd.concat([d[[c for c in keep if c in d.columns]] for d in dfs], ignore_index=True)
    allbars = allbars.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)
    days = allbars["date"].drop_duplicates().tolist()
    print(f"{allbars.symbol.nunique()} stocks, {len(allbars):,} stock-days, {len(days):,} trading days "
          f"(loaded in {time.time() - t0:.0f}s). Running the daily loop ...", flush=True)

    # ---- THE DAILY LOOP (strictly causal) ----
    trackers: dict[str, C.CircuitLiquidityTracker] = {}
    records = allbars.to_dict("records")
    rows, summary = [], []
    i, n = 0, len(records)
    t1 = time.time()
    for k, day in enumerate(days):
        lvl = int(mw_level.get(day, 0) or 0)
        dr = mw_dir.get(day)
        n_day = n_blk = n_stair = 0
        while i < n and records[i]["date"] == day:
            bar = records[i]
            i += 1
            sym = bar["symbol"]
            tr = trackers.get(sym)
            if tr is None:
                tr = trackers[sym] = cfg.tracker(sym, calendar=mkt.calendar)
            f = tr.update_eod(bar)                      # flags as of the close of `day`
            lab = label(f, lvl, dr if isinstance(dr, str) else None, block_mw)
            blocked = lab["TRADE_BLOCKED"] != "NO"
            strategy_hook(day, sym, bar, f, blocked)    # <<< your strategy: day t information only
            rows.append((sym, day, bar["close"], *[lab[c] for c in COLS]))
            n_day += 1
            n_blk += blocked
            n_stair += lab["STAIRCASE"] in ("CLIMBING", "FALLING")
        summary.append((day, n_day, n_blk, n_stair, lvl))
        if (k + 1) % 1000 == 0 or k + 1 == len(days):
            print(f"   day {k + 1:,}/{len(days):,}  {day.date()}  ({time.time() - t1:.0f}s)", flush=True)

    res = pd.DataFrame(rows, columns=["symbol", "date", "close"] + COLS)
    res.to_csv(out / "daily_flags_all.csv.gz", index=False, compression="gzip", date_format="%Y-%m-%d")
    S = pd.DataFrame(summary, columns=["date", "stocks_traded", "trade_blocked", "staircase_tagged", "mwcb_level"])
    S.to_csv(out / "daily_summary.csv", index=False, date_format="%Y-%m-%d")
    with open(out / "trackers_state.pkl", "wb") as fh:
        pickle.dump(trackers, fh)

    print(f"\nDaily loop done: {len(res):,} stock-days in {time.time() - t1:.0f}s")
    for c in COLS:
        vc = res[c].replace("", "(blank)").value_counts()
        print(f"   {c:13s} " + " | ".join(f"{k}: {v:,}" for k, v in vc.head(8).items()))
    last = S.iloc[-1]
    tagged = res[(res.date == last.date) & res.STAIRCASE.isin(["CLIMBING", "FALLING"])]
    print(f"   last day {last.date.date()}: traded {last.stocks_traded}, blocked {last.trade_blocked}, "
          f"staircase {', '.join(tagged.symbol) or '-'}")

    if a.verify:
        ref = cfg.output_dir(data, "_four_flags_out") / "four_flags_eod_stocks_all.csv.gz"
        if not ref.exists():
            print(f"[VERIFY] {ref} not found - run run_four_flags.py first")
        else:
            b = pd.read_csv(ref, keep_default_na=False, dtype=str)
            r = res.assign(date=res.date.dt.strftime("%Y-%m-%d")).astype(str)
            cols = [c for c in COLS if c in b.columns]
            m = r.merge(b[["symbol", "date"] + cols], on=["symbol", "date"], suffixes=("", "_batch"))
            diff = {c: int((m[c] != m[c + "_batch"]).sum()) for c in cols}
            print(f"[VERIFY] daily loop vs batch run_four_flags: rows compared {len(m):,} | mismatches {diff}")

    print(f"\nTotal {time.time() - t0:.0f}s. Wrote: {out}")


if __name__ == "__main__":
    main()
