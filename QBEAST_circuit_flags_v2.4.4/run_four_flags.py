"""
QBEAST AI - four-flag runner for the whole universe (parallel, causal)
======================================================================
Writes one column per flag for every stock and index, plus the trading gate:

    PRICE_BAND | CIRCUIT | MWCB | STAIRCASE | TRADE_BLOCKED

Every output row t is computed from bars <= t of that stock only (plus the market-wide
MWCB state known at the close of t). Parameters come from qbeast_flags_config.json.

Run (PowerShell, in the bundle folder):
    python run_four_flags.py                                   # paths + workers from the config
    python run_four_flags.py --data "E:\\Downloads\\Final_Data" --workers 25 --intraday --check-every 1
    python run_four_flags.py --config my_config.json --limit 50   # quick smoke test on 50 stocks

Outputs (default <data>\\_four_flags_out):
    eod_stocks\\<SYMBOL>.csv            date, exchange, close, volume + the 5 columns
    eod_indices\\<INDEX>.csv            date, close + the 5 columns (NA except MWCB)
    intraday_stocks\\<SYMBOL>.csv.gz    (--intraday) one row per bar + the 5 columns
    four_flags_eod_stocks_all.csv.gz    all stocks in one file
    four_flags_summary.csv              per-symbol counts and last-day flags
    eod_etfs\\, *_etfs.csv / four_flags_eod_etfs_all.csv.gz   v2.4.3: the same for ETFs (paths.etfs_eod_subdir set)
    staircase_episodes.csv              every tagged staircase episode
    step_episodes.csv                   v2.4.3: every tagged STEP staircase episode (illiquid "flat, then jump")
    four_flags_report.txt               the console report
    selfcheck_failures.csv              only written if a causality self-check failed
"""
from __future__ import annotations

import argparse
import gzip
import random
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit_liquidity_flags as C  # noqa: E402
import flags_io as IO  # noqa: E402
from flags_config import load_config, mp_context  # noqa: E402

OUTCOLS = IO.OUTCOLS
_G: dict = {}   # per-process globals, set by the pool initializer


def _init(cfg_path, calendar, mw_daily, mw_intraday):
    _G["cfg"] = load_config(cfg_path)
    _G["calendar"], _G["mw_daily"], _G["mw_intraday"] = calendar, mw_daily, mw_intraday


def _same(a: pd.Series, b: pd.Series) -> bool:
    a = a.astype(object).where(a.notna(), None).reset_index(drop=True)
    b = b.astype(object).where(b.notna(), None).reset_index(drop=True)
    return a.equals(b)


def selfcheck(d: pd.DataFrame, full: pd.DataFrame, rng: random.Random) -> list[str]:
    """No-repaint (truncate at random days: earlier rows must not change) + streaming parity."""
    cfg = _G["cfg"]
    fails = []
    n = len(d)
    if n < 40:
        return fails
    for cut in sorted(rng.sample(range(30, n), k=min(3, n - 30))):
        part = IO.eod_flags(d.iloc[:cut + 1].copy(), cfg, _G["calendar"], _G["mw_daily"])
        for f in IO.OUTCOLS_ALL:                         # v2.4.3: incl. STAIRCASE_VOL_WARN and STEP
            if not _same(full[f].iloc[:cut + 1], part[f]):
                fails.append(f"repaint:{f}@{d.date.iloc[cut].date()}")
    tr = cfg.tracker(d.symbol.iloc[0], calendar=_G["calendar"])
    got = pd.DataFrame([tr.update_eod(r) for r in d.to_dict("records")])
    for col in ("circuit_locked_dir", "staircase_state", "chronic_illiquid", "step_state", "step_staircase"):
        if not _same(got[col], full[col]):
            fails.append(f"stream:{col}")
    return fails


