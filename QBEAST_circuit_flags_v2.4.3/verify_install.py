"""
QBEAST AI - verify the bundle on YOUR machine (no real data needed)
====================================================================
Builds a small synthetic data folder shaped exactly like Final_Data (stocks EOD, indices EOD,
intraday), then runs the test suite and EVERY script in the bundle against it and checks
the flags that must come out (a staircase, a falling ladder, chronic illiquidity, a penny
stock, a stitched NSE/BSE series, an MWCB day, intraday freezes and the early block).

Run (PowerShell, in the bundle folder):
    python verify_install.py
    python verify_install.py --real-data "E:\\Downloads\\Final_Data"     # + quick checks on real data
Exit code 0 = everything passed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TICK = 0.05
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"   {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)
    return ok


# ------------------------------------------------------------------ synthetic data
def grid(x: float) -> float:
    return round(round(x / TICK) * TICK, 2)


def gen_stock(pattern: str, p0: float, base_vol: float, seed: int):
    """U/F = upper circuit close-locked / frozen, D/G = lower circuit close-locked / frozen,
    n = normal day, z = single-price day at 0%, g = gap-filled row."""
    rng = np.random.default_rng(seed)
    rows, pc = [], p0
    for ch in pattern:
        gap = 0
        if ch in "UF":
            c = math.floor(pc * 1.05 / TICK + 1e-9) * TICK
            c = round(c, 2)
            if ch == "F":
                o = h = l = c
            else:
                o = grid(pc * 1.01)
                h, l = c, min(o, pc)
            v = base_vol * 0.3
        elif ch in "DG":
            c = round(math.ceil(pc * 0.95 / TICK - 1e-9) * TICK, 2)
            if ch == "G":
                o = h = l = c
            else:
                o = grid(pc * 0.99)
                l, h = c, max(o, pc)
            v = base_vol * 0.3
        elif ch == "J":                                   # v2.4.3: +3% jump on normal volume (STEP event)
            c = grid(pc * 1.03)
            o, h, l = pc, c, pc
            v = base_vol
        elif ch in "zg":
            o = h = l = c = pc
            v = 0.0 if ch == "g" else base_vol * 0.05
            gap = int(ch == "g")
        else:
            step = max(TICK, pc * rng.uniform(0.002, 0.012))
            c = grid(max(TICK * 2, pc + rng.choice([-1, 1]) * step))
            o = grid(pc + rng.uniform(-0.3, 0.3) * abs(c - pc))
            h = grid(max(o, c) + abs(c - pc) * 0.3 + TICK)
            l = grid(max(TICK, min(o, c) - abs(c - pc) * 0.3 - TICK))
            v = base_vol * rng.uniform(0.8, 1.2)
        rows.append(dict(open=o, high=h, low=l, close=c, volume=round(v), gap=gap))
        pc = c
    return rows


def write_eod(path: Path, sym: str, dates, rows, exch="NSE", src="Dhan", exch_series=None, blank_rows=(),
              product_class="EQUITY"):
    recs = []
    for i, (d, r) in enumerate(zip(dates, rows)):
        ex = exch_series[i] if exch_series is not None else exch
        recs.append({"date": d.strftime("%d-%m-%Y"), "open": r["open"], "high": r["high"], "low": r["low"],
                     "close": r["close"], "adj_close": r["close"], "volume": float(r["volume"]),
                     "open_interest": 0.0, "source": src, "exchange": ex, "product_class": product_class,
                     "symbol": sym, "_source": src, "_exchange": ex, "_gap_filled": r["gap"]})
    df = pd.DataFrame(recs)
    for i in blank_rows:                       # blank symbol/source/exchange like real Final_Data rows
        df.loc[i, ["symbol", "source", "exchange"]] = np.nan
    df.to_csv(path, index=False)


def write_intraday(path: Path, dates, rows, tz: bool, bars: int = 30):
    recs = []
    for d, r in zip(dates, rows):
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        frozen = o == h == l == c
        for j in range(bars):
            ts = d + pd.Timedelta(hours=9, minutes=15 + j)
            if frozen:
                bo = bh = bl = bc = c
            elif c == h and c > o and r["volume"] < 1e9:      # close-locked upper day: ramp then pinned
                if j < 10:
                    bc = round(o + (c - o) * (j + 1) / 10 - (TICK if j < 9 else 0), 2)
                    bo, bh, bl = bc, bc, bc
                else:
                    bo = bh = bl = bc = c
            else:
                bc = round(o + (c - o) * (j + 1) / bars, 2)
                bo, bh, bl = bc, min(h, bc + TICK), max(l, bc - TICK)
                bh, bl = max(bh, bc), min(bl, bc)
            stamp = ts.strftime("%Y-%m-%dT%H:%M:%S+05:30") if tz else ts.strftime("%Y-%m-%d %H:%M:%S")
            recs.append({"datetimestamp": stamp, "open": bo, "high": bh, "low": bl, "close": bc,
                         "adj_close": bc, "volume": 100.0, "open_interest": 0.0})
    pd.DataFrame(recs).to_csv(path, index=False)


def build_dataset(root: Path) -> dict:
    n = 400
    dates = pd.bdate_range("2019-01-01", periods=n)
    se = root / "Final_Clean_Stocks_EOD_Data"
    ie = root / "Final_Clean_Indices_EOD_Data"
    si = root / "Final_Clean_Stocks_INTRADAY_Data"
    for p in (se, ie, si):
        p.mkdir(parents=True, exist_ok=True)
    ladder = "UFFUFFUF"
    stair = gen_stock("n" * 300 + ladder + "n" * (n - 300 - len(ladder)), 50.0, 20000, 1)
    fall = gen_stock("n" * 200 + "DGGDGG" + "n" * (n - 206), 80.0, 15000, 2)
    dead = gen_stock("n" * 100 + ("zzzn" * 75) + "n" * (n - 400), 30.0, 5000, 3)
    liquid = gen_stock("n" * n, 1500.0, 2_000_000, 4)
    penny = gen_stock("n" * n, 1.20, 5_000_000, 5)
    switch_pat = list("n" * n)
    switch_pat[150] = "g"
    switch = gen_stock("".join(switch_pat), 200.0, 50000, 6)
    write_eod(se / "STAIR1.csv", "STAIR1", dates, stair)
    write_eod(se / "FALL1.csv", "FALL1", dates, fall, exch="BSE", src="Kite")
    write_eod(se / "DEADSTK.csv", "DEADSTK", dates, dead)
    write_eod(se / "LIQUID1.csv", "LIQUID1", dates, liquid)
    write_eod(se / "PENNY.csv", "PENNY", dates, penny)
    write_eod(se / "SWITCH.csv", "SWITCH", dates, switch,
              exch_series=["NSE" if (i // 40) % 2 == 0 else "BSE" for i in range(n)], blank_rows=(33, 77))
    # v2.4.3: ETF folder -- ETF1 sits flat (single-price, thin) then jumps (STEP staircase); file name ETF1_NSE.csv
    # with blank symbol cells (load_eod must keep ONE symbol); ETF2 is liquid
    ee = root / "Final_ETF_EoD_Data"
    ee.mkdir(parents=True, exist_ok=True)
    etf1 = gen_stock("n" * 250 + "zzzzJ" + "n" * 20 + "zzJ" + "n" * (n - 278), 20.0, 300000, 7)
    etf2 = gen_stock("n" * n, 250.0, 3_000_000, 8)
    write_eod(ee / "ETF1_NSE.csv", "ETF1", dates, etf1, product_class="ETF", blank_rows=(10, 251, 300))
    write_eod(ee / "ETF2_NSE.csv", "ETF2", dates, etf2, product_class="ETF")
    # index with one MWCB day (index position 300: low -12%, close -5%)
    rng = np.random.default_rng(9)
    pc, idx_rows = 10000.0, []
    for i in range(n):
        if i == 300:
            o, low, c = pc * 0.99, pc * 0.88, pc * 0.95
            high = o
        else:
            c = pc * (1 + rng.normal(0, 0.008))
            o = pc * (1 + rng.normal(0, 0.002))
            high, low = max(o, c) * 1.003, min(o, c) * 0.997
        idx_rows.append({"date": dates[i].strftime("%d-%m-%Y"), "open": round(o, 2), "high": round(high, 2),
                         "low": round(low, 2), "close": round(c, 2), "adjusted_close": round(c, 2),
                         "volume": 0, "open_interest": 0})
        pc = c
    pd.DataFrame(idx_rows).to_csv(ie / "Nifty 50.csv", index=False)
    pd.DataFrame(idx_rows).assign(close=lambda x: (x.close * 1.1).round(2)).to_csv(ie / "NIFTY 500.csv", index=False)
    # intraday: STAIR1 sessions 290..320 (tz-aware stamps), LIQUID1 sessions 290..320 (naive stamps)
    rng_days = range(290, 321)
    write_intraday(si / "STAIR1.csv", [dates[i] for i in rng_days], [stair[i] for i in rng_days], tz=True)
    write_intraday(si / "LIQUID1.csv", [dates[i] for i in rng_days], [liquid[i] for i in rng_days], tz=False)
    return {"dates": dates, "tag_day": dates[304], "untag_day": dates[309], "fall_tag_day": dates[204],
            "etf_stale3_day": dates[252], "etf_jump_day": dates[254],
            "mwcb_day": dates[300], "early_day": dates[304], "after_tag_day": dates[305]}


# ------------------------------------------------------------------ helpers
def run(script: str, *args: str, timeout: int = 900) -> tuple[bool, str]:
    cmd = [sys.executable, str(HERE / script), *args]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(HERE))
    out = (p.stdout or "") + (p.stderr or "")
    ok = p.returncode == 0
    if not ok:
        print(f"      command failed ({p.returncode}) after {time.time() - t0:.0f}s: {' '.join(cmd)}\n" +
              "\n".join("      | " + x for x in out.strip().splitlines()[-25:]))
    return ok, out


def csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False, dtype=str)


def main():
    ap = argparse.ArgumentParser(description="Verify the QBEAST circuit flags bundle end to end.")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep", action="store_true", help="keep the synthetic data folder")
    ap.add_argument("--real-data", default=None, help="optional: Final_Data folder for quick real-data checks")
    a = ap.parse_args()

    sys.path.insert(0, str(HERE))
    import circuit_liquidity_flags as C
    print(f"QBEAST bundle verification | circuit_liquidity_flags v{C.__version__} | Python {sys.version.split()[0]} "
          f"| pandas {pd.__version__} | numpy {np.__version__}")
    tmp = Path(tempfile.mkdtemp(prefix="qbeast_verify_"))
    data = tmp / "Final_Data"
    exp = build_dataset(data)
    cfg_path = tmp / "verify_config.json"
    vcfg = {"paths": {"data_dir": str(data), "etfs_eod_subdir": "Final_ETF_EoD_Data"},     # v2.4.3: + ETFs
            "staircase_etf": {"step_jump_pct": 2.5},
            "run": {"workers": a.workers, "check_every": 1, "mp_start_method": "spawn"}}
    if os.environ.get("QBEAST_VERIFY_OVERRIDE"):          # developer hook: inject a broken setting on purpose
        for sec, kv in json.loads(os.environ["QBEAST_VERIFY_OVERRIDE"]).items():
            vcfg.setdefault(sec, {}).update(kv)
    cfg_path.write_text(json.dumps(vcfg))
    print(f"synthetic data: {data}")

    print("\n[1] versions")
    maj = tuple(int(x) for x in pd.__version__.split(".")[:2])
    check("Python >= 3.10", sys.version_info >= (3, 10), sys.version)
    check("pandas >= 2.0", maj >= (2, 0), pd.__version__)

    print("\n[2] config file")
    import flags_config as F
    try:
        cfg = F.load_config()
        check("qbeast_flags_config.json loads", True)
        check("config values valid", cfg.staircase.start_confirm_days >= 1)
    except Exception as e:  # noqa: BLE001
        check("qbeast_flags_config.json loads", False, str(e))

    print("\n[3] unit tests")
    ok, out = run("test_circuit_liquidity_flags.py")
    last = [x for x in out.splitlines() if "passed" in x]
    check("test suite", ok, last[-1] if last else out[-300:])

    D = str(data)
    common = ["--config", str(cfg_path), "--data", D]

    print("\n[4] run_four_flags.py (parallel, spawn, self-check on every stock)")
    ok, out = run("run_four_flags.py", *common, "--intraday", "--check-every", "1")
    check("run_four_flags.py runs", ok)
    o4 = data / "_four_flags_out"
    if ok:
        s = csv(o4 / "four_flags_summary.csv")
        check("all 6 stocks processed", (s.status == "ok").sum() == 6, s[["symbol", "status"]].to_string())
        check("causality self-check ok on every stock", (s.selfcheck == "ok").all(), s[["symbol", "selfcheck"]].to_string())
        st = csv(o4 / "eod_stocks" / "STAIR1.csv").set_index("date")
        td, ud = exp["tag_day"].strftime("%Y-%m-%d"), exp["untag_day"].strftime("%Y-%m-%d")
        prev = exp["dates"][303].strftime("%Y-%m-%d")
        check("STAIR1 tagged CLIMBING on its 5th upper circuit (not before)",
              st.loc[td, "STAIRCASE"] == "CLIMBING" and st.loc[prev, "STAIRCASE"] == "BUILDING",
              f"{prev}={st.loc[prev, 'STAIRCASE']} {td}={st.loc[td, 'STAIRCASE']}")
        check("STAIR1 circuit + band columns", st.loc[td, "CIRCUIT"] == "UPPER" and st.loc[td, "PRICE_BAND"] == "5",
              f"{st.loc[td, 'CIRCUIT']} / {st.loc[td, 'PRICE_BAND']}")
        check("STAIR1 TRADE_BLOCKED while tagged, released after 2 normal days",
              "STAIRCASE" in st.loc[td, "TRADE_BLOCKED"] and st.loc[ud, "STAIRCASE"] == "" and
              st.loc[ud, "TRADE_BLOCKED"] == "NO", f"{st.loc[ud, 'STAIRCASE']!r} {st.loc[ud, 'TRADE_BLOCKED']}")
        fa = csv(o4 / "eod_stocks" / "FALL1.csv").set_index("date")
        check("FALL1 tagged FALLING", fa.loc[exp["fall_tag_day"].strftime("%Y-%m-%d"), "STAIRCASE"] == "FALLING")
        fall_days = fa[fa.STAIRCASE == "FALLING"]
        check("every FALLING day is TRADE_BLOCKED (no buy, no sell, no exit)",
              len(fall_days) > 0 and fall_days.TRADE_BLOCKED.str.contains("STAIRCASE").all(),
              fall_days.TRADE_BLOCKED.to_dict().__repr__()[:200])
        climb_days = st[st.STAIRCASE == "CLIMBING"]
        check("every CLIMBING day is TRADE_BLOCKED (no buy, no sell, no exit)",
              len(climb_days) > 0 and climb_days.TRADE_BLOCKED.str.contains("STAIRCASE").all(),
              climb_days.TRADE_BLOCKED.to_dict().__repr__()[:200])
        de = csv(o4 / "eod_stocks" / "DEADSTK.csv")
        check("DEADSTK blocked as CHRONIC", de.TRADE_BLOCKED.str.contains("CHRONIC").any())
        li = csv(o4 / "eod_stocks" / "LIQUID1.csv")
        md = exp["mwcb_day"].strftime("%Y-%m-%d")
        check("LIQUID1: no circuit / staircase; blocked only on the MWCB day",
              (li.CIRCUIT == "").all() and (li.STAIRCASE == "").all() and
              set(li.loc[li.TRADE_BLOCKED != "NO", "date"]) == {md})
        check("MWCB day flagged LOWER_10 for every stock", (csv(o4 / "four_flags_eod_stocks_all.csv.gz")
                                                             .query("date == @md").MWCB == "LOWER_10").all())
        pe = csv(o4 / "eod_stocks" / "PENNY.csv")
        check("PENNY: 1-tick hits never become a staircase", not pe.STAIRCASE.isin(["CLIMBING", "FALLING"]).any())
        sw = csv(o4 / "eod_stocks" / "SWITCH.csv")
        check("SWITCH (stitched NSE/BSE, blank cells, gap-filled row) processed", len(sw) == 400)
        nx = csv(o4 / "eod_indices" / "Nifty 50.csv")
        check("index file: NA flags + one MWCB day", (nx.STAIRCASE == "NA").all() and (nx.MWCB != "").sum() == 1)
        ist = csv(o4 / "intraday_stocks" / "STAIR1.csv.gz")
        ist["day"] = ist.date.str[:10]
        ed, ad = exp["early_day"].strftime("%Y-%m-%d"), exp["after_tag_day"].strftime("%Y-%m-%d")
        check("intraday STAIR1: freezes at the upper band", (ist.CIRCUIT == "UPPER").any())
        check("intraday STAIR1: EARLY_BLOCK on the 5th ladder day",
              (ist.loc[ist.day == ed, "STAIRCASE"] == "EARLY_BLOCK").any())
        check("intraday STAIR1: CLIMBING all day after the tag",
              (ist.loc[ist.day == ad, "STAIRCASE"] == "CLIMBING").all())
        il = csv(o4 / "intraday_stocks" / "LIQUID1.csv.gz")
        check("intraday LIQUID1 (naive timestamps): no flags", (il.CIRCUIT == "").all() and (il.STAIRCASE == "").all())

    print("\n[5] daily_backtest_loop.py (day-by-day loop vs batch)")
    ok, out = run("daily_backtest_loop.py", *common, "--workers", str(a.workers), "--verify")
    line = [x for x in out.splitlines() if x.startswith("[VERIFY]")]
    check("daily_backtest_loop.py runs", ok)
    counts = []
    if line and "{" in line[0]:
        body = line[0].split("{", 1)[1].rstrip("}").replace("'", "").replace(" ", "")
        counts = [item.split(":")[1] for item in body.split(",") if ":" in item]
    check("daily loop == batch (0 mismatches)", len(counts) == 5 and all(c == "0" for c in counts),
          line[0] if line else "no VERIFY line")
    check("trackers_state.pkl written", (data / "_daily_loop_out" / "trackers_state.pkl").exists())

    print("\n[6] flags_for_one_day.py")
    ok, out = run("flags_for_one_day.py", *common, "--symbol", "STAIR1", "--date", exp["tag_day"].strftime("%Y-%m-%d"))
    check("one day: STAIR1 CLIMBING + blocked", ok and "CLIMBING" in out and "do NOT buy" in out)
    ok, out = run("flags_for_one_day.py", *common, "--symbol", "FALL1", "--date", exp["fall_tag_day"].strftime("%Y-%m-%d"))
    check("one day: FALL1 FALLING + blocked", ok and "FALLING" in out and "do NOT buy" in out)
    ok, out = run("flags_for_one_day.py", *common, "--symbol", "STAIR1",
                  "--from", exp["dates"][296].strftime("%Y-%m-%d"), "--to", exp["dates"][312].strftime("%Y-%m-%d"),
                  "--verify")
    check("daily range: independent calls == batch", ok and "[VERIFY] daily independent calls == full-history batch: True" in out)

    print("\n[7] example_daily_usage.py + call_four_functions.py")
    ok, out = run("example_daily_usage.py", *common, "--symbol", "STAIR1", "--check-days", "40")
    check("literal loop == streaming == batch", ok and "streaming == batch: True" in out)
    ok, out = run("call_four_functions.py", *common, "--symbol", "STAIR1")
    check("call_four_functions.py runs", ok and "FLAG 4" in out)

    print("\n[7b] v2.4.2 volume rules (real volume in tag / untag, missing volume)")
    import circuit_liquidity_flags as C
    check("library is v2.4.2 or later", tuple(int(x) for x in C.__version__.split(".")) >= (2, 4, 2), C.__version__)
    leg = F.legacy_v241_config()
    check("LEGACY_V241 preset loads (v2.4.1 behaviour available)",
          leg.circuit.volume_quality is False and leg.staircase.tag_vol_frac is None)
    if ok:
        heads = list(csv(o4 / "eod_stocks" / "STAIR1.csv").columns)
        check("run_four_flags EOD output has STAIRCASE_VOL_WARN", C.VOL_WARN_COLUMN in heads, str(heads))

    def _mk(vols):
        rows, c = [], 100.0
        for k in range(30):
            c2 = round(c * (1 + (0.004 if k % 2 else -0.003)), 2)
            rows.append(dict(open=c, high=max(c, c2) * 1.004, low=min(c, c2) * 0.996, close=c2, volume=10000.0))
            c = c2
        for v in vols:
            c2 = round(c * 1.05 / 0.05) * 0.05
            rows.append(dict(open=round(c * 1.01, 2), high=c2, low=c, close=c2, volume=v))
            c = c2
        d = pd.DataFrame(rows)
        d.insert(0, "date", pd.bdate_range("2024-01-01", periods=len(d)))
        d.insert(0, "symbol", "V")
        return d

    import flags_io as IO
    heavy = IO.eod_flags(_mk([30000.0] * 6), F.load_config())
    check("heavy-volume ladder NOT tagged (BUILDING, LADDER_HIGH_VOL)",
          heavy.STAIRCASE.iloc[-1] == "BUILDING" and heavy[C.VOL_WARN_COLUMN].iloc[-1] == "LADDER_HIGH_VOL",
          heavy[["STAIRCASE", C.VOL_WARN_COLUMN]].tail(3).to_string())
    check("heavy-volume ladder tagged under LEGACY_V241", IO.eod_flags(_mk([30000.0] * 6), leg).STAIRCASE.iloc[-1] == "CLIMBING")
    thin = IO.eod_flags(_mk([800.0] * 5), F.load_config())
    check("thin-volume ladder tagged on the 5th day", thin.STAIRCASE.iloc[-1] == "CLIMBING" and thin.STAIRCASE.iloc[-2] == "BUILDING")
    novol = IO.eod_flags(_mk([float("nan")] * 5), F.load_config())
    check("missing-volume ladder tagged on OHLC with TAGGED_NO_VOL",
          novol.STAIRCASE.iloc[-1] == "CLIMBING" and novol[C.VOL_WARN_COLUMN].iloc[-1] == "TAGGED_NO_VOL")

    print("\n[7c] v2.4.3 STEP staircase (illiquid 'flat, then jump'; stocks and ETFs, no band needed)")
    check("library is v2.4.3", C.__version__ == "2.4.3", C.__version__)
    l2 = F.legacy_v242_config()
    check("LEGACY_V242 preset loads (v2.4.2 behaviour available)", l2.staircase.step_enabled is False
          and F.legacy_v241_config().staircase.step_enabled is False)
    if ok:
        heads = list(csv(o4 / "eod_stocks" / "STAIR1.csv").columns)
        check("run_four_flags EOD output has STEP", C.STEP_COLUMN in heads, str(heads))
        de = csv(o4 / "eod_stocks" / "DEADSTK.csv")
        check("DEADSTK (single-price runs) also gets a STEP tag", de.STEP.isin(["FLAT", "CLIMBING", "FALLING"]).any())

    def _st(tail, vol=50000.0, sym="ETFX"):
        rows, c = [], 100.0
        for k in range(30):
            c2 = round(c * (1 + (0.006 if k % 2 else -0.005)), 2)
            rows.append(dict(open=c, high=max(c, c2) * 1.003, low=min(c, c2) * 0.997, close=c2, volume=vol))
            c = c2
        for ch in tail:
            if ch == "s":                                             # stale: same close, single price, thin
                rows.append(dict(open=c, high=c, low=c, close=c, volume=vol * 0.02))
            elif ch == "q":                                           # same close but normal volume (liquid)
                rows.append(dict(open=c, high=c * 1.004, low=c * 0.996, close=c, volume=vol))
            else:                                                     # J / K jump 3%, n normal
                c2 = round(c * {"J": 1.03, "K": 0.97, "n": 1.006}[ch], 2)
                rows.append(dict(open=c, high=max(c, c2), low=min(c, c2), close=c2, volume=vol))
                c = c2
        d = pd.DataFrame(rows)
        d.insert(0, "date", pd.bdate_range("2024-01-01", periods=len(d)))
        d.insert(0, "symbol", sym)
        return d

    up = IO.eod_flags(_st("sssJnn"), F.load_config())
    w = up.iloc[30:].reset_index(drop=True)
    check("STEP: FLAT tag on the 3rd stale bar, CLIMBING after a +3% jump",
          list(w.STEP) == ["BUILDING", "BUILDING", "FLAT", "CLIMBING", "CLIMBING", ""], str(list(w.STEP)))
    check("STEP: TRADE_BLOCKED while tagged (no buy, no sell, no exit), released after 2 normal days",
          all("STEP_STAIRCASE" in x for x in w.TRADE_BLOCKED.iloc[2:5]) and w.TRADE_BLOCKED.iloc[5] == "NO",
          str(list(w.TRADE_BLOCKED)))
    dn = IO.eod_flags(_st("sssKnn"), F.load_config()).iloc[30:]
    check("STEP: falling step tagged FALLING and blocked", dn.STEP.iloc[3] == "FALLING"
          and "STEP_STAIRCASE" in dn.TRADE_BLOCKED.iloc[3])
    lq = IO.eod_flags(_st("qqqqqqnn"), F.load_config())
    check("STEP: unchanged close on normal volume (liquid) is never stale", (lq.STEP == "").all())
    check("STEP: off under LEGACY_V242", (IO.eod_flags(_st("sssJnn"), l2).STEP == "").all())
    import copy as _cp
    ex = _cp.deepcopy(F.load_config())
    ex.staircase = C.StaircaseParams(**{**ex.staircase.__dict__, "step_exempt_pattern": "LIQUID"})
    check("STEP: step_exempt_pattern exempts LIQUIDBEES-style symbols",
          (IO.eod_flags(_st("sssJnn", sym="LIQUIDBEES"), ex).STEP == "").all())

    print("\n[7d] v2.4.3 asset classes, ETF folder, directions, volume rule, corporate actions")
    if ok:
        e1p = o4 / "eod_etfs" / "ETF1.csv"
        check("run_four_flags processed the ETF folder (eod_etfs, *_etfs summaries)",
              e1p.exists() and (o4 / "four_flags_summary_etfs.csv").exists() and (o4 / "step_episodes_etfs.csv").exists())
        if e1p.exists():
            e1 = csv(e1p)
            check("ETF1 file with blank symbol cells stays ONE symbol (400 rows)", len(e1) == 400 and set(e1.symbol) == {"ETF1"})
            check("ETF rows use the ETF rule set (ASSET_CLASS = ETF)", (e1.ASSET_CLASS == "ETF").all())
            e1 = e1.set_index("date")
            d3, dj = exp["etf_stale3_day"].strftime("%Y-%m-%d"), exp["etf_jump_day"].strftime("%Y-%m-%d")
            check("ETF1: STEP FLAT tag on the 3rd stale day, CLIMBING on the jump, blocked",
                  e1.loc[d3, "STEP"] == "FLAT" and e1.loc[dj, "STEP"] == "CLIMBING"
                  and "STEP_STAIRCASE" in e1.loc[dj, "TRADE_BLOCKED"], str(e1.loc[d3:dj, ["STEP", "TRADE_BLOCKED"]]))
            e2 = csv(o4 / "eod_etfs" / "ETF2.csv")
            check("ETF2 (liquid): never STEP-tagged", (e2.STEP.fillna("") == "").all())
        sts = csv(o4 / "eod_stocks" / "STAIR1.csv")
        check("stock rows use the STOCK rule set (ASSET_CLASS = STOCK)", (sts.ASSET_CLASS == "STOCK").all())
        sm = csv(o4 / "four_flags_summary_etfs.csv")
        check("self-check ok on every ETF", (sm.selfcheck == "ok").all(), sm[["symbol", "selfcheck"]].to_string())
    vc = F.load_config(str(cfg_path))
    check("staircase_etf section reaches the ETF rule set",
          vc.staircase.for_class("ETF").step_jump_pct == 2.5 and vc.staircase.step_jump_pct == 2.0)
    l2 = F.legacy_v242_config()
    check("LEGACY_V242 switches every 2.4.3 rule off", (not l2.staircase.step_enabled) and l2.circuit.ca_jump_pct is None
          and not l2.staircase.zero_volume_as_missing and l2.staircase.vol_reliability_min is None)
    sp = C.StaircaseParams(start_confirm_days_falling=3)
    fall = IO.eod_flags(pd.DataFrame([dict(symbol="Q", date=d, **{k: r[k] for k in ("open", "high", "low", "close", "volume")})
                                      for d, r in zip(pd.bdate_range("2024-01-01", periods=36),
                                                      gen_stock("n" * 30 + "DDDDnn", 80.0, 15000, 2))]),
                        type(F.load_config())(**{**F.load_config().__dict__, "staircase": sp}))
    check("falling-specific S = 3: FALLING tag on the 3rd lower-circuit day",
          list(fall.STAIRCASE.iloc[30:34]) == ["BUILDING", "BUILDING", "FALLING", "FALLING"], str(list(fall.STAIRCASE.iloc[30:34])))
    try:
        import importlib
        import shutil as _sh
        pk = tmp / "pkgtest" / "qbeast_flags_pkg"
        pk.mkdir(parents=True)
        for f_ in list(HERE.glob("*.py")) + list(HERE.glob("*.json")):
            _sh.copy(f_, pk / f_.name)
        r_ = subprocess.run([sys.executable, "-c", "import qbeast_flags_pkg as Q; print(Q.__version__)"],
                            cwd=str(pk.parent), capture_output=True, text=True)
        check("bundle imports as a package (for the qbeast_exec wheel)", r_.returncode == 0 and
              r_.stdout.strip() == C.__version__, r_.stderr[-300:])
    except Exception as e:  # noqa: BLE001
        check("bundle imports as a package (for the qbeast_exec wheel)", False, str(e))

    if a.real_data:
        print(f"\n[8] quick checks on real data: {a.real_data}")
        env = dict(os.environ, QBEAST_DATA=a.real_data)
        p = subprocess.run([sys.executable, str(HERE / "test_circuit_liquidity_flags.py")], capture_output=True,
                           text=True, env=env, cwd=str(HERE))
        check("test suite incl. real-data tests", p.returncode == 0, (p.stdout or "")[-200:])
        rout = tmp / "real_out"
        ok, out = run("run_four_flags.py", "--config", str(cfg_path), "--data", a.real_data, "--out", str(rout),
                      "--limit", "20", "--check-every", "1")
        sc = [x for x in out.splitlines() if x.startswith("[SELF-CHECK]")]
        check("run_four_flags.py on up to 20 real stocks (all ok, self-check ok)",
              ok and "| not ok 0" in out and bool(sc) and "FAIL" not in sc[0], sc[0] if sc else out[-300:])

    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\nRESULT: {n_ok}/{len(RESULTS)} checks passed")
    if a.keep:
        print(f"synthetic data kept at {data}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if n_ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
