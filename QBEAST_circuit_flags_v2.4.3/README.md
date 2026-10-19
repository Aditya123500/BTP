# QBEAST AI — Circuit & Liquidity Flags (v2.4.3)

Four flags that tell a backtest, paper or live system when an Indian stock's printed price was **not really tradable**, plus one gate column that turns them into a single yes/no:

| # | Flag | Question it answers | Function |
|---|---|---|---|
| 1 | Price Band | What % move is this stock allowed today? | `compute_price_band_flag` |
| 2 | Upper / Lower Circuit | Did the stock close locked at its band today? | `compute_circuit_hit_flag` |
| 3 | MWCB | Did the whole market hit a circuit breaker today? | `compute_mwcb_flag` |
| 4 | Staircase | Is the stock in a run of daily circuits (a "circuit ladder")? | `compute_staircase_flag` |
| — | Gate | Can I trade this stock at the next open? | `TRADE_BLOCKED` column |

All four functions are in **one file: `circuit_liquidity_flags.py`**. Every setting is in **one config file: `qbeast_flags_config.json`**.

**No forward bias:** every flag on day *t* uses only data up to and including day *t*. This is proven by automated checks on all 1,272 stocks of Final_Data (section 10).


> **v2.4.3 (18-Oct-2026):**
> - New STEP staircase: an illiquid "flat, then jump" pattern, which also covers ETFs.
> - Separate ETF rules (`*_etf` config sections).
> - Separate climbing / falling settings.
> - The owner volume rule: OHLC only when volume is zero, missing or unreliable.
> - A corporate-action guard.
> - The bundle can be imported as a package.
>
> Overwrite the 2.4.2 files to upgrade; nothing was renamed. All changes, new parameters and test results: **[UPGRADE_v2.4.3.md](UPGRADE_v2.4.3.md)**. `flags_config.legacy_v242_config()` reproduces 2.4.2 exactly.

---

## Contents

