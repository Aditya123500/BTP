"""
QBEAST AI - shared data loading + flag pipelines used by every script
======================================================================
One place for: reading Final_Data CSVs, the NIFTY 50 calendar / MWCB table,
and the complete EOD / intraday flag pipelines (all driven by the config).

    from flags_config import load_config
    import flags_io as IO
    cfg = load_config()
    stock = IO.load_eod(path_to_csv)
    mkt = IO.load_market(cfg, cfg.data_dir())               # calendar + MWCB table
    eod = IO.eod_flags(stock, cfg, mkt.calendar, mkt.mw_daily)
    eod[IO.OUTCOLS]                                         # PRICE_BAND CIRCUIT MWCB STAIRCASE TRADE_BLOCKED
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:                                       # v2.4.3: works as plain files AND inside a package / wheel
    from . import circuit_liquidity_flags as C
    from .flags_config import FlagsConfig
except ImportError:
    import circuit_liquidity_flags as C
    from flags_config import FlagsConfig

logging.getLogger("qbeast.flags.circuit_liquidity").setLevel(logging.ERROR)

FLAGS = list(C.FOUR_FLAG_COLUMNS)                 # PRICE_BAND, CIRCUIT, MWCB, STAIRCASE
OUTCOLS = FLAGS + [C.GATE_COLUMN]                 # + TRADE_BLOCKED  (unchanged in v2.4.2 / v2.4.3)
OUTCOLS_ALL = OUTCOLS + [C.VOL_WARN_COLUMN, C.STEP_COLUMN, C.ASSET_CLASS_COLUMN]   # v2.4.2: + STAIRCASE_VOL_WARN; v2.4.3: + STEP, ASSET_CLASS


# ------------------------------------------------------------------ CSV loaders
def load_eod(path: str | Path) -> pd.DataFrame:
    """Daily bars: date (dd-mm-yyyy or ISO), open, high, low, close, volume [, symbol, exchange,
    source, _gap_filled]. Symbol defaults to the file name. Rows with a non-positive price are dropped."""
    path = Path(path)
    d = pd.read_csv(path)
    d.columns = [c.strip() for c in d.columns]
    if "date" not in d.columns:
        cand = [c for c in d.columns if "date" in c.lower() or "time" in c.lower()]
        if not cand:
            raise ValueError(f"{path.name}: no date column found (columns: {list(d.columns)})")
        d = d.rename(columns={cand[0]: "date"})
    missing = {"open", "high", "low", "close", "volume"} - set(d.columns)
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {sorted(missing)}")
    raw = d["date"]
    d["date"] = pd.to_datetime(raw, format="%d-%m-%Y", errors="coerce")
    if d["date"].isna().any():
        d["date"] = C.parse_dates(raw.astype(str))
    d = d.dropna(subset=["date"])
    d["date"] = d["date"].astype("datetime64[ns]")
    if "symbol" in d.columns:
        # v2.4.3 fix: blank symbol cells take the file's own symbol (its most frequent non-blank value). v2.4.2
        # used the file name, which differs for ETF files (AXISBPSETF_NSE.csv holds symbol AXISBPSETF): the blank
        # rows became a second "symbol" and the batch functions split one history into two.
        sym_mode = d["symbol"].dropna().astype(str).str.strip().replace("", np.nan).dropna().mode()
        d["symbol"] = d["symbol"].fillna(sym_mode.iloc[0] if len(sym_mode) else path.stem)
    else:
        d["symbol"] = path.stem
    d["symbol"] = d["symbol"].astype(str)
    for c in ("product_class", "asset_class"):        # v2.4.3: the asset class picks the rule set (STOCK / ETF)
        if c in d.columns and d[c].isna().any():
            m = d[c].dropna().mode()
            if len(m):
                d[c] = d[c].fillna(m.iloc[0])
    for c in ("source", "exchange"):                  # blank cells seen in Final_Data -> use _source/_exchange
        if c in d.columns and f"_{c}" in d.columns:
            d[c] = d[c].fillna(d[f"_{c}"])
    d = d.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    bad = (d[["open", "high", "low", "close"]] <= 0).any(axis=1)
    return d.loc[~bad].reset_index(drop=True)


def load_intraday(path: str | Path) -> pd.DataFrame:
    """1-minute / tick bars. Timestamp column: datetimestamp, datetime, timestamp, date+time or date;
    ISO text (with or without +05:30), dd-mm-yyyy HH:MM, or epoch seconds/ms. Converted to IST, tz-naive."""
    path = Path(path)
    d = pd.read_csv(path)
    d.columns = [c.strip() for c in d.columns]
    low = {c.lower(): c for c in d.columns}
    for key in ("datetimestamp", "datetime", "timestamp"):
        if key in low:
            raw = d[low[key]]
            break
    else:
        raw = (d[low["date"]].astype(str) + " " + d[low["time"]].astype(str)) if ("date" in low and "time" in low) \
            else d[low.get("date", d.columns[0])]
    if pd.api.types.is_numeric_dtype(raw):
        ts = pd.to_datetime(raw, unit="ms" if raw.max() > 1e11 else "s", utc=True)
    else:
        txt = raw.astype(str).str.strip()
        tz_aware = txt.str.contains(r"[+-]\d{2}:?\d{2}$|Z$", regex=True).any()
        ts = pd.to_datetime(txt, format="ISO8601", utc=True) if tz_aware else C.parse_dates(txt)
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    d["date"] = ts.astype("datetime64[ns]")
    for k in ("open", "high", "low", "close", "volume"):
        if k not in d.columns and k in low:
            d[k] = d[low[k]]
    missing = {"open", "high", "low", "close"} - set(d.columns)
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {sorted(missing)}")
    if "volume" not in d.columns:
        d["volume"] = np.nan
    d = d.dropna(subset=["date"])
    d["symbol"] = path.stem
    d = d.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    bad = (d[["open", "high", "low", "close"]] <= 0).any(axis=1)
    return d.loc[~bad].reset_index(drop=True)


# ------------------------------------------------------------------ market-wide (MWCB + calendar)
@dataclass
class Market:
    calendar: pd.DatetimeIndex | None       # NIFTY 50 trading dates (None if the file is missing)
    mw_daily: pd.DataFrame | None           # one row per date: mwcb_level, mwcb_dir, mwcb_triggered
    mw_intraday: pd.DataFrame | None        # one row per index timestamp: halt / auction windows
    indices_used: list[str]


def load_market(cfg: FlagsConfig, data_dir: Path, intraday: bool = False) -> Market:
    frames, calendar = [], None
    idx_dir = cfg.sub("indices_eod_subdir", data_dir)
    for name, fname in cfg.paths["mwcb_index_files"].items():
        p = idx_dir / fname
        if p.exists():
            d = load_eod(p).assign(index_name=name)
            frames.append(d.drop(columns="symbol"))
            if name == "NIFTY50":
                calendar = pd.DatetimeIndex(d.date)
    mw_daily = None
    if frames:
        mw_daily = C.aggregate_mwcb_by_date(C.compute_mwcb_flag(pd.concat(frames, ignore_index=True),
                                                                **cfg.mwcb_kwargs("eod")))
    mw_intraday = None
    if intraday:
        iidx = cfg.sub("indices_intraday_subdir", data_dir)
        fr = []
        for name, fname in cfg.paths["mwcb_index_files"].items():
            p = iidx / fname
            if p.exists():
                fr.append(load_intraday(p).assign(index_name=name).drop(columns="symbol"))
        if fr:
            mw_intraday = C.aggregate_mwcb_by_date(C.compute_mwcb_flag(pd.concat(fr, ignore_index=True),
                                                                       **cfg.mwcb_kwargs("intraday")))
    return Market(calendar, mw_daily, mw_intraday, [f.index_name.iloc[0] for f in frames])


# ------------------------------------------------------------------ pipelines (causal)
def eod_state(stock: pd.DataFrame, cfg: FlagsConfig, calendar=None) -> pd.DataFrame:
    """Flag 2 (+ band) -> Flag 4 -> chronic, all with the config's parameters."""
    circ = C.compute_circuit_hit_flag(stock, mode="eod", circuit_params=cfg.circuit)
    stair = C.compute_staircase_flag(circ, cfg.staircase)
    return C.compute_chronic_illiquidity_flag(stair, cfg.chronic, calendar=calendar)


