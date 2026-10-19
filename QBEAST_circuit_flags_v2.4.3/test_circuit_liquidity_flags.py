"""
Tests for circuit_liquidity_flags v2 (v2.4.3: + STEP staircase tests at the end).
Run:  python -m pytest -q test_circuit_liquidity_flags.py      (or: python test_circuit_liquidity_flags.py)
Real-data tests auto-skip unless QBEAST_DATA points at Final_Data
(e.g. set QBEAST_DATA=E:\\Downloads\\Final_Data).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit_liquidity_flags as C  # noqa: E402

DATA = os.environ.get("QBEAST_DATA")


# ----------------------------------------------------------------- helpers
def make_eod(pattern: str, sym="X", start="2024-01-01", p0=100.0, band=5.0, base_vol=10000.0,
             seed=0, exchange="NSE", source="Dhan") -> pd.DataFrame:
    """U/D = upper/lower circuit day closing at the high/low (close_locked),
    F/G = frozen O=H=L=C upper/lower, n = normal day, t = thin normal day,
    z = single-price 0% day, g = gap-filled row."""
    rng = np.random.default_rng(seed)
    rows, c = [], p0
    for ch in "n" * 30 + pattern:
        pc = c
        if ch in "UF":
            c = round(pc * (1 + band / 100) / 0.05) * 0.05 if pc > 50 else np.floor(pc * (1 + band / 100) / 0.05) * 0.05
            o = c if ch == "F" else round(pc * 1.01, 2)
            h, l, v = c, (c if ch == "F" else min(o, pc)), base_vol * 0.3
        elif ch in "DG":
            c = round(pc * (1 - band / 100) / 0.05) * 0.05 if pc > 50 else np.ceil(pc * (1 - band / 100) / 0.05) * 0.05
            o = c if ch == "G" else round(pc * 0.99, 2)
            l, h, v = c, (c if ch == "G" else max(o, pc)), base_vol * 0.3
        elif ch == "z":
            o = h = l = c = pc
            v = base_vol * 0.05
        elif ch == "g":
            o = h = l = c = pc
            v = 0.0
        else:
            r = rng.uniform(-0.015, 0.015)
            c = round(pc * (1 + r), 2)
            o = round(pc * (1 + rng.uniform(-0.005, 0.005)), 2)
            h = round(max(o, c) * 1.006, 2)
            l = round(min(o, c) * 0.994, 2)
            v = base_vol * (0.05 if ch == "t" else rng.uniform(0.8, 1.2))
        rows.append(dict(open=o, high=h, low=l, close=c, volume=v, _gap_filled=int(ch == "g")))
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range(start, periods=len(df)))
    df.insert(0, "symbol", sym)
    df["exchange"], df["source"] = exchange, source
    return df


def eod_chain(df, sp=None, chp=None, **kw):
    c = C.compute_circuit_hit_flag(df, mode="eod", **kw)
    s = C.compute_staircase_flag(c, sp)
    return C.compute_chronic_illiquidity_flag(s, chp)


# v2.4.2: the parameter set that reproduces v2.4.1 exactly
LEGACY_SP = C.StaircaseParams(vol_avg_days=1, tag_vol_frac=None, missing_volume_fallback=False,
                              step_enabled=False, zero_volume_as_missing=False,
                              vol_reliability_min=None)    # v2.4.3: none of the 2.4.3 rules existed in 2.4.1
LEGACY_CP = C.CircuitParams(volume_quality=False, ca_jump_pct=None)
LEGACY_CHP = C.ChronicParams(missing_volume_as_no_trade=True)
LEGACY_CK = {"chp": LEGACY_CHP, "circuit_params": LEGACY_CP}


def norm(df):
    """Make None/NaN comparable across pandas string/object dtypes."""
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def tail(df, n):
    return df.iloc[30:30 + n] if n else df.iloc[30:]


# ----------------------------------------------------------------- v1 regressions
def test_band_nan_not_asymmetric_and_tightening():
    df = pd.DataFrame(dict(symbol="A", date=pd.bdate_range("2024-01-01", periods=5),
                           upper_band_pct=[np.nan, np.inf, np.nan, 20, 10],
                           lower_band_pct=[np.nan, np.inf, np.nan, 20, 10]))
    o = C.compute_price_band_flag(df)
    assert not o.band_asymmetric.iloc[0]
    assert o.band_tightened.tolist() == [False, False, False, True, True]  # inf->20 across a gap, 20->10


def test_tick_floored_circuit_detected():
    # prev 1.70, 5% band floored to tick -> 1.75 (+2.94%), frozen
    df = make_eod("", p0=1.70)
    df[["open", "high", "low", "close"]] = (df[["open", "high", "low", "close"]] / 0.05).round() * 0.05  # raw 0.05-tick era
    last = df.iloc[-1].copy()
    pc = last.close
    lim = np.floor(pc * 1.05 / 0.05) * 0.05
    row = dict(symbol="X", date=df.date.iloc[-1] + pd.offsets.BDay(), open=lim, high=lim, low=lim, close=lim,
               volume=100.0, _gap_filled=0, exchange="NSE", source="Dhan", upper_band_pct=5.0, lower_band_pct=5.0)
    d2 = pd.concat([df.assign(upper_band_pct=5.0, lower_band_pct=5.0), pd.DataFrame([row])], ignore_index=True)
    o = C.compute_circuit_hit_flag(d2)
    assert o.circuit_locked_dir.iloc[-1] == "upper"


def test_long_ladder_not_starved():
    out = eod_chain(make_eod("U" * 40))
    t = tail(out, 40)
    assert t.ladder_day.all()
    assert t.staircase.iloc[4:].all() and not t.staircase.iloc[:4].any()


# ----------------------------------------------------------------- staircase semantics (causal)
def test_no_retro_marking_and_tag_on_S():
    t = tail(eod_chain(make_eod("UUUUU")), 5)
    assert t.staircase.tolist() == [False, False, False, False, True]
    assert t.staircase_state.tolist() == ["BUILDING"] * 4 + ["CONFIRMED"]
    assert t.staircase_early_block_dir.iloc[3] == "upper"


def test_E_reached_ends_run_and_grace_days_stay_tagged():
    t = tail(eod_chain(make_eod("UUUUUU" + "n" + "UU" + "nn" + "n")), 0)
    tagged = t.staircase.tolist()[:12]
    assert tagged == [False] * 4 + [True] * 2 + [True] + [True] * 2 + [True, False, False]
    assert t.staircase_state.iloc[9] == "COOLING" and t.staircase_state.iloc[10] == "DORMANT"


def test_thin_volume_days_do_not_untag():
    # v2.4.1 semantics (day's own volume): the 2nd normal day untags
    t = tail(eod_chain(make_eod("UUUUU" + "tttt" + "nnn"), LEGACY_SP, **LEGACY_CK), 0)
    assert t.staircase.iloc[4:9].all()           # thin days = OTHER, keep tag
    assert not t.staircase.iloc[10]
    # v2.4.2 default: NORMAL needs the 3-day average of real volume >= 0.5 x baseline -> after 4 thin days the
    # 1st normal day still averages ~0.37x (OTHER), the 2nd and 3rd count -> untag one day later
    t = tail(eod_chain(make_eod("UUUUU" + "tttt" + "nnn")), 0)
    assert t.staircase.iloc[4:9].all()
    assert t.day_class.iloc[9] == "OTHER" and t.staircase.iloc[10] and not t.staircase.iloc[11]


def test_direction_flip_stays_tagged_new_event():
    t = tail(eod_chain(make_eod("UUUUU" + "DD")), 0)
    assert t.staircase.iloc[4:7].all()
    assert t.staircase_dir.iloc[6] == "falling"
    assert t.staircase_event_id.iloc[6] == t.staircase_event_id.iloc[4] + 1


def test_unknown_gap_filled_holds_state():
    t = tail(eod_chain(make_eod("UUU" + "g" + "UU")), 0)
    assert t.day_class.iloc[3] == "UNKNOWN"
    assert t.staircase.iloc[5] and t.ladder_run_len.iloc[5] == 5


def test_strict_mode_misses_wick_days():
    t = tail(eod_chain(make_eod("FFFUFFF"), lock_mode="strict"), 0)
    assert not t.staircase.any()                  # U (wick) breaks the strict run
    t2 = tail(eod_chain(make_eod("FFFUFFF")), 0)
    assert t2.staircase.iloc[4:].all()


def test_chronic_single_price_tags_and_releases():
    t = tail(eod_chain(make_eod("z" * 20 + "n" * 60)), 0)
    assert t.chronic_illiquid.any()
    assert not t.chronic_illiquid.iloc[-1]


def test_exchange_switch_unknown():
    a = make_eod("n" * 5)
    a.loc[a.index[-2:], "exchange"] = "BSE"
    o = C.compute_circuit_hit_flag(a)
    assert o.data_unknown.iloc[-2] and not o.data_unknown.iloc[-1]


# ----------------------------------------------------------------- causality guarantees
def _universe():
    pats = ["n" * 20 + "UUUUUUU" + "nnn" + "DDDDDD" + "tt" + "nnnn",
            "zzznzzzzznnnzzzz" * 3,
            "UUUUnUUUUUUnnDDnn" * 2,
            "n" * 60]
    return pd.concat([make_eod(p, sym=f"S{i}", seed=i) for i, p in enumerate(pats)], ignore_index=True)


def test_no_repaint_truncation():
    u = _universe()
    full = eod_chain(u).set_index(["symbol", "date"])
    cols = ["circuit_locked_dir", "band_est_next", "staircase_state", "staircase", "ladder_run_len",
            "chronic_illiquid", "vol_baseline"]
    dates = sorted(u.date.unique())
    for cut in dates[25::7]:
        part = eod_chain(u[u.date <= cut]).set_index(["symbol", "date"])
        a = full.loc[part.index, cols]
        pd.testing.assert_frame_equal(norm(a), norm(part[cols]), check_dtype=False)


def test_streaming_parity_eod():
    u = _universe()
    batch = eod_chain(u)
    keys = ["circuit_locked_dir", "staircase_state", "staircase", "ladder_run_len", "normal_day_count",
            "chronic_illiquid", "band_est_next"]
    for s, g in u.groupby("symbol"):
        tr = C.CircuitLiquidityTracker(s)
        got = pd.DataFrame([tr.update_eod(r) for r in g.to_dict("records")])
        exp = batch[batch.symbol == s][keys].reset_index(drop=True)
        pd.testing.assert_frame_equal(norm(got[keys]), norm(exp), check_dtype=False)


# ----------------------------------------------------------------- intraday
def make_intraday(days: list[str], sym="X", pc0=100.0, band=5.0, bars=12):
    """days: 'n' normal session, 'U' pinned at upper band from open."""
    rows, pc = [], pc0
    d0 = pd.Timestamp("2024-03-01")
    rng = np.random.default_rng(1)
    for k, ch in enumerate(days):
        day = d0 + pd.offsets.BDay(k)
        lim = round(pc * (1 + band / 100), 2)
        px = pc
        for j in range(bars):
            ts = day + pd.Timedelta(hours=9, minutes=15 + j)
            if ch == "U":
                o = h = l = c = lim
                v = 5.0
            else:
                o = px
                c = round(px * (1 + rng.uniform(-0.002, 0.002)), 2)
                h, l, v = max(o, c) * 1.001, min(o, c) * 0.999, 1000.0
                px = c
            rows.append(dict(symbol=sym, date=ts, open=o, high=h, low=l, close=c, volume=v))
        pc = rows[-1]["close"]
    return pd.DataFrame(rows)


def test_intraday_run_resets_each_session():
    b = make_intraday(["n"] * 3 + ["U", "U"])
    o = C.compute_circuit_hit_flag(b, mode="intraday")
    first_bar_day5 = o[o.date == o.date.dt.normalize().max() + pd.Timedelta(hours=9, minutes=15)]
    assert int(first_bar_day5.pinned_run_len.iloc[0]) == 1


def test_intraday_early_block_and_parity():
    b = make_intraday(["n"] * 25 + ["U"] * 6 + ["n"] * 3)
    ci = C.compute_circuit_hit_flag(b, mode="intraday")
    st = C.compute_staircase_flag(ci, mode="intraday")
    d = st.date.dt.normalize()
    days = sorted(d.unique())
    day5 = st[d == days[29]]                        # 5th locked session: yesterday run==S-1
    assert day5.early_block.iloc[3:].all() and not day5.early_block.iloc[:2].any()
    day6 = st[d == days[30]]
    assert day6.eod_staircase_prev.all()           # tagged at close of 5th session
    tr = C.CircuitLiquidityTracker("X")
    got = pd.DataFrame([tr.update_intraday(r) for r in b.to_dict("records")])
    for k in ("pinned_run_len", "intraday_freeze", "staircase_intraday", "early_block"):
        assert got[k].tolist() == st[k].tolist(), k


# ----------------------------------------------------------------- MWCB
def test_mwcb_intraday_halt_window():
    ts = pd.date_range("2020-03-13 09:15", periods=60, freq="1min")
    close = np.r_[[9590 * 0.95] * 5, [9590 * 0.899] * 55]
    df = pd.DataFrame(dict(index_name="NIFTY50", date=ts, open=close, high=close, low=close, close=close,
                           prev_close=9590.0))
    o = C.compute_mwcb_flag(df, mode="intraday", basis="prev_close")
    trig_i = int(np.flatnonzero(o.mwcb_trigger_level.to_numpy() == 10)[0])
    assert trig_i == 5
    assert o.mwcb_halt_active.iloc[6:51].all() and not o.mwcb_halt_active.iloc[51]
    assert o.mwcb_reopen_auction.iloc[51:].all()


def test_mwcb_aggregate_no_duplication():
    idx = pd.DataFrame(dict(index_name=["NIFTY50", "SENSEX"] * 2,
                            date=np.repeat(pd.to_datetime(["2020-03-12", "2020-03-13"]), 2),
                            close=[9590., 32778., 9955., 34103.], prev_close=[10458., 35697., 9590., 32778.],
                            high=[10040., 35000., 10159., 34800.], low=[9508., 32400., 8555., 29388.]))
    agg = C.aggregate_mwcb_by_date(C.compute_mwcb_flag(idx, basis="prev_close"))
    assert len(agg) == 2 and agg.mwcb_level.tolist() == [0, 10]
    assert pd.isna(agg.mwcb_dir.iloc[0]) and agg.mwcb_dir.iloc[1] == "lower"


def test_exclusion_tables_eod_and_intraday():
    k = eod_chain(make_eod("UUUUU" + "nn" + "n"))
    mw = pd.DataFrame(dict(date=[k.date.iloc[5]], mwcb_level=[10], mwcb_dir=["lower"], mwcb_triggered=[True]))
    x = C.build_universe_exclusion_table(k, mw)
    assert x.trade_blocked.iloc[34] and x.block_reason.iloc[34] == "staircase"
    assert x.trade_blocked.iloc[5] and x.block_reason.iloc[5] == "mwcb_day"
    assert not x.trade_blocked.iloc[-1]
    # intraday: halt window blocks everything, open locked at upper blocks only buys
    b = make_intraday(["n"] * 3, bars=60)
    ci = C.compute_circuit_hit_flag(b, mode="intraday")
    st = C.compute_staircase_flag(ci, mode="intraday")
    day = st.date.dt.normalize().max()
    ts = pd.date_range(day + pd.Timedelta(hours=9, minutes=15), periods=60, freq="1min")
    lvl = np.r_[[100.0] * 5, [89.0] * 55]
    idx = pd.DataFrame(dict(index_name="NIFTY50", date=ts, open=lvl, high=lvl, low=lvl, close=lvl, prev_close=100.0))
    mwi = C.aggregate_mwcb_by_date(C.compute_mwcb_flag(idx, mode="intraday", basis="prev_close"))
    xi = C.build_universe_exclusion_table(st, mwi, mode="intraday")
    today = xi[xi.date.dt.normalize() == day].reset_index(drop=True)
    assert not today.trade_blocked.iloc[5] and today.trade_blocked.iloc[6:51].all()
    assert (today.block_reason.iloc[6] == "mwcb_halt") and not today.buy_fill_feasible_at_open.iloc[10]


def test_intraday_session_guard_and_no_candidate_by_default():
    # band 5% given; price trades +7% early, then sits at +5% with close==high -> not a circuit
    ts = pd.date_range("2024-03-04 09:15", periods=10, freq="1min")
    px = [107.0, 106.0] + [105.0] * 8
    b = pd.DataFrame(dict(symbol="X", date=ts, open=px, high=px, low=px, close=px, volume=100.0,
                          prev_close=100.0, upper_band_pct=5.0, lower_band_pct=5.0))
    o = C.compute_circuit_hit_flag(b, mode="intraday")
    assert not o.pinned.any()
    # band unknown: no candidate matching unless opted in
    b2 = b.drop(columns=["upper_band_pct", "lower_band_pct"]).assign(open=105.0, high=105.0, low=105.0, close=105.0)
    assert not C.compute_circuit_hit_flag(b2, mode="intraday").pinned.any()
    assert C.compute_circuit_hit_flag(b2, mode="intraday", intraday_candidate_mode=True).intraday_freeze.any()


def test_adjusted_offgrid_prices_use_fine_tick_slack():
    # back-adjusted history: prices off the 0.05 grid -> slack from 0.01 tick
    d = make_eod("", p0=1.58)
    d[["open", "high", "low", "close"]] = (d[["open", "high", "low", "close"]] * 0.9973).round(2)
    o = C.compute_circuit_hit_flag(d)
    assert (o.effective_tick.iloc[15:] == 0.01).all()
    assert o.slack_pct.iloc[-1] < 1.0      # would be ~3.2% with a 0.05 tick


def test_four_flag_columns_eod_and_intraday():
    k = eod_chain(make_eod("UUUUU" + "n"))
    mw = pd.DataFrame(dict(date=[k.date.iloc[34]], mwcb_level=[10], mwcb_dir=["lower"], mwcb_triggered=[True]))
    x = C.four_flag_columns(C.build_universe_exclusion_table(k, mw))
    r = x.iloc[34]
    assert (r.PRICE_BAND, r.CIRCUIT, r.MWCB, r.STAIRCASE) == ("5", "UPPER", "LOWER_10", "CLIMBING")
    assert r.TRADE_BLOCKED == "STAIRCASE+MWCB_DAY" and x.TRADE_BLOCKED.iloc[10] == "NO"
    assert x.TRADE_BLOCKED.iloc[31] == "NO"                     # BUILDING is not a block
    assert x.STAIRCASE.iloc[31] == "BUILDING" and x.CIRCUIT.iloc[5] == "" and x.PRICE_BAND.iloc[5] == "UNKNOWN"
    b = make_intraday(["n"] * 25 + ["U"] * 6)
    st = C.compute_staircase_flag(C.compute_circuit_hit_flag(b, mode="intraday"), mode="intraday")
    f = C.four_flag_columns(C.build_universe_exclusion_table(st, mode="intraday"), mode="intraday")
    assert "STAIRCASE" in set(f.TRADE_BLOCKED) and "NO" in set(f.TRADE_BLOCKED)
    assert set(f.MWCB) == {"NA"} and "EARLY_BLOCK" in set(f.STAIRCASE) and "UPPER" in set(f.CIRCUIT)


def test_both_staircase_directions_block_buy_and_sell():
    """Any tagged staircase - CLIMBING or FALLING - is barred from buying AND selling (and exiting)."""
    for pat, label in (("UUUUUU", "CLIMBING"), ("DDDDDD", "FALLING")):
        x = C.four_flag_columns(C.build_universe_exclusion_table(eod_chain(make_eod(pat))))
        tagged = x[x.STAIRCASE == label]
        assert len(tagged) == 2, (label, len(tagged))                  # 5th and 6th ladder day
        assert tagged.trade_blocked.all() and tagged.TRADE_BLOCKED.str.contains("STAIRCASE").all(), label
    # the tracker (Paper / Live) gives the same gate in both directions
    for pat in ("UUUUUU", "DDDDDD"):
        tr = C.CircuitLiquidityTracker("X")
        f = [tr.update_eod(r) for r in make_eod(pat).to_dict("records")]
        assert f[-1]["staircase"] and f[-1]["staircase_dir"] in ("climbing", "falling")


# ----------------------------------------------------------------- config + shared pipeline
def test_config_defaults_and_typo_detection(tmp_path=None):
    import json
    import tempfile
    import flags_config as F
    cfg = F.load_config()
    assert cfg.staircase.start_confirm_days == 5 and cfg.circuit.lock_mode == "close_locked"
    d = Path(tempfile.mkdtemp())
    (d / "typo.json").write_text(json.dumps({"staircase": {"start_confrim_days": 4}}))
    try:
        F.load_config(d / "typo.json")
        raise AssertionError("typo not caught")
    except F.ConfigError as e:
        assert "start_confrim_days" in str(e)
    (d / "bad.json").write_text(json.dumps({"staircase": {"end_confirm_days": 0}}))
    try:
        F.load_config(d / "bad.json")
        raise AssertionError("bad value not caught")
    except F.ConfigError:
        pass


def test_config_parameters_reach_the_pipeline():
    import json
    import tempfile
    import flags_config as F
    import flags_io as IO
    d = Path(tempfile.mkdtemp())
    (d / "s3.json").write_text(json.dumps({"staircase": {"start_confirm_days": 3}, "gate": {"block_on_mwcb_day": False}}))
    cfg3 = F.load_config(d / "s3.json")
    df = make_eod("UUUU")
    v5 = IO.eod_flags(df, F.load_config())
    v3 = IO.eod_flags(df, cfg3)
    assert v5.STAIRCASE.iloc[32] == "BUILDING" and v3.STAIRCASE.iloc[32] == "CLIMBING"
    mw = pd.DataFrame(dict(date=[df.date.iloc[10]], mwcb_level=[10], mwcb_dir=["lower"], mwcb_triggered=[True]))
    assert IO.eod_flags(df, F.load_config(), None, mw).TRADE_BLOCKED.iloc[10] == "MWCB_DAY"
    assert IO.eod_flags(df, cfg3, None, mw).TRADE_BLOCKED.iloc[10] == "NO"
    # tracker built from the same config agrees with the batch pipeline
    tr = cfg3.tracker("X")
    got = [tr.update_eod(r)["staircase_state"] for r in df.to_dict("records")]
    assert got == v3.staircase_state.tolist()


# ----------------------------------------------------------------- v2.4.2: volume in tag / untag, missing volume
def _set_vol(df, rel_idx, value):
    """Set volume on rows 30+rel_idx (after the 30 warm-up normal days)."""
    df = df.copy()
    df.loc[[30 + i for i in rel_idx], "volume"] = value
    return df


def test_v242_volume_status_classification():
    df = make_eod("n" * 30)
    df.loc[31, "volume"] = 0.0                                       # zero volume but the price moved -> MISSING
    df.loc[32, ["open", "high", "low", "close"]] = df.loc[31, "close"]
    df.loc[32, "volume"] = 0.0                                       # zero, price unchanged -> ZERO (no trade)
    df.loc[33, "volume"] = np.nan                                    # blank -> MISSING
    df.loc[34, "volume"] = -10.0                                     # negative (erroneous) -> MISSING
    df.loc[35, "_gap_filled"] = 1                                    # gap-filled row -> GAP
    o = C.compute_circuit_hit_flag(df, mode="eod")
    assert o.volume_status.iloc[30] == "REAL"
    assert o.volume_status.iloc[31:36].tolist() == ["MISSING", "ZERO", "MISSING", "MISSING", "GAP"]
    # a long zero run: the zero_run_missing-th consecutive zero session SO FAR (causal) is MISSING
    z = make_eod("z" * 30)
    z.loc[30:, "volume"] = 0.0
    oz = C.compute_circuit_hit_flag(z, mode="eod", circuit_params=C.CircuitParams(zero_run_missing=20))
    assert (oz.volume_status.iloc[30:49] == "ZERO").all() and (oz.volume_status.iloc[49:] == "MISSING").all()
    assert (C.compute_circuit_hit_flag(z, mode="eod", circuit_params=C.CircuitParams(volume_quality=False))
            .volume_status.iloc[30:] == "ZERO").all()                # v2.4.1: zero is zero


def test_v242_heavy_volume_ladder_not_tagged_until_thin():
    base = 10000.0
    df = _set_vol(make_eod("U" * 9), range(0, 6), base * 3.0)        # 6 locked days on 3x volume, then thin
    t = tail(eod_chain(df), 0)
    assert not t.staircase.iloc[:6].any()                            # S reached on day 5, but the ladder is liquid
    assert (t.staircase_vol_warn.iloc[4:6] == "LADDER_HIGH_VOL").all()
    assert t.staircase_state.iloc[5] == "BUILDING" and t.ladder_run_len.iloc[5] == 6
    k = int(np.argmax(t.staircase.to_numpy()))                       # tagged once the 3-day average is thin
    assert k >= 6 and t.vol_avg_real.iloc[k] < 0.5 * t.vol_baseline.iloc[k]
    # v2.4.1: tagged on the 5th ladder day regardless of volume
    assert tail(eod_chain(df, LEGACY_SP, **LEGACY_CK), 0).staircase.iloc[4]


def test_v242_missing_volume_tags_on_ohlc_with_warning():
    df = _set_vol(make_eod("UUUUU"), range(0, 5), np.nan)            # ladder days with NO volume data
    t = tail(eod_chain(df), 0)
    assert t.staircase.tolist() == [False] * 4 + [True]
    assert t.staircase_vol_warn.iloc[4] == "TAGGED_NO_VOL" and t.staircase_vol_basis.iloc[4] == "OHLC"
    x = C.four_flag_columns(C.build_universe_exclusion_table(eod_chain(df)))
    assert x[C.VOL_WARN_COLUMN].iloc[34] == "TAGGED_NO_VOL" and "STAIRCASE" in x.TRADE_BLOCKED.iloc[34]


def test_v242_missing_volume_untags_on_ohlc_v241_never_does():
    df = make_eod("UUUUU" + "nnnn")
    df.loc[35:, "volume"] = 0.0                                      # normal price action, volume missing (price moves)
    t = tail(eod_chain(df), 0)
    assert t.staircase.iloc[4] and t.staircase.iloc[5]               # E=2: 1st OHLC-normal day keeps the tag
    assert t.staircase_vol_warn.iloc[5] == "NORMAL_NO_VOL"
    assert not t.staircase.iloc[6] and t.staircase_vol_warn.iloc[6] == "UNTAGGED_NO_VOL"
    leg = tail(eod_chain(df, LEGACY_SP, **LEGACY_CK), 0)
    assert leg.staircase.iloc[4:].all()                              # v2.4.1: no NORMAL day without volume -> stuck


def test_v242_untag_needs_average_volume_back():
    df = make_eod("UUUUU" + "nnnnn")
    df.loc[35:36, "volume"] = 10000.0 * 0.2                          # OHLC-normal but thin: not NORMAL
    t = tail(eod_chain(df), 0)
    assert (t.day_class.iloc[5:7] == "OTHER").all() and t.staircase.iloc[5:7].all()
    assert not t.staircase.iloc[9]


def test_v242_chronic_missing_volume_is_not_no_trade():
    df = make_eod("n" * 70)
    df.loc[30:, "volume"] = 0.0                                      # price keeps moving, volume never reported
    new = eod_chain(df)
    old = eod_chain(df, LEGACY_SP, **LEGACY_CK)
    assert old.chronic_illiquid.iloc[-1] and not new.chronic_illiquid.any()
    assert (new.volume_status.iloc[30:] == "MISSING").all()


def _universe_v242():
    u = _universe()
    rng = np.random.default_rng(7)
    u.loc[rng.random(len(u)) < 0.06, "volume"] = np.nan
    u.loc[rng.random(len(u)) < 0.06, "volume"] = 0.0
    ix = u.index[u.symbol == "S0"][40:70]
    u.loc[ix, "volume"] = 0.0                                        # a long zero-volume stretch
    ix = u.index[u.symbol == "S2"][32:40]
    u.loc[ix, "volume"] = u.loc[ix, "volume"] * 8                    # heavy-volume ladder
    return u


V242_COLS = ["volume_status", "zero_volume_run", "staircase_state", "staircase", "ladder_run_len", "normal_day_count",
             "vol_avg_real", "staircase_vol_basis", "staircase_vol_warn", "chronic_illiquid", "vol_baseline"]


def test_v242_no_repaint_truncation():
    u = _universe_v242()
    full = eod_chain(u).set_index(["symbol", "date"])
    for cut in sorted(u.date.unique())[25::3]:
        part = eod_chain(u[u.date <= cut]).set_index(["symbol", "date"])
        pd.testing.assert_frame_equal(norm(full.loc[part.index, V242_COLS]), norm(part[V242_COLS]), check_dtype=False)


def test_v242_streaming_parity_eod():
    u = _universe_v242()
    batch = eod_chain(u)
    for s, g in u.groupby("symbol"):
        tr = C.CircuitLiquidityTracker(s)
        got = pd.DataFrame([tr.update_eod(r) for r in g.to_dict("records")])
        exp = batch[batch.symbol == s][V242_COLS].reset_index(drop=True)
        pd.testing.assert_frame_equal(norm(got[V242_COLS]), norm(exp), check_dtype=False)


def test_v242_legacy_config_reproduces_v241_semantics():
    import flags_config as F
    leg = F.legacy_v241_config()
    assert leg.circuit.volume_quality is False and leg.staircase.vol_avg_days == 1
    assert leg.staircase.tag_vol_frac is None and leg.chronic.missing_volume_as_no_trade is True
    df = _set_vol(make_eod("U" * 6), range(0, 6), 30000.0)
    import flags_io as IO
    assert IO.eod_flags(df, leg).STAIRCASE.iloc[34] == "CLIMBING"     # v2.4.1: heavy-volume ladder is tagged
    assert IO.eod_flags(df, F.load_config()).STAIRCASE.iloc[34] == "BUILDING"


# ----------------------------------------------------------------- real data (optional)
def _load(path):
    d = pd.read_csv(path)
    d["date"] = pd.to_datetime(d["date"], format="%d-%m-%Y")
    if "symbol" in d.columns:
        d["symbol"] = d["symbol"].fillna(Path(path).stem)
    return d


def test_iso_dates_not_day_swapped():
    s = pd.Series(["2024-03-01 09:15:00", "2024-03-12 09:16:00", "12-03-2024"])
    got = C.parse_dates(s).dt.strftime("%Y-%m-%d").tolist()
    assert got == ["2024-03-01", "2024-03-12", "2024-03-12"], got


def test_real_nifty_mwcb_days():
    if not DATA:
        return
    n = _load(Path(DATA) / "Final_Clean_Indices_EOD_Data" / "Nifty 50.csv").assign(index_name="NIFTY50")
    o = C.compute_mwcb_flag(n)
    got = set(o.loc[o.mwcb_triggered, "date"].dt.strftime("%Y-%m-%d"))
    assert {"2004-05-17", "2008-01-22", "2009-05-18", "2020-03-13", "2020-03-23"} <= got, got


def test_real_indothai_ladder():
    if not DATA:
        return
    d = _load(Path(DATA) / "Final_Clean_Stocks_EOD_Data" / "INDOTHAI.csv")
    o = eod_chain(d)
    w = o[(o.date >= "2021-12-20") & (o.date <= "2022-01-10")]
    assert w.staircase.sum() >= 10, w[["date", "circuit_locked_dir", "staircase_state"]]
    r = eod_chain(_load(Path(DATA) / "Final_Clean_Stocks_EOD_Data" / "RELIANCE.csv"))
    assert not r.staircase.any()


# ----------------------------------------------------------------- v2.4.3: STEP staircase (illiquid "flat, then jump")
STEP_KEYS = ["step_stale_day", "step_stale_run", "step_event", "step_events_win", "step_state", "step_staircase",
             "step_dir", "step_event_id", "step_normal_count", "step_vol_warn"]


def make_step(pattern: str, sym="E", p0=100.0, base_vol=50000.0, seed=3, start="2024-01-01") -> pd.DataFrame:
    """n normal day (moves, normal volume); s stale (close = previous close, O=H=L=C, 2% volume);
    S stale with ZERO volume; m stale with blank (MISSING) volume; q unchanged close on NORMAL volume (liquid,
    not stale); J / K jump +3% / -3% on normal volume; t thin normal day (moves, 2% volume)."""
    rng = np.random.default_rng(seed)
    rows, c = [], p0
    for ch in "n" * 30 + pattern:
        pc = c
        if ch in "sSmq":
            o = h = l = c = pc
            v = {"s": base_vol * 0.02, "S": 0.0, "m": np.nan, "q": base_vol * rng.uniform(0.8, 1.2)}[ch]
            if ch == "q":
                h, l = round(pc * 1.004, 2), round(pc * 0.996, 2)
        elif ch in "JK":
            c = round(pc * (1.03 if ch == "J" else 0.97), 2)
            o, h, l, v = pc, max(pc, c), min(pc, c), base_vol
        else:
            r = rng.uniform(0.004, 0.012) * rng.choice([-1, 1])
            c = round(pc * (1 + r), 2)
            o = pc
            h, l = round(max(o, c) * 1.003, 2), round(min(o, c) * 0.997, 2)
            v = base_vol * (0.02 if ch == "t" else rng.uniform(0.8, 1.2))
        rows.append(dict(open=o, high=h, low=l, close=c, volume=v))
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range(start, periods=len(df)))
    df.insert(0, "symbol", sym)
    df["exchange"] = "NSE"
    return df


def gate_chain(df, sp=None):
    o = eod_chain(df, sp)
    return C.four_flag_columns(C.build_universe_exclusion_table(o, None), mode="eod")


def test_step_flat_run_tags_and_blocks_both_directions():
    for jump, label in (("J", "CLIMBING"), ("K", "FALLING")):
        o = gate_chain(make_step("sss" + jump + "nnnnn"))
        w = o.iloc[30:]
        assert not w.step_staircase.iloc[:2].any() and w.STEP.iloc[0] == "BUILDING"
        assert w.step_staircase.iloc[2] and w.STEP.iloc[2] == "FLAT"           # 3rd stale bar tags
        assert w.step_event.iloc[3] and w.STEP.iloc[3] == label                 # the jump gives the direction
        for t in range(2, 5):
            assert "STEP_STAIRCASE" in w.TRADE_BLOCKED.iloc[t], (label, t, w.TRADE_BLOCKED.iloc[t])
            assert w.trade_blocked.iloc[t] and w.exclude_from_backtest_EOD.iloc[t], (label, t)
        assert not w.step_staircase.iloc[5] and w.TRADE_BLOCKED.iloc[5] == "NO"  # 2nd normal bar untags
        assert w.STAIRCASE.eq("").all()                                         # the circuit staircase is untouched


def test_step_two_events_in_window_tag():
    o = gate_chain(make_step("ssJnnnnnssJnnnn"))
    w = o.iloc[30:].reset_index(drop=True)
    assert w.step_event.sum() == 2 and not w.step_staircase.iloc[:10].any()     # stale runs of 2 never tag alone
    assert w.step_staircase.iloc[10] and w.STEP.iloc[10] == "CLIMBING" and w.step_events_win.iloc[10] == 2


def test_step_liquid_unchanged_close_is_not_stale():
    o = gate_chain(make_step("q" * 8 + "n" * 3))
    assert not o.step_stale_day.any() and not o.step_staircase.any() and (o.TRADE_BLOCKED == "NO").all()


def test_step_low_price_tick_moves_are_not_stale():
    rows, c = [], 13.10
    for k, ch in enumerate("n" * 30 + "abababab"):
        pc = c
        c = round(pc + (0.01 if (ch == "a" or (ch == "n" and k % 2)) else -0.01), 2)
        rows.append(dict(open=pc, high=max(pc, c) + 0.02, low=min(pc, c) - 0.02, close=c, volume=8e6))
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range("2024-01-01", periods=len(df)))
    df.insert(0, "symbol", "METALX")
    o = gate_chain(df)
    assert not o.step_stale_day.any() and not o.step_staircase.any()


def test_step_one_tick_moves_on_thin_volume_are_not_stale():
    rows, c = [], 13.10
    for k in range(40):
        pc = c
        thin = k >= 30
        c = round(pc + (0.01 if k % 2 else -0.01), 2)
        rows.append(dict(open=pc, high=max(pc, c), low=min(pc, c), close=c, volume=1e5 * (0.02 if thin else 1.0)))
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range("2024-01-01", periods=len(df)))
    df.insert(0, "symbol", "THINX")
    o = gate_chain(df)
    assert not o.step_stale_day.any() and not o.step_staircase.any()   # a one-paise move is a trade, not a stale bar


def test_step_zero_and_missing_volume():
    o = gate_chain(make_step("SSS" + "nn"))                    # v2.4.3 owner rule: ZERO volume -> price only + warning
    assert o.step_staircase.iloc[32] and (o.step_vol_warn.iloc[30:33] == "STALE_NO_VOL").all()
    z = gate_chain(make_step("SSS" + "nn"), C.StaircaseParams(zero_volume_as_missing=False))
    assert z.step_staircase.iloc[32] and not z.step_vol_warn.iloc[30:33].ne("").any()   # v2.4.2-style: ZERO = thin
    m = gate_chain(make_step("mmm" + "nn"))
    assert m.step_staircase.iloc[32] and (m.step_vol_warn.iloc[30:33] == "STALE_NO_VOL").all()


def test_step_thin_moving_days_do_not_untag():
    o = gate_chain(make_step("sss" + "t" * 5 + "nnnn"))
    w = o.iloc[30:].reset_index(drop=True)
    assert w.step_staircase.iloc[2:8].all()                                     # thin days keep the tag
    assert not w.step_staircase.iloc[-1]                                        # volume back -> untagged


def _step_universe():
    return pd.concat([make_step("sssJnnssKnnnnnSSnnn", sym="A", seed=1),
                      make_step("ssJnnnnssJnnqqqnnmmmnn", sym="B", seed=2),
                      make_step("q" * 6 + "n" * 6, sym="C", seed=3)], ignore_index=True)


def test_step_streaming_parity():
    u = _step_universe()
    batch = eod_chain(u)
    for sym, g in u.groupby("symbol"):
        tr = C.CircuitLiquidityTracker(sym)
        got = pd.DataFrame([tr.update_eod(r) for r in g.to_dict("records")])
        exp = batch[batch.symbol == sym][STEP_KEYS].reset_index(drop=True)
        pd.testing.assert_frame_equal(norm(got[STEP_KEYS]), norm(exp), check_dtype=False)


def test_step_no_repaint_truncation():
    u = _step_universe()
    full = eod_chain(u)
    for sym, g in u.groupby("symbol"):
        f = full[full.symbol == sym].reset_index(drop=True)
        for cut in range(28, len(g)):
            part = eod_chain(g.iloc[:cut + 1]).reset_index(drop=True)
            pd.testing.assert_frame_equal(norm(part[STEP_KEYS]), norm(f.loc[:cut, STEP_KEYS]), check_dtype=False)


def test_step_disabled_is_v242():
    u = _step_universe()
    sp_off = C.StaircaseParams(step_enabled=False)
    a = gate_chain(u, sp_off)
    b = gate_chain(u)
    assert not a.step_staircase.any() and (a.STEP == "").all() and not a.TRADE_BLOCKED.str.contains("STEP").any()
    other = [c for c in a.columns if not c.startswith("step_") and c not in ("STEP", "TRADE_BLOCKED", "trade_blocked",
                                                                              "block_reason", "exclude_from_backtest_EOD")]
    pd.testing.assert_frame_equal(norm(a[other]), norm(b[other]), check_dtype=False)
    assert b.TRADE_BLOCKED.str.contains("STEP_STAIRCASE").any()


def test_step_exempt_pattern():
    d = make_step("sssJnn", sym="LIQUIDBEES_NSE")
    assert gate_chain(d).step_staircase.any()
    sp = C.StaircaseParams(step_exempt_pattern="liquid|overnight")
    o = gate_chain(d, sp)
    assert not o.step_staircase.any() and (o.TRADE_BLOCKED == "NO").all()
    tr = C.CircuitLiquidityTracker("LIQUIDBEES_NSE", staircase_params=sp)
    assert not any(tr.update_eod(r)["step_staircase"] for r in d.to_dict("records"))


def test_step_intraday_previous_close_tag():
    days = make_step("sssJnnn")
    rows = []
    for r in days.to_dict("records"):
        for k in range(6):
            ts = pd.Timestamp(r["date"]) + pd.Timedelta(hours=9, minutes=15 + k)
            px = r["close"] if r["open"] == r["close"] else r["open"] + (r["close"] - r["open"]) * k / 5
            rows.append(dict(symbol="E", date=ts, open=px, high=max(px, r["high"] if k == 5 else px),
                             low=min(px, r["low"] if k == 5 else px), close=px, volume=r["volume"] / 6))
    b = pd.DataFrame(rows)
    ci = C.compute_circuit_hit_flag(b, mode="intraday")
    st = C.compute_staircase_flag(ci, mode="intraday")
    x = C.four_flag_columns(C.build_universe_exclusion_table(st, None, mode="intraday"), mode="intraday")
    d = x.date.dt.normalize()
    sess = sorted(d.unique())
    jump_day = x[d == sess[33]]                                  # day after the 3rd stale session
    assert jump_day.step_staircase_prev.all() and jump_day.TRADE_BLOCKED.str.contains("STEP_STAIRCASE").all()
    assert not x[d == sess[29]].step_staircase_prev.any()
    tr = C.CircuitLiquidityTracker("E")
    got = pd.DataFrame([tr.update_intraday(r) for r in b.to_dict("records")])
    assert got.step_staircase_prev.tolist() == st.step_staircase_prev.tolist()


def test_step_config_keys():
    import json
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import flags_config as F
    cfg = F.load_config()
    assert cfg.staircase.step_enabled and cfg.staircase.step_tag_stale_run == 3
    assert not F.legacy_v242_config().staircase.step_enabled and not F.legacy_v241_config().staircase.step_enabled
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"staircase": {"step_jump_pct": 3.5, "step_exempt_pattern": "LIQUID"}}, fh)
    c2 = F.load_config(fh.name)
    assert c2.staircase.step_jump_pct == 3.5 and c2.staircase.step_exempt("LIQUIDBEES")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"staircase": {"step_jump_pctt": 3.5}}, fh)
    try:
        F.load_config(fh.name)
        raise AssertionError("typo accepted")
    except F.ConfigError:
        pass


# ----------------------------------------------------------------- v2.4.3: asset classes, directions, volume rule, CA
def test_v243_etf_rules_from_product_class():
    sp = C.StaircaseParams(etf_overrides=(("start_confirm_days", 3),))
    stock = make_eod("UUUUU").assign(product_class="EQUITY")
    etf = make_eod("UUUUU", sym="ETFX").assign(product_class="ETF")
    t = eod_chain(pd.concat([stock, etf], ignore_index=True), sp)
    ts, te = tail(t[t.symbol == "X"], 0), tail(t[t.symbol == "ETFX"], 0)
    assert ts.staircase.tolist() == [False] * 4 + [True]                 # stock rule: 5 ladder days
    assert te.staircase.tolist() == [False, False, True, True, True]     # ETF rule: 3 ladder days
    v = C.four_flag_columns(C.build_universe_exclusion_table(eod_chain(etf, sp)), mode="eod")
    assert (v.ASSET_CLASS == "ETF").all()
    tr = C.CircuitLiquidityTracker("ETFX", staircase_params=sp)        # class from the first bar's product_class
    got = [tr.update_eod(r)["staircase"] for r in etf.to_dict("records")][30:]
    assert got == te.staircase.tolist() and tr.asset_class == "ETF"
    tr2 = C.CircuitLiquidityTracker("ETFX", staircase_params=sp, asset_class="EQUITY")   # explicit class wins
    assert [tr2.update_eod(r)["staircase"] for r in etf.to_dict("records")][30:] == ts.staircase.tolist()


def test_v243_direction_specific_start_and_end():
    sp = C.StaircaseParams(start_confirm_days_falling=3, end_confirm_days_climbing=4)
    dn = tail(eod_chain(make_eod("DDDDD" + "nnnn"), sp), 0)
    assert dn.staircase.iloc[:5].tolist() == [False, False, True, True, True] and dn.staircase_dir.iloc[2] == "falling"
    d0 = tail(eod_chain(make_eod("DDDDD" + "nnnn")), 0)
    first_free = lambda t: int(np.flatnonzero(~t.staircase.to_numpy() & (np.arange(len(t)) >= 5))[0])
    assert first_free(dn) == first_free(d0)                               # falling untags with the shared E = 2
    up = tail(eod_chain(make_eod("UUUUU" + "n" * 8), sp), 0)
    u0 = tail(eod_chain(make_eod("UUUUU" + "n" * 8)), 0)
    assert up.staircase.iloc[:5].tolist() == [False] * 4 + [True]       # climbing keeps the shared S = 5
    assert first_free(up) == first_free(u0) + 2                           # ... and needs 4 NORMAL days, not 2


def test_v243_ladder_break_days():
    pat = "UUUnUU"
    assert not tail(eod_chain(make_eod(pat)), 0).staircase.any()        # v2.4.2: the break resets the run
    t = tail(eod_chain(make_eod(pat), C.StaircaseParams(ladder_break_days=1)), 0)
    assert t.staircase.tolist() == [False] * 5 + [True] and t.ladder_break_used.iloc[3] == 1
    t2 = tail(eod_chain(make_eod(pat), C.StaircaseParams(ladder_break_days_falling=1)), 0)
    assert not t2.staircase.any()                                        # the tolerance was given to FALLING only


def test_v243_zero_volume_is_ohlc_basis():
    # a ZERO-volume no-trade day (price unchanged): no volume information -> OHLC basis (owner rule)
    df = make_eod("zz" + "nn")
    df.loc[30:31, "volume"] = 0.0
    t = tail(eod_chain(df), 0)
    assert (t.volume_status.iloc[:2] == "ZERO").all()
    assert (t.staircase_vol_reason.iloc[:2] == "ZERO").all() and (t.staircase_vol_basis.iloc[:2] == "OHLC").all()
    assert np.isnan(t.vol_avg_real.iloc[0])                                # not averaged in as volume 0
    t2 = tail(eod_chain(df, C.StaircaseParams(zero_volume_as_missing=False)), 0)
    assert (t2.staircase_vol_basis.iloc[:2] == "VOLUME").all() and t2.vol_avg_real.iloc[1] < t2.vol_avg_real.iloc[3]
    # a frozen ladder day with zero volume is MISSING volume (the price moved): tagged on OHLC with a warning
    lad = make_eod("UUUUU")
    lad.loc[30:, "volume"] = 0.0
    lt = tail(eod_chain(lad), 0)
    assert lt.staircase.iloc[-1] and lt.staircase_vol_warn.iloc[-1] == "TAGGED_NO_VOL"


def test_v243_unreliable_volume_era_is_ohlc_basis():
    df = make_eod("n" * 60 + "UUUUU")
    k = np.arange(len(df))
    df.loc[(k < 85) & (k % 3 != 0), "volume"] = np.nan                    # 2 of 3 sessions without volume data
    t = eod_chain(df).iloc[-5:]
    assert t.staircase.iloc[-1] and set(t.staircase_vol_reason) <= {"UNRELIABLE", "MISSING"}
    assert (t.staircase_vol_reason == "UNRELIABLE").any()
    t2 = eod_chain(df, C.StaircaseParams(vol_reliability_min=None)).iloc[-5:]
    assert not (t2.staircase_vol_reason == "UNRELIABLE").any()


def test_v243_corporate_action_guard_holds_state():
    df = make_eod("UU" + "n" + "UUU")
    i = 32                                                                # the 'n' day becomes a 1:2 split
    f = 0.5
    df.loc[i:, ["open", "high", "low", "close"]] *= f
    df.loc[i, ["open", "high", "low", "close"]] = df.loc[i, "close"]
    c = C.compute_circuit_hit_flag(df, mode="eod")
    assert bool(c.ca_suspect.iloc[i]) and int(c.ca_suspect.sum()) == 1
    t = tail(eod_chain(df), 0)
    assert t.day_class.iloc[2] == "UNKNOWN" and t.staircase.iloc[-1]      # held through the split: 5 ladder days
    t0 = tail(eod_chain(df, circuit_params=C.CircuitParams(ca_jump_pct=None)), 0)
    assert not t0.staircase.iloc[-1]                                       # v2.4.2: the split day reset the ladder


def test_v243_traded_value_floor():
    df = make_eod("n" * 40, p0=100.0, base_vol=1000.0)                   # ~Rs 1 lakh a day
    chp = C.ChronicParams(min_traded_value=500_000.0)
    o = eod_chain(df, chp=chp)
    assert o.chronic_illiquid.iloc[-1] and o.low_traded_value.iloc[-1]
    assert not eod_chain(df).chronic_illiquid.any()                       # off by default
    x = C.build_universe_exclusion_table(o)
    assert x.trade_blocked.iloc[-1] and "chronic" in x.block_reason.iloc[-1]


def test_v243_config_etf_sections_and_presets():
    import json
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import flags_config as F
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"staircase_etf": {"start_confirm_days": 3, "step_jump_pct": 1.5},
                   "chronic_etf": {"min_traded_value": 500000}, "circuit_etf": {"band_candidates": [5, 10, 20]}}, fh)
    cfg = F.load_config(fh.name)
    assert cfg.staircase.start_confirm_days == 5 and cfg.staircase.for_class("ETF").start_confirm_days == 3
    assert cfg.staircase.for_class("ETF").step_jump_pct == 1.5 and cfg.chronic.for_class("ETF").min_traded_value == 500000
    assert cfg.circuit.for_class("ETF").band_candidates == (5.0, 10.0, 20.0)
    leg = F.legacy_v242_config(fh.name)
    assert leg.staircase.for_class("ETF").start_confirm_days == 3      # the user's ETF rule is kept ...
    assert not leg.staircase.for_class("ETF").step_enabled              # ... the 2.4.3 behaviour switched off
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"staircase_etf": {"start_confrim_days": 3}}, fh)
    try:
        F.load_config(fh.name)
        raise AssertionError("typo in an *_etf section accepted")
    except F.ConfigError:
        pass


def test_v243_load_eod_blank_symbol_cells():
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import flags_io as IO
    d = make_eod("n" * 5).drop(columns=["symbol"])
    d["date"] = d["date"].dt.strftime("%d-%m-%Y")
    d["symbol"] = "AXISX"
    d.loc[[3, 7, 20], "symbol"] = np.nan
    d["product_class"] = "ETF"
    d.loc[5, "product_class"] = np.nan
    with tempfile.TemporaryDirectory() as tdir:
        f = Path(tdir) / "AXISX_NSE.csv"
        d.to_csv(f, index=False)
        x = IO.load_eod(f)
    assert set(x.symbol) == {"AXISX"} and set(x.product_class) == {"ETF"}   # v2.4.2 gave a 2nd symbol AXISX_NSE


def test_v243_package_import():
    import shutil
    import subprocess
    import tempfile
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as tdir:
        pkg = Path(tdir) / "qbeast_flags_pkg"
        pkg.mkdir()
        for f in list(here.glob("*.py")) + list(here.glob("*.json")):
            shutil.copy(f, pkg / f.name)
        code = ("from qbeast_flags_pkg import circuit_liquidity_flags as C, flags_config as F, flags_io as IO; "
                "import qbeast_flags_pkg as Q; print(Q.__version__, F.load_config().staircase.step_enabled)")
        r = subprocess.run([sys.executable, "-c", code], cwd=tdir, capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.split()[0] == C.__version__, r.stderr[-400:]


def _v243_universe():
    a = make_eod("UUUnUUnnnDDDDnnn", sym="A", seed=1).assign(product_class="EQUITY")
    b = make_eod("UUnzzzUUUnn", sym="B", seed=2).assign(product_class="ETF")
    b.loc[33:36, "volume"] = 0.0
    c = make_eod("nnUUUUUUnnn", sym="C", seed=3).assign(product_class="EQUITY")
    c.loc[37:, ["open", "high", "low", "close"]] *= 0.5                     # split inside the run
    return pd.concat([a, b, c], ignore_index=True)


V243_SP = C.StaircaseParams(ladder_break_days_climbing=1, start_confirm_days_falling=3,
                            etf_overrides=(("start_confirm_days", 3), ("step_jump_pct", 1.0)))
V243_KEYS = ["staircase_state", "staircase", "staircase_dir", "ladder_run_len", "ladder_break_used",
             "staircase_vol_reason", "step_state", "step_staircase", "chronic_illiquid", "ca_suspect", "asset_class_used"]


def test_v243_no_repaint_and_streaming_parity():
    u = _v243_universe()
    full = eod_chain(u, V243_SP)
    for sym, g in u.groupby("symbol"):
        f = full[full.symbol == sym].reset_index(drop=True)
        for cut in range(28, len(g)):
            part = eod_chain(g.iloc[:cut + 1], V243_SP).reset_index(drop=True)
            pd.testing.assert_frame_equal(norm(part[V243_KEYS]), norm(f.loc[:cut, V243_KEYS]), check_dtype=False)
        tr = C.CircuitLiquidityTracker(sym, staircase_params=V243_SP)
        got = pd.DataFrame([tr.update_eod(r) for r in g.to_dict("records")])
        pd.testing.assert_frame_equal(norm(got[V243_KEYS]), norm(f[V243_KEYS]), check_dtype=False)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    bad = 0
    for f in fns:
        try:
            f()
            print(f"PASS {f.__name__}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL {f.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