def eod_stock_worker(args):
    path, outdir, do_check, seed = args
    t0 = time.time()
    try:
        d = IO.load_eod(path)
        if len(d) < 2:
            return {"symbol": Path(path).stem, "status": "too_short"}, None, None, [], None
        o = IO.eod_flags(d, _G["cfg"], _G["calendar"], _G["mw_daily"])
        sym = o.symbol.iloc[0]
        keep = ["symbol", "date"] + [c for c in ("exchange", "close", "volume") if c in o.columns] + IO.OUTCOLS_ALL
        view = o[keep].copy()
        view.to_csv(Path(outdir) / f"{sym}.csv", index=False, date_format="%Y-%m-%d")
        summ = {"symbol": sym, "status": "ok", "rows": len(o), "first": o.date.min().date(), "last": o.date.max().date()}
        for f in IO.OUTCOLS_ALL:
            for val, cnt in o[f].value_counts().items():
                if val not in ("", "NO"):
                    summ[f"{f}={val}"] = int(cnt)
        last = o.iloc[-1]
        summ.update({f"last_{f}": last[f] for f in OUTCOLS})
        fails = selfcheck(d, o, random.Random(seed)) if do_check else []
        summ["selfcheck"] = ("FAIL:" + ";".join(fails)) if fails else ("ok" if do_check else "skipped")
        summ["secs"] = round(time.time() - t0, 2)
        # The per-symbol CSV is already written above. Returning the full
        # multi-year frame through multiprocessing can exhaust memory while
        # pickling it; parent process aggregates the saved files instead.
        return summ, None, IO.staircase_episodes(o), fails, IO.step_episodes(o)
    except Exception as e:  # noqa: BLE001
        return {"symbol": Path(path).stem, "status": f"error: {type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=3)}, None, None, [], None


def eod_index_worker(args):
    path, outdir = args
    try:
        d = IO.load_eod(path)
        name = Path(path).stem
        mw = _G["mw_daily"]
        if mw is not None:
            d = d.merge(mw[["date", "mwcb_level", "mwcb_dir"]], on="date", how="left")
        d = C.four_flag_columns(d, mode="eod")
        for f in ("PRICE_BAND", "CIRCUIT", "STAIRCASE", C.GATE_COLUMN):
            d[f] = "NA"          # indices have no band, no circuit, no staircase and are not traded
        view = d[["date", "close"] + OUTCOLS]
        view.to_csv(Path(outdir) / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        return {"index": name, "status": "ok", "rows": len(view), "mwcb_days": int((view.MWCB != "").sum()),
                "first": d.date.min().date(), "last": d.date.max().date()}
    except Exception as e:  # noqa: BLE001
        return {"index": Path(path).stem, "status": f"error: {type(e).__name__}: {e}"}


def intraday_worker(args):
    path, eod_path, outdir = args
    t0 = time.time()
    try:
        b = IO.load_intraday(path)
        sym = b.symbol.iloc[0]
        e = IO.load_eod(eod_path) if eod_path and Path(eod_path).exists() else None
        f = IO.intraday_flags(b, _G["cfg"], e, _G["calendar"], _G["mw_intraday"])
        view = f[["symbol", "date", "close"] + OUTCOLS]
        view.to_csv(Path(outdir) / f"{sym}.csv.gz", index=False, compression="gzip")
        r = {"symbol": sym, "status": "ok", "bars": len(view), "sessions": int(view.date.dt.normalize().nunique()),
             "eod_used": e is not None, "secs": round(time.time() - t0, 1)}
        for fl in ("CIRCUIT", "STAIRCASE", "MWCB", C.GATE_COLUMN):
            for val, cnt in view[fl].value_counts().items():
                if val not in ("", "NA", "NO"):
                    r[f"{fl}={val}"] = int(cnt)
        return r
    except Exception as e:  # noqa: BLE001
        return {"symbol": Path(path).stem, "status": f"error: {type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=3)}


def main():
    ap = argparse.ArgumentParser(description="Four flags + TRADE_BLOCKED for every stock and index (causal).")
    ap.add_argument("--config", default=None, help="config JSON (default: qbeast_flags_config.json next to this file)")
    ap.add_argument("--data", default=None, help="data folder (default: paths.data_dir in the config)")
    ap.add_argument("--out", default=None, help="output folder (default: <data>\\_four_flags_out)")
    ap.add_argument("--workers", type=int, default=None, help="processes (default: run.workers in the config)")
    ap.add_argument("--check-every", type=int, default=None, help="self-check 1 in N stocks, 0 = off (default: config)")
    ap.add_argument("--intraday", action="store_true", help="also process the intraday folder")
    ap.add_argument("--limit", type=int, default=0, help="first N stock files only (smoke test)")
    ap.add_argument("--exclude-stock-files", nargs="*", default=[],
                    help="exact CSV filenames in the stock input folder to skip (for example, an index file mixed into stock data)")
    ap.add_argument("--include-index-files", nargs="*", default=None,
                    help="exact CSV filenames in the index input folder to process; default processes every CSV")
    a = ap.parse_args()

    cfg = load_config(a.config)
    data = cfg.data_dir(a.data)
    if not data.exists():
        sys.exit(f"ERROR: data folder not found: {data}  (use --data or set paths.data_dir in the config)")
    workers = a.workers or cfg.run["workers"]
    check_every = cfg.run["check_every"] if a.check_every is None else a.check_every
    out = cfg.output_dir(data, "_four_flags_out", a.out)
    for sub in ("eod_stocks", "eod_indices", "intraday_stocks"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def say(s=""):
        print(s, flush=True)
        lines.append(str(s))

    t_all = time.time()
    say(f"QBEAST four-flag runner | circuit_liquidity_flags v{C.__version__} | pandas {pd.__version__} | workers {workers}")
    say(cfg.summary())
    say(f"data={data}\nout ={out}")

    mkt = IO.load_market(cfg, data, intraday=a.intraday)
    if mkt.mw_daily is not None:
        trig = mkt.mw_daily[mkt.mw_daily.mwcb_triggered]
        say(f"\n[MWCB] indices used: {mkt.indices_used} | trigger days: {len(trig)}")
        for r in trig.itertuples():
            say(f"   {r.date.date()}  {str(r.mwcb_dir).upper()}_{r.mwcb_level}")
    else:
        say("\n[MWCB] no MWCB index file found (paths.mwcb_index_files) - MWCB column will be empty")
    init = (a.config, mkt.calendar, mkt.mw_daily, mkt.mw_intraday)
    ctx = mp_context(cfg)

    def eod_pass(folder, LAB, sub, suf, exclude_files=()):
        files = sorted(folder.glob("*.csv"))
        excluded = {str(name).strip().casefold() for name in exclude_files}
        if excluded:
            files = [p for p in files if p.name.casefold() not in excluded]
            say(f"   excluded input files: {', '.join(sorted(excluded))}")
        if a.limit:
            files = files[: a.limit]
        say(f"\n[EOD {LAB}] {len(files)} files")
        t0 = time.time()
        summaries, episodes, failures, step_eps = [], [], [], []
        jobs = [(str(p), str(out / sub), bool(check_every) and i % check_every == 0, i) for i, p in enumerate(files)]
        with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=init, mp_context=ctx) as ex:
            futs = [ex.submit(eod_stock_worker, j) for j in jobs]
            for k, f in enumerate(as_completed(futs), 1):
                s, v, ep, fl, sep = f.result()
                if sep is not None and len(sep):
                    step_eps.append(sep)
                summaries.append(s)
                if ep is not None and len(ep):
                    episodes.append(ep)
                if fl:
                    failures.append({"symbol": s["symbol"], "fails": ";".join(fl)})
                if k % 200 == 0 or k == len(futs):
                    print(f"   {k}/{len(futs)}  ({time.time() - t0:.0f}s)", flush=True)
        S = pd.DataFrame(summaries).sort_values("symbol")
        S.to_csv(out / f"four_flags_summary{suf}.csv", index=False)
        (pd.concat(episodes, ignore_index=True) if episodes else IO.staircase_episodes(pd.DataFrame(
            {"staircase": [], "date": [], "symbol": []}))).to_csv(out / f"staircase_episodes{suf}.csv", index=False,
                                                                date_format="%Y-%m-%d")
        (pd.concat(step_eps, ignore_index=True) if step_eps else IO.step_episodes(pd.DataFrame())).to_csv(
            out / f"step_episodes{suf}.csv", index=False, date_format="%Y-%m-%d")                 # v2.4.3
        if failures:
            pd.DataFrame(failures).to_csv(out / f"selfcheck_failures{suf}.csv", index=False)
        ok = S[S.status == "ok"] if "status" in S else S
        say(f"   done in {time.time() - t0:.0f}s | ok {len(ok)} | not ok {len(S) - len(ok)}")
        for r in S[S.status != "ok"].head(10).itertuples():
            say(f"   !! {r.symbol}: {r.status}")
        if len(ok):
            counts = {col: Counter() for col in IO.OUTCOLS_ALL}
            last_rows = []
            row_count = 0
            combined = out / f"four_flags_eod_{sub[4:]}_all.csv.gz"
            written_names = {f"{r.symbol}.csv" for r in ok.itertuples()}
            output_paths = sorted(p for p in (out / sub).glob("*.csv") if p.name in written_names)
            with gzip.open(combined, "wt", encoding="utf-8", newline="") as stream:
                first = True
                for path in output_paths:
                    frame = pd.read_csv(path)
                    frame.to_csv(stream, index=False, header=first, date_format="%Y-%m-%d")
                    first = False
                    row_count += len(frame)
                    for col in IO.OUTCOLS_ALL:
                        counts[col].update(frame[col].fillna("").replace("", "(blank)").value_counts().to_dict())
                    last_rows.append(frame.iloc[-1])
            say(f"\n[EOD {LAB}] symbol-days {row_count:,} - value counts per column")
            for fcol in IO.OUTCOLS_ALL:
                vc = counts[fcol].most_common(10)
                say(f"   {fcol:13s} " + " | ".join(f"{k}: {v:,}" for k, v in vc))
            last = pd.DataFrame(last_rows)
            tagged = last[last.STAIRCASE.isin(["CLIMBING", "FALLING"])]
            say(f"\n   STAIRCASE on each stock's last date ({len(tagged)}): " +
                ", ".join(f"{r.symbol}({r.STAIRCASE[0]})" for r in tagged.itertuples()))
            bld = last[last.STAIRCASE == "BUILDING"]
            say(f"   BUILDING on last date ({len(bld)}): " + ", ".join(bld.symbol))
            blk = last[last[C.GATE_COLUMN] != "NO"]
            say(f"   TRADE_BLOCKED on last date ({len(blk)}): " +
                ", ".join(f"{r.symbol}({getattr(r, C.GATE_COLUMN)})" for r in blk.itertuples()))
            nb = row_count - counts[C.GATE_COLUMN].get("NO", 0)
            say(f"   TRADE_BLOCKED stock-days: {nb:,} ({nb / row_count:.2%})")
            n_ep = sum(len(e) for e in episodes)
            say(f"   staircase episodes: {n_ep:,} in {len(episodes)} stocks")
            say(f"   STEP staircase episodes (v2.4.3): {sum(len(e) for e in step_eps):,} in {len(step_eps)} stocks")
            say(f"\n[SELF-CHECK] causality (no-repaint on all output columns + streaming parity): "
                f"{ok.selfcheck.value_counts().to_dict() if 'selfcheck' in ok else 'n/a'}")


    # ---- EOD stocks (and, v2.4.3, ETFs: paths.etfs_eod_subdir; ETF rows use the *_etf rule sections)
    eod_pass(cfg.sub("stocks_eod_subdir", data), "STOCKS", "eod_stocks", "", a.exclude_stock_files)
    etf_sub = cfg.paths.get("etfs_eod_subdir")
    if etf_sub:
        if (data / etf_sub).exists():
            (out / "eod_etfs").mkdir(parents=True, exist_ok=True)
            eod_pass(data / etf_sub, "ETFS", "eod_etfs", "_etfs")
        else:
            say(f"\n[EOD ETFS] folder not found: {data / etf_sub} (paths.etfs_eod_subdir) - skipped")

    # ---- EOD indices
    index_dir = cfg.sub("indices_eod_subdir", data)
    if a.include_index_files is None:
        idx_files = sorted(index_dir.glob("*.csv"))
    else:
        idx_files = [index_dir / name for name in a.include_index_files]
        missing_indices = [p.name for p in idx_files if not p.is_file()]
        if missing_indices:
            sys.exit(f"ERROR: configured index files not found in {index_dir}: {missing_indices}")
    say(f"\n[EOD INDICES] {len(idx_files)} files")
    if idx_files:
        with ProcessPoolExecutor(max_workers=min(workers, len(idx_files)), initializer=_init, initargs=init,
                                 mp_context=ctx) as ex:
            ires = [f.result() for f in as_completed([ex.submit(eod_index_worker, (str(p), str(out / "eod_indices")))
                                                      for p in idx_files])]
        for r in sorted(ires, key=lambda x: x["index"]):
            if r["status"] == "ok":
                say(f"   {r['index']:24s} rows {r['rows']:>6,}  {r['first']}..{r['last']}  MWCB days {r['mwcb_days']}")
            else:
                say(f"   !! {r['index']}: {r['status']}")

    # ---- intraday stocks
    if a.intraday:
        ifiles = sorted(cfg.sub("stocks_intraday_subdir", data).glob("*.csv"))
        eod_dir = cfg.sub("stocks_eod_subdir", data)
        say(f"\n[INTRADAY STOCKS] {len(ifiles)} files | MWCB intraday: "
            f"{'yes' if mkt.mw_intraday is not None else 'NA (no index intraday data)'}")
        if ifiles:
            t1 = time.time()
            jobs = [(str(p), str(eod_dir / p.name), str(out / "intraday_stocks")) for p in ifiles]
            with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), initializer=_init, initargs=init,
                                     mp_context=ctx) as ex:
                res = [f.result() for f in as_completed([ex.submit(intraday_worker, j) for j in jobs])]
            I = pd.DataFrame(res).sort_values("symbol")
            I.to_csv(out / "four_flags_intraday_summary.csv", index=False)
            say(f"   done in {time.time() - t1:.0f}s")
            for r in I.to_dict("records"):
                if r["status"] != "ok":
                    say(f"   !! {r['symbol']}: {r['status']}")
                    continue
                extra = " | ".join(f"{k}: {int(v):,}" for k, v in r.items() if "=" in k and pd.notna(v))
                say(f"   {r['symbol']:12s} bars {r['bars']:>8,} sess {r['sessions']:>5}  {extra or 'no flags'}")

    say(f"\nTotal {time.time() - t_all:.0f}s. Wrote: {out}")
    (out / "four_flags_report.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