def eod_flags(stock: pd.DataFrame, cfg: FlagsConfig, calendar=None, mw_daily=None) -> pd.DataFrame:
    """Complete EOD result: every detailed column + PRICE_BAND, CIRCUIT, MWCB, STAIRCASE, TRADE_BLOCKED.
    Row t uses bars <= t only."""
    x = C.build_universe_exclusion_table(eod_state(stock, cfg, calendar), mw_daily, mode="eod", **cfg.gate_kwargs())
    return C.four_flag_columns(x, mode="eod")


def intraday_flags(bars: pd.DataFrame, cfg: FlagsConfig, eod_stock: pd.DataFrame | None = None,
                   calendar=None, mw_intraday=None) -> pd.DataFrame:
    """Complete intraday result per bar. If the stock's EOD history is given, each session uses the
    PREVIOUS day's EOD close as prev_close and its causal band estimate, and inherits yesterday's
    staircase / chronic state (strictly earlier dates only)."""
    b = bars.copy()
    est = None
    if eod_stock is not None and len(eod_stock):
        e = eod_stock.copy()
        e["symbol"] = b.symbol.iloc[0]
        est = eod_state(e, cfg, calendar)
        ec = est[["date", "close", "band_est_next"]].copy()
        ec["_s"] = ec["date"].dt.normalize()
        b["_s"] = b["date"].dt.normalize()
        sess = b[["_s"]].drop_duplicates().sort_values("_s")
        m = pd.merge_asof(sess, ec.sort_values("_s")[["_s", "close", "band_est_next"]], on="_s",
                          direction="backward", allow_exact_matches=False)
        m = m.rename(columns={"close": "prev_close"})
        b = b.drop(columns=[c for c in ("prev_close", "upper_band_pct", "lower_band_pct") if c in b.columns])
        b = b.merge(m, on="_s", how="left").drop(columns="_s")
        b["upper_band_pct"] = b["band_est_next"]
        b["lower_band_pct"] = b["band_est_next"]
        b = b.drop(columns="band_est_next")
    ci = C.compute_circuit_hit_flag(b, mode="intraday", circuit_params=cfg.circuit)
    st = C.compute_staircase_flag(ci, cfg.staircase, mode="intraday", eod_state_df=est,
                                  circuit_params=cfg.circuit, chronic_params=cfg.chronic)
    x = C.build_universe_exclusion_table(st, mw_intraday, mode="intraday")
    return C.four_flag_columns(x, mode="intraday")