1. [Install](#1-install)
2. [Verify your setup (do this first)](#2-verify-your-setup-do-this-first)
3. [What is in the bundle](#3-what-is-in-the-bundle)
4. [Quick start: PowerShell commands](#4-quick-start-powershell-commands)
5. [Configuration: every parameter](#5-configuration-every-parameter)
6. [The four functions: inputs and outputs](#6-the-four-functions-inputs-and-outputs)
7. [Output columns: what each value means](#7-output-columns-what-each-value-means)
8. [Python usage examples](#8-python-usage-examples)
9. [Script reference](#9-script-reference)
10. [Rules: no forward bias and the trading gate](#10-rules-no-forward-bias-and-the-trading-gate)
11. [Troubleshooting](#11-troubleshooting)
12. [Known limits](#12-known-limits)

---

## 1. Install

Requirements: **Python 3.10 or newer**, **pandas 2.0 or newer**, **numpy**. Nothing else.

Copy these lines into PowerShell exactly as written (they assume the ZIP is in `E:\Downloads`; change that path if yours is elsewhere):

```powershell
cd E:\Downloads
Expand-Archive -Path E:\Downloads\QBEAST_circuit_flags_v2.4.2.zip -DestinationPath E:\Downloads -Force
cd E:\Downloads\QBEAST_circuit_flags_v2.4.2
python -m pip install -r requirements.txt
```

Tested combinations (all checks pass):

| Python | pandas | numpy |
|---|---|---|
| 3.10 | 2.2.3 | 1.26.4 |
| 3.11 | 2.0.3 | 1.24.4 |
| 3.11 | 2.2.3 | 1.26.4 |
| 3.11 | 3.0.2 | 2.4.4 |
| 3.11 (Windows) | 3.0.3 | 2.4.6 |
| 3.12 | 3.0.6 | 2.5.3 |

If `python` is not found on Windows, use `py` instead (for example `py verify_install.py`).

---

## 2. Verify your setup (do this first)

```powershell
cd E:\Downloads\QBEAST_circuit_flags_v2.4.2
python verify_install.py
```

This needs **no data**. It builds a small synthetic data folder shaped like Final_Data, then runs the tests and **every script** against it. It checks the flags that must appear: a staircase, a falling ladder, chronic illiquidity, a penny stock, a stitched NSE/BSE series, an MWCB day, intraday freezes and the early block. The last line must read:

```
RESULT: 32/32 checks passed
```

With the real data available, add a quick real-data check (the last line then reads `RESULT: 34/34 checks passed`):

```powershell
python verify_install.py --real-data "E:\Downloads\Final_Data"
```

---

## 3. What is in the bundle

| File | What it is |
|---|---|
| `circuit_liquidity_flags.py` | **The library.** The 4 flag functions, the chronic-illiquidity flag, the gate, and the bar-by-bar tracker |
| `qbeast_flags_config.json` | **The config.** Paths, workers and every flag parameter |
| `flags_config.py` | Loads and validates the config (catches typos) |
| `flags_io.py` | Shared CSV loaders and the complete EOD / intraday pipelines used by all scripts |
| `flags_for_one_day.py` | One stock, one day (or a range of days); each flag from its own call |
| `daily_backtest_loop.py` | Day-by-day causal loop over the whole universe, with a `strategy_hook()` for your strategy |
| `run_four_flags.py` | Parallel run: the 5 columns for every stock, index and intraday file |
| `call_four_functions.py` | Calls each of the 4 functions and prints what it returns |
| `example_daily_usage.py` | Runs the 3 equivalent calling patterns for one stock and proves they agree |
| `verify_install.py` | End-to-end self-test on synthetic data (section 2) |
| `test_circuit_liquidity_flags.py` | 27 unit tests |
| `requirements.txt` | pandas, numpy |
| `README.md` | This file |
| `QBEAST_AI_Circuit_Liquidity_Flags_SPEC_v2.md` | Design specification |
| `QBEAST_Circuit_Liquidity_Flags_Guide.pdf` | Technical & functional guide with use cases |
| `CHANGELOG.md` | Version history |

---

## 4. Quick start: PowerShell commands

Run these **in PowerShell** from the bundle folder. Anything in a Python code block (section 8) goes inside a `.py` file, never into PowerShell.

| I want to… | Command |
|---|---|
| Check my setup | `python verify_install.py` |
| See the flags for one stock on the latest day (live, after the close) | `python flags_for_one_day.py --symbol INDOTHAI` |
| See the flags for one stock on a past day | `python flags_for_one_day.py --symbol INDOTHAI --date 2021-12-24` |
| Run a daily backtest loop for one stock | `python flags_for_one_day.py --symbol INDOTHAI --from 2021-12-15 --to 2022-01-20 --verify` |
| Get the 5 columns for every stock and index | `python run_four_flags.py --intraday` |
| Run the day-by-day loop over all stocks | `python daily_backtest_loop.py --verify` (run `run_four_flags.py` first for `--verify`) |
| See what each function returns | `python call_four_functions.py --symbol INDOTHAI` |
| Use another data folder | add `--data "D:\MyData\Final_Data"` to any command |
| Use another config | add `--config my_config.json` to any command |

Example output of `python flags_for_one_day.py --symbol INDOTHAI --date 2021-12-24`:

```
INDOTHAI flags at the close of 2021-12-24:
   close          27.65
   PRICE_BAND     5
   CIRCUIT        UPPER
   MWCB           -
   STAIRCASE      CLIMBING
   TRADE_BLOCKED  STAIRCASE
   -> do NOT buy, sell or exit this stock at the next open (MtM continues)
```

---

## 5. Configuration: every parameter

### How the config is found

The first match wins:

1. `--config path.json` on the command line (or `load_config("path.json")` in Python)
2. The environment variable `QBEAST_FLAGS_CONFIG`
3. `qbeast_flags_config.json` next to the scripts
4. Built-in defaults (identical to the shipped file)

Command-line options (`--data`, `--workers`, `--check-every`, `--out`) override the config for that run.

**Rules:**

- Keys starting with `_` are comments.
- A key you leave out keeps its default, so your own config can be as small as `{"staircase": {"start_confirm_days": 4}}`.
- An unknown or misspelt key stops the run with a clear message, for example `unknown key 'staircase.start_confrim_days'`.
- An invalid value (such as `end_confirm_days: 0`) is also refused.

### `paths`

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | `E:\Downloads\Final_Data` | Root data folder (override with `--data`) |
| `stocks_eod_subdir` | `Final_Clean_Stocks_EOD_Data` | Daily stock CSVs, one per symbol (`<SYMBOL>.csv`) |
| `indices_eod_subdir` | `Final_Clean_Indices_EOD_Data` | Daily index CSVs |
| `stocks_intraday_subdir` | `Final_Clean_Stocks_INTRADAY_Data` | Intraday stock CSVs (same file names as EOD) |
| `indices_intraday_subdir` | `Final_Clean_Indices_INTRADAY_Data` | Intraday index CSVs (optional; enables intraday MWCB halt windows) |
| `mwcb_index_files` | `{"NIFTY50": "Nifty 50.csv", "SENSEX": "SENSEX.csv"}` | Index files used for MWCB; NIFTY50 also gives the trading calendar. Missing files are skipped |
| `output_dir` | `null` | `null` = outputs go inside `data_dir`; or a folder path |

### `run`

| Key | Default | Meaning |
|---|---|---|
| `workers` | `25` | Parallel processes (25 suits a 16-core / 32-thread CPU; use fewer on smaller machines) |
| `check_every` | `10` | Causality self-check on 1 in N stocks (`1` = every stock, `0` = off) |
| `mp_start_method` | `null` | `null` = platform default (spawn on Windows); for debugging only |

### `circuit` (Flag 2, plus the band inference used for Flag 1)

| Key | Default | Meaning / when to change |
|---|---|---|
| `lock_mode` | `close_locked` | `close_locked`: close = high (upper) or low (lower). `strict`: open = high = low = close. Strict misses locked days with a small opening wick |
| `tick_size` | `0.05` | Exchange tick in ₹. Tolerance = 1 tick / previous close + `tol` |
| `tol` | `0.0001` | Extra relative tolerance (fraction) |
| `band_candidates` | `[2, 5, 10, 20]` | Allowed price bands in % |
| `infer_band` | `true` | Infer the band causally when no `upper_band_pct` / `lower_band_pct` columns are given |
| `band_lookback` | `20` | Recent sessions whose range bounds an inferred band |
| `price_eq_rel_tol` | `1e-6` | Relative tolerance for price equality (open = high, and so on) |
| `min_band_ticks` | `2` | A band narrower than this many ticks is `tick_degenerate` (penny stock): reported, never feeds Staircase or Chronic |
| `fine_tick_size` | `0.01` | Tick assumed once prices leave the 0.05 grid |
| `tick_grid_lookback` | `10` | Recent closes used to detect the finer grid |
| `offgrid_max_slack_pct` | `0.5` | Cap on the tolerance for off-grid (back-adjusted or fine-tick) prices |
| `intraday_min_pinned_bars` | `3` | Intraday: consecutive bars pinned at the band that make a freeze |
| `intraday_require_thin_vol` | `false` | Intraday: also require thin volume for a freeze |
| `intraday_vol_frac` | `0.1` | Intraday thin-volume threshold (share of the recent median) |
| `intraday_vol_lookback` | `20` | Intraday bars in that median |
| `intraday_candidate_mode` | `false` | `true` = test every candidate band intraday when the session band is unknown. Causes false freezes on large caps |
| `volume_quality` | `true` | **v2.4.2.** Classify each day's volume (`volume_status`): REAL, ZERO (true no-trade: zero volume, price unchanged), MISSING (blank / negative / infinite, zero volume while the price moved, or the `zero_run_missing`-th zero-volume day in a row so far), GAP. `false` = v2.4.1 |
| `zero_run_missing` | `20` | **v2.4.2.** From this many consecutive zero/blank-volume days on (counted causally), volume is treated as missing data, not as no trading |

### `staircase` (Flag 4)

| Key | Default | Meaning / when to change |
|---|---|---|
| `start_confirm_days` (S) | `5` | Consecutive same-direction ladder days needed to tag. Lower = earlier and more tags |
| `end_confirm_days` (E) | `2` | Consecutive NORMAL days needed to untag |
| `vol_frac` | `null` | `null` = no thin-volume requirement for a ladder day; `0.1` = ladder-day volume must be under 10% of the baseline |
| `volume_lookback` | `20` | Clean trading days in the volume baseline (median) |
| `normal_vol_frac` | `0.5` | A NORMAL (untagging) day needs volume ≥ this × the baseline |
| `min_baseline_obs` | `null` | Observations before the baseline counts; `null` = max(3, volume_lookback // 4) |
| `intraday_early_block` | `true` | Block intraday when yesterday closed at S − 1 ladder days and every bar today is pinned in that direction |
| `vol_avg_days` | `3` | **v2.4.2.** Days in the trailing average of REAL volume (ZERO days count as 0, MISSING days are skipped). Used for the tag and the untag. `1` = v2.4.1 (the day's own volume) |
| `tag_vol_frac` | `0.5` | **v2.4.2.** Tag only when that average < this × the baseline (an illiquid ladder). A ladder still trading heavy volume stays `BUILDING` with `STAIRCASE_VOL_WARN = LADDER_HIGH_VOL`. `null` = v2.4.1 (no volume test for the tag) |
| `missing_volume_fallback` | `true` | **v2.4.2.** When the day's volume is MISSING (or there is no baseline yet), tag and untag are decided on OHLC only and the day is marked in `STAIRCASE_VOL_WARN`. `false` = v2.4.1 (no untag without volume, so such a tag never ends) |

### `chronic` (chronic illiquidity, part of `TRADE_BLOCKED`)

The trailing window is measured in sessions. The stock is tagged when any measure reaches its `enter_*` level, and untagged only when all measures fall below their `exit_*` levels.

| Key | Default | Meaning |
|---|---|---|
| `window` | `60` | Trailing sessions |
| `min_obs` | `20` | Sessions needed before the flag can switch on |
| `enter_single_price` / `exit_single_price` | `0.2` / `0.1` | Share of single-price days (O = H = L = C, not at a band) |
| `enter_no_trade` / `exit_no_trade` | `0.2` / `0.1` | Share of no-trade days (zero volume, gap-filled, or a trading day missing from the file) |
| `enter_circuit` / `exit_circuit` | `0.3` / `0.15` | Share of circuit-locked days |
| `missing_volume_as_no_trade` | `false` | **v2.4.2.** `false` = a MISSING-volume day counts as traded (volume unknown), not as a no-trade day. `true` = v2.4.1 |

### v2.4.2: volume in the staircase, and missing volume

- **Tag** = S consecutive ladder days (OHLC: close locked at the band) **and** the average real volume of the last `vol_avg_days` (3) days < `tag_vol_frac` (0.5) × baseline. On real data (1,272 stocks, 2002–2026) this halves the staircase days (26,196 → 14,155): the removed days are ladders that kept trading heavy volume at the band (tradable). INDOTHAI Dec-2021 is tagged on 28-Dec instead of 23-Dec (534k shares traded on 23-Dec).
- **Untag** = E consecutive NORMAL days; NORMAL = OHLC-normal **and** the same 3-day average ≥ `normal_vol_frac` (0.5) × baseline. Volume must be back, not just one day.
- **Missing volume** (blank, negative, zero while the price moved, or a long zero run): tag and untag fall back to OHLC only, with a warning (`TAGGED_NO_VOL`, `NORMAL_NO_VOL`, `UNTAGGED_NO_VOL`). In v2.4.1 a staircase whose volume went missing could never be untagged. In the chronic flag, a missing-volume day is not a no-trade day.
- **Sensitivity** (stock staircase days / episodes): v2.4.1 26,196 / 1,416; avg 1 day < 0.5× 17,814 / 799; avg 3 < 1.0× 17,155 / 894; **avg 3 < 0.5× (default) 14,155 / 673**; avg 5 < 0.5× 12,642 / 572; avg 3 < 0.25× 11,228 / 479.
- **Exactly v2.4.1:** `flags_config.legacy_v241_config()` (or put the `LEGACY_V241` overrides in your JSON). Checked bit-identical with v2.4.1 on 1,861 real files (4.84 M rows: 1,272 stocks + 589 ETFs), batch and tracker.

### v2.4.3: STEP staircase, ETF rules, directions, volume, corporate actions

**`staircase` (STEP)**
- `step_enabled`
- `step_tag_stale_run` (3)
- `step_min_stale` (2)
- `step_jump_pct` (2.0)
- `step_window` (40)
- `step_events_to_tag` (2)
- `step_end_confirm_days` (2)
- `step_stale_vol_frac` (0.2)
- `step_price_eq_rel_tol`
- `step_exempt_pattern` (regex; e.g. "LIQUID|OVERNIGHT")

**`staircase` (volume)**
- `zero_volume_as_missing` (true)
- `vol_reliability_window` (60)
- `vol_reliability_min` (0.5)

**`staircase` (direction)**
- `ladder_break_days` (0)
- `start_confirm_days_climbing` / `_falling`
- `end_confirm_days_climbing` / `_falling`
- `tag_vol_frac_climbing` / `_falling`
- `ladder_break_days_climbing` / `_falling`
- `step_jump_pct_climbing` / `_falling` (null = the shared value)

**`circuit`**
- `ca_jump_pct` (35)

**`chronic`**
- `min_traded_value` (null)
- `traded_value_window` (20)
- `traded_value_exit_mult` (1.5)

**ETF rule sets**
- `circuit_etf`, `staircase_etf`, `chronic_etf`: list only the keys whose ETF value differs.
- The asset class comes from each file's `product_class` / `asset_class` column.

**Paths**
- `paths.etfs_eod_subdir`: ETF folder processed by `run_four_flags.py`.

Details and the rule definitions: [UPGRADE_v2.4.3.md](UPGRADE_v2.4.3.md).

### `mwcb` (Flag 3)

| Key | Default | Meaning |
|---|---|---|
| `basis` | `auto` | Reference close for the limits: `auto` = previous quarter's last close before `quarterly_basis_before`, previous day's close after it; or `prev_close` / `quarterly` |
| `quarterly_basis_before` | `2013-07-01` | Cut-over date for `auto` (to be confirmed against the SEBI circular) |
| `use_high_low` | `true` | Trigger on the index's intraday extreme (recommended; the close alone missed 13 Mar 2020) |
| `levels` | `[10, 15, 20]` | Trigger levels in % |
| `reopen_auction_minutes` | `15` | Pre-open call auction after each halt (intraday) |
| `market_close` | `15:30` | Session end, for "halt for the rest of the day" (intraday) |
| `halt_rules` | SEBI table | Per level: list of `[until HH:MM, halt minutes]`; `null` = rest of the day, `0` = no halt |

### `gate`

| Key | Default | Meaning |
|---|---|---|
| `block_on_mwcb_day` | `true` | On an MWCB day, `TRADE_BLOCKED = MWCB_DAY`, so no orders are placed at that close for the next open. Set `false` to trade the next morning |

---

## 6. The four functions: inputs and outputs

Each function returns **the table you give it, with new columns added**. Row *t* uses rows up to *t* only.

### Flag 1 — `compute_price_band_flag(df)`

Use this only with point-in-time band data. Without it, Flag 2 infers the band and reports it as `PRICE_BAND`.

- **Input:** `symbol`, `date`, `upper_band_pct`, `lower_band_pct` (0–100; `inf` = no band; NaN = unknown)
- **Adds:** `band_known`, `band_asymmetric`, `band_tightened`, `band_widened`

### Flag 2 — `compute_circuit_hit_flag(df, mode="eod" | "intraday", circuit_params=cfg.circuit)`

- **Input:** `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`
  - Optional: `prev_close`, `upper_band_pct` / `lower_band_pct`, `exchange`, `_gap_filled`
- **Adds (EOD):**
  - `circuit_locked_dir` (`upper` / `lower`)
  - `band_hit_dir`, `frozen`, `single_price`, `tick_degenerate`
  - `band_upper_used` (band in force), `band_est_next` (band for tomorrow)
  - `open_at_upper` / `open_at_lower`, `data_unknown`
- **Adds (intraday):** `pinned`, `pinned_run_len`, `intraday_freeze`, `freeze_dir`, `locked_since_open_dir`

### Flag 3 — `compute_mwcb_flag(index_df, **cfg.mwcb_kwargs("eod" | "intraday"))`

- **Input:** `index_name`, `date`, `close`; `high` and `low` recommended
- **Adds (EOD):** `mwcb_level` (0 / 10 / 15 / 20), `mwcb_dir`, `mwcb_triggered`, `extreme_up_pct`, `extreme_dn_pct`
- **Adds (intraday):** `mwcb_halt_active`, `mwcb_reopen_auction`, `mwcb_halt_rest_of_day`
- Before joining onto stocks, call `aggregate_mwcb_by_date()`: one row per date, the maximum across NIFTY and SENSEX.

### Flag 4 — `compute_staircase_flag(circuit_output, cfg.staircase)`

- **Input:** the output of Flag 2
- **Adds (EOD):**
  - `staircase` (True = tagged, do not trade)
  - `staircase_state` (DORMANT / BUILDING / CONFIRMED / COOLING)
  - `staircase_dir` (`climbing` / `falling`)
  - `ladder_run_len`, `normal_day_count`, `staircase_event_id`, `day_class`, `vol_baseline`
- **Adds (intraday, `mode="intraday"`):** `staircase_intraday`, `eod_staircase_prev`, `early_block`

### Extras

- `compute_chronic_illiquidity_flag(df, cfg.chronic)` — adds `chronic_illiquid`
- `build_universe_exclusion_table(df, mwcb_by_date, **cfg.gate_kwargs())` — adds `trade_blocked`, `block_reason`, and the fill-feasibility columns
- `four_flag_columns(table)` — adds the readable `PRICE_BAND`, `CIRCUIT`, `MWCB`, `STAIRCASE`, `TRADE_BLOCKED`
- `CircuitLiquidityTracker` — bar by bar: `update_eod(bar)`, `update_intraday(bar)`; picklable
- `parse_dates` — reads ISO dates as ISO and dd-mm-yyyy as day-first

---

## 7. Output columns: what each value means

| Column | EOD values | Intraday values |
|---|---|---|
| **PRICE_BAND** | `2` `5` `10` `20` (band in force); `0/5` asymmetric (supplied data); `NONE` no band; `UNKNOWN` no data or evidence yet | session band from the previous close |
| **CIRCUIT** | `UPPER` / `LOWER` (closed locked at the band); `UPPER_1TICK` / `LOWER_1TICK` (penny stock, info only); `UPSIDE_LOCKED`; blank | `UPPER` / `LOWER` inside a freeze; blank |
| **MWCB** | `LOWER_10`, `LOWER_15`, `UPPER_20`… (same for every stock that day); blank | `HALT_10` / `AUCTION_10`…; `NA` without intraday index data |
| **STAIRCASE** | `CLIMBING` / `FALLING` = tagged, **do not trade**; `BUILDING` = ladder forming, still tradable; blank | `CLIMBING` / `FALLING` (from the previous close); `EARLY_BLOCK`; blank |
| **TRADE_BLOCKED** | `NO` = tradable; else `STAIRCASE`, `CHRONIC`, `MWCB_DAY`, joined by `+` | `NO`; else `STAIRCASE`, `CHRONIC`, `MWCB_HALT` |
| **STAIRCASE_VOL_WARN** (v2.4.2, extra column; `IO.OUTCOLS` is unchanged, `IO.OUTCOLS_ALL` includes it) | `TAGGED_NO_VOL` / `UNTAGGED_NO_VOL` / `NORMAL_NO_VOL` (decided on OHLC only: volume missing); `LADDER_HIGH_VOL` (S+ ladder days but volume not thin, so not tagged yet); blank | blank (the tag is decided at EOD) |

Index files show `NA` in every column except MWCB.

---

## 8. Python usage examples

Put these in a `.py` file in the bundle folder (or add the folder to `sys.path`). They read the data folder from the config.

### 8.1 One stock, today, each flag separately (after the close)

```python
import flags_io as IO
from flags_config import load_config
from flags_for_one_day import get_price_band, get_circuit, get_mwcb, get_staircase, get_trade_blocked

cfg = load_config()
data = cfg.data_dir()
stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / "INDOTHAI.csv")
nifty = IO.load_eod(cfg.sub("indices_eod_subdir", data) / "Nifty 50.csv")

day = stock.date.iloc[-1]                 # today = the last bar (live) or any past day (backtest)
s = stock[stock.date <= day]              # history up to and including today only
n = nifty[nifty.date <= day]

print("PRICE_BAND   ", get_price_band(s))
print("CIRCUIT      ", get_circuit(s))
print("MWCB         ", get_mwcb(n))
print("STAIRCASE    ", get_staircase(s))
print("TRADE_BLOCKED", get_trade_blocked(s, n))
```

### 8.2 Daily backtest loop for one stock (streaming tracker)

```python
import flags_io as IO
from flags_config import load_config
from daily_backtest_loop import label

cfg = load_config()
data = cfg.data_dir()
stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / "INDOTHAI.csv")
mkt = IO.load_market(cfg, data)                          # NIFTY 50 calendar + MWCB per date
mw = mkt.mw_daily.set_index("date")

tracker = cfg.tracker("INDOTHAI", calendar=mkt.calendar)
for bar in stock.to_dict("records"):                     # one day at a time, in date order
    f = tracker.update_eod(bar)                          # flags as of today's close
    lvl = int(mw.mwcb_level.get(bar["date"], 0))
    cols = label(f, lvl, mw.mwcb_dir.get(bar["date"]) if lvl else None, cfg.gate["block_on_mwcb_day"])
    if cols["TRADE_BLOCKED"] != "NO":
        continue                                         # no buy / sell / exit today; MtM continues
    # ... your strategy here; orders fill at the next bar's open
print("last day:", cols)
```

### 8.3 Live: continue from yesterday's state each evening

```python
import pickle
import flags_io as IO
from flags_config import load_config

cfg = load_config()
data = cfg.data_dir()
stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / "INDOTHAI.csv")
history, today_bar = stock.iloc[:-1], stock.iloc[-1].to_dict()

# one-time: build the state from history and save it
tracker = cfg.tracker("INDOTHAI")
for bar in history.to_dict("records"):
    tracker.update_eod(bar)
with open("INDOTHAI_state.pkl", "wb") as fh:
    pickle.dump(tracker, fh)

# every evening after the close: load, feed today's bar only, save
with open("INDOTHAI_state.pkl", "rb") as fh:
    tracker = pickle.load(fh)
flags = tracker.update_eod(today_bar)
with open("INDOTHAI_state.pkl", "wb") as fh:
    pickle.dump(tracker, fh)
print(today_bar["date"].date(), flags["staircase_state"], "blocked" if flags["staircase"] else "tradable")
```

### 8.4 Batch: whole history in one call, then read row t on day t

```python
import flags_io as IO
from flags_config import load_config

cfg = load_config()
data = cfg.data_dir()
mkt = IO.load_market(cfg, data)
stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / "INDOTHAI.csv")
flags = IO.eod_flags(stock, cfg, mkt.calendar, mkt.mw_daily)       # every column + the 5 readable ones
print(flags[["date", "close"] + IO.OUTCOLS].tail())
```

### 8.5 The four functions directly, with your own parameters

```python
import circuit_liquidity_flags as C
import flags_io as IO
from flags_config import load_config

cfg = load_config()
data = cfg.data_dir()
stock = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / "INDOTHAI.csv")
nifty = IO.load_eod(cfg.sub("indices_eod_subdir", data) / "Nifty 50.csv").assign(index_name="NIFTY50")

flag2 = C.compute_circuit_hit_flag(stock, mode="eod", circuit_params=cfg.circuit)
flag4 = C.compute_staircase_flag(flag2, C.StaircaseParams(start_confirm_days=4))   # override one parameter
flag3 = C.compute_mwcb_flag(nifty, **cfg.mwcb_kwargs())
print(flag4.staircase.sum(), "staircase days;", int(flag3.mwcb_triggered.sum()), "MWCB days")
```

### 8.6 Intraday bars for one stock

```python
import flags_io as IO
from flags_config import load_config

cfg = load_config()
data = cfg.data_dir()
bars = IO.load_intraday(cfg.sub("stocks_intraday_subdir", data) / "INDOTHAI.csv")
eod = IO.load_eod(cfg.sub("stocks_eod_subdir", data) / "INDOTHAI.csv")     # gives prev close + band + tag
out = IO.intraday_flags(bars, cfg, eod)
print(out[["date", "close"] + IO.OUTCOLS].query("CIRCUIT != ''").head())
```

---

## 9. Script reference

Every script accepts `--config` and `--data`. Run any script with `-h` for its full help.

| Script | Main options | Writes |
|---|---|---|
| `run_four_flags.py` | `--workers N`, `--check-every N`, `--intraday`, `--limit N`, `--out DIR` | `<data>\_four_flags_out\`: `eod_stocks\<SYMBOL>.csv`, `eod_indices\<INDEX>.csv`, `intraday_stocks\<SYMBOL>.csv.gz`, `four_flags_eod_stocks_all.csv.gz`, `four_flags_summary.csv`, `staircase_episodes.csv`, `four_flags_report.txt` |
| `daily_backtest_loop.py` | `--workers N`, `--limit N`, `--verify`, `--out DIR` | `<data>\_daily_loop_out\`: `daily_flags_all.csv.gz`, `daily_summary.csv`, `trackers_state.pkl` |
| `flags_for_one_day.py` | `--symbol S` (required), `--date D`, `--from D --to D`, `--verify` | prints to the screen |
| `call_four_functions.py` | `--symbol S` | prints to the screen |
| `example_daily_usage.py` | `--symbol S`, `--check-days N` | prints; exit code 1 if the 3 patterns disagree |
| `verify_install.py` | `--real-data DIR`, `--workers N`, `--keep` | prints; exit code 0 = all checks passed |
| `test_circuit_liquidity_flags.py` | set `$env:QBEAST_DATA` to add the real-data tests | prints PASS / FAIL |

**Expected input files:**

- **Stock EOD CSV:** `date` (dd-mm-yyyy or ISO), `open`, `high`, `low`, `close`, `volume`. Optional: `symbol` (defaults to the file name), `exchange`, `source`, `_gap_filled`, `upper_band_pct`, `lower_band_pct`.
- **Index CSV:** the same columns.
- **Intraday CSV:** a timestamp column (`datetimestamp`, `datetime`, `timestamp`, `date`+`time` or `date`; ISO with or without `+05:30`, or epoch) plus `open`, `high`, `low`, `close`, `volume`.

---

## 10. Rules: no forward bias and the trading gate

1. Row *t* is computed from bars up to and including *t* only. Nothing is re-marked afterwards and no end date is back-dated.
2. Row *t* is the state **at the close of day t**. Decide at *t*; the order fills at *t+1*'s open.
3. Batch, day-by-day and bar-by-bar give identical values. `run_four_flags.py` re-proves it on every run: cutting the data at a random day never changes earlier rows, and the streaming tracker matches the batch.
4. Only the execution simulator may look at bar *t+1* (`open_at_upper` / `open_at_lower`), to decide whether a fill was physically possible there.

**While `TRADE_BLOCKED` is not `NO`:** no new buy, no new sell, no exit; mark-to-market continues. A staircase is untagged after 2 consecutive normal days with real volume.

**Any staircase is blocked in both directions.** A CLIMBING staircase (upper-circuit ladder) and a FALLING staircase (lower-circuit ladder) are treated identically: no buy and no sell. The direction only changes the label. `verify_install.py` and the unit tests check this explicitly for both directions.

---

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| PowerShell says `Missing opening '(' after keyword 'for'` or `Missing argument in parameter list` | Python code was pasted into PowerShell. Put it in a `.py` file and run `python myfile.py` |
| `ERROR: data folder not found` | Set `paths.data_dir` in the config, or pass `--data "E:\Downloads\Final_Data"` |
| `ConfigError: unknown key '…'` | A typo in the config; the message lists the valid keys |
| `ConfigError: … not valid JSON (line N …)` | JSON syntax: use double quotes, no trailing commas, and write Windows paths as `E:\\Downloads\\...` |
| Old behaviour or old numbers | Check the version: `python -c "import circuit_liquidity_flags as C; print(C.__version__)"` → `2.4.2` |
| `ModuleNotFoundError: pandas` | `python -m pip install -r requirements.txt` |
| `flags_for_one_day.py --from/--to` is slow over years | Expected: it re-reads history each day. Use `daily_backtest_loop.py` or the tracker (section 8.2) for long runs |
| Dates look wrong (months and days swapped) | The loaders already handle this; if you load CSVs yourself, use `C.parse_dates(column)` |
| `NativeCommandError` lines in PowerShell | Harmless warning text written to stderr; warnings are silenced in the scripts |

---

## 12. Known limits

- **No point-in-time band data** in Final_Data. Bands are inferred from price action, so liquid and F&O stocks mostly show `UNKNOWN`. Supplying `upper_band_pct` / `lower_band_pct` columns (or `inf` for F&O) makes PRICE_BAND exact with no code change.
- **F&O stocks** can show a false circuit when they touch their flexible 10% band (for example HFCL).
- **Back-adjusted prices** make circuit detection before about 2005 approximate.
- **SENSEX** is not in Final_Data, so NIFTY 50 alone drives MWCB. The `quarterly_basis_before` date and the 21 Jan 2008 / 24 Oct 2008 triggers still need confirming.
- **Intraday** is validated on 10 real stocks plus synthetic data; illiquid small-cap intraday files are pending.
- **MCX / NCDEX** commodity limits are out of scope.
