"""
HOW TO CALL THE 4 FUNCTIONS - one by one, with what each returns.
All 4 functions live in ONE file: circuit_liquidity_flags.py. Parameters come from
qbeast_flags_config.json (flags_config.load_config).

Run (PowerShell, in the bundle folder):
    python call_four_functions.py --symbol INDOTHAI
    python call_four_functions.py --data "E:\\Downloads\\Final_Data" --symbol RELIANCE

Rule for every function: give it rows UP TO TODAY only; row t of the result uses bars <= t only.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit_liquidity_flags as C          # noqa: E402  <-- the ONE file with all 4 functions
import flags_io as IO                         # noqa: E402
from flags_config import load_config          # noqa: E402

ap = argparse.ArgumentParser(description="Call each of the 4 flag functions and print what it returns.")
ap.add_argument("--config", default=None)
ap.add_argument("--data", default=None)
ap.add_argument("--symbol", default="INDOTHAI")
a = ap.parse_args()
cfg = load_config(a.config)
data = cfg.data_dir(a.data)
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / f"{a.symbol}.csv")
nifty = IO.load_eod(cfg.sub("indices_eod_subdir", data) / cfg.paths["mwcb_index_files"]["NIFTY50"])
nifty["index_name"] = "NIFTY50"

# ================================================================ FLAG 1 - PRICE BAND
# Input : symbol, date, upper_band_pct, lower_band_pct   (your point-in-time band data)
# Output: same rows + band_known, band_asymmetric, band_tightened, band_widened
# (Final_Data has no band data, so here is a tiny example table.)
bands = pd.DataFrame({
    "symbol": [a.symbol] * 4,
    "date": ["01-01-2024", "02-01-2024", "03-01-2024", "04-01-2024"],
    "upper_band_pct": [20, 10, 5, 0],          # 0 = GSM "no upward movement"
    "lower_band_pct": [20, 10, 5, 5],
})
flag1 = C.compute_price_band_flag(bands)
print("\n=== FLAG 1: compute_price_band_flag ===")
print(flag1[["date", "upper_band_pct", "lower_band_pct", "band_asymmetric", "band_tightened"]])

# ================================================================ FLAG 2 - UPPER / LOWER CIRCUIT
# Input : symbol, date, open, high, low, close, volume  [exchange, _gap_filled, band columns optional]
# Output: + circuit_locked_dir ('upper'/'lower'), band_hit_dir, frozen, band_upper_used, band_est_next, ...
flag2 = C.compute_circuit_hit_flag(stock, mode="eod", circuit_params=cfg.circuit)
print("\n=== FLAG 2: compute_circuit_hit_flag ===")
hits = flag2.loc[flag2.circuit_locked_dir.notna(), ["date", "close", "move_pct", "band_upper_used", "circuit_locked_dir"]]
print(hits.tail(8) if len(hits) else "   (no circuit days for this stock)")

# ================================================================ FLAG 3 - MWCB (market-wide)
# Input : index_name, date, close, high, low   (NIFTY 50)
# Output: + mwcb_level (0/10/15/20), mwcb_dir ('upper'/'lower'), mwcb_triggered
flag3 = C.compute_mwcb_flag(nifty, **cfg.mwcb_kwargs("eod"))
print("\n=== FLAG 3: compute_mwcb_flag ===")
print(flag3.loc[flag3.mwcb_triggered, ["date", "mwcb_level", "mwcb_dir", "extreme_dn_pct", "pct_move"]])

# ================================================================ FLAG 4 - STAIRCASE
# Input : the OUTPUT of Flag 2
# Output: + staircase (True = tagged, DO NOT TRADE), staircase_state, staircase_dir, ladder_run_len, ...
flag4 = C.compute_staircase_flag(flag2, cfg.staircase)
print("\n=== FLAG 4: compute_staircase_flag ===")
tag = flag4.loc[flag4.staircase, ["date", "close", "circuit_locked_dir", "staircase_state", "staircase_dir", "ladder_run_len"]]
print(tag.head(8) if len(tag) else "   (never a staircase)")

# ================================================================ ALL TOGETHER: one column per flag + gate
chronic = C.compute_chronic_illiquidity_flag(flag4, cfg.chronic, calendar=pd.DatetimeIndex(nifty.date))
table = C.build_universe_exclusion_table(chronic, C.aggregate_mwcb_by_date(flag3), **cfg.gate_kwargs())
view = C.four_flag_columns(table)
print("\n=== ALL TOGETHER: PRICE_BAND | CIRCUIT | MWCB | STAIRCASE | TRADE_BLOCKED ===")
act = view.loc[(view.STAIRCASE != "") | (view.TRADE_BLOCKED != "NO"), ["date", "close"] + IO.OUTCOLS]
print(act.tail(10) if len(act) else "   (no staircase or blocked days for this stock)")
print(f"\nLatest day ({view.date.iloc[-1].date()}): " +
      ", ".join(f"{c}={view[c].iloc[-1] or '-'}" for c in IO.OUTCOLS))