def staircase_episodes(o: pd.DataFrame) -> pd.DataFrame:
    """One row per tagged staircase episode of an eod_flags() result."""
    tagged = o["staircase"].astype(bool)
    ep = (tagged != tagged.shift(fill_value=False)).cumsum()
    g = o[tagged].groupby(ep[tagged])
    if len(o[tagged]) == 0:
        return pd.DataFrame(columns=["symbol", "start", "end", "days", "dirs", "max_run", "start_close", "end_close"])
    res = g.agg(start=("date", "min"), end=("date", "max"), days=("date", "size"),
                dirs=("staircase_dir", lambda x: ",".join(sorted(set(x.dropna())))),
                max_run=("ladder_run_len", "max"), start_close=("close", "first"),
                end_close=("close", "last")).reset_index(drop=True)
    if "staircase_vol_warn" in o.columns:            # v2.4.2: was the tag decided without volume?
        w = o["staircase_vol_warn"].fillna("").astype(str).to_numpy()
        pos = np.flatnonzero(tagged.to_numpy())
        out_w = []
        for _, idx in pd.Series(pos).groupby(ep.to_numpy()[pos]):
            lo, hi = idx.iloc[0], min(idx.iloc[-1] + 1, len(w) - 1)      # + the untagging bar
            out_w.append(",".join(sorted(set(w[lo:hi + 1]) - {""})))
        res["vol_warn"] = out_w
    else:
        res["vol_warn"] = ""
    res.insert(0, "symbol", o.symbol.iloc[0])
    return res


def step_episodes(o: pd.DataFrame) -> pd.DataFrame:
    """v2.4.3: one row per tagged STEP staircase episode (illiquid 'flat, then jump') of an eod_flags() result."""
    cols = ["symbol", "start", "end", "days", "dirs", "step_events", "max_stale_run", "start_close", "end_close",
            "vol_warn"]
    if "step_staircase" not in o.columns or not o["step_staircase"].astype(bool).any():
        return pd.DataFrame(columns=cols)
    tagged = o["step_staircase"].astype(bool)
    ep = (tagged != tagged.shift(fill_value=False)).cumsum()
    g = o[tagged].groupby(ep[tagged])
    res = g.agg(start=("date", "min"), end=("date", "max"), days=("date", "size"),
                dirs=("step_dir", lambda x: ",".join(sorted(set(x.dropna())))),
                step_events=("step_event", "sum"), max_stale_run=("step_stale_run", "max"),
                start_close=("close", "first"), end_close=("close", "last")).reset_index(drop=True)
    w = o["step_vol_warn"].fillna("").astype(str).to_numpy()
    pos = np.flatnonzero(tagged.to_numpy())
    out_w = []
    for _, idx in pd.Series(pos).groupby(ep.to_numpy()[pos]):
        lo, hi = idx.iloc[0], min(idx.iloc[-1] + 1, len(w) - 1)
        out_w.append(",".join(sorted(set(w[lo:hi + 1]) - {""})))
    res["vol_warn"] = out_w
    res.insert(0, "symbol", o.symbol.iloc[0])
    return res[cols]
