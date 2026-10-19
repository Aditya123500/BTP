# QBEAST circuit & liquidity flags: v2.4.2 → v2.4.3

**Upgrade:** overwrite the v2.4.2 files with the v2.4.3 files.
- No file, function, class, parameter or output column was renamed or removed.
- Everything new is either a keyword argument with a default, a new column, a new config key or section, or a new file (`__init__.py`, this document).
- `TRADE_BLOCKED` keeps its name and meaning: "NO" = tradable, otherwise the reasons joined by `+`.

**Note for team PCs:** overwriting also replaces `qbeast_flags_config.json`. If you edited your copy (paths, workers…), put the same values back after the upgrade. Every new key has a safe default, so an old v2.4.2 JSON also works unchanged with v2.4.3.

## 1. What changed and why

| Area | v2.4.2 | v2.4.3 | Why (evidence) |
|---|---|---|---|
| ETF staircases | The staircase needs a close locked at a 2/5/10/20% band; ETFs never stay at a band (longest run 2 days in 589 ETF files), so ETFs could never be tagged | New STEP staircase: an illiquid "flat, then jump" pattern, no band needed. Tagged → `TRADE_BLOCKED` reason `STEP_STAIRCASE` (no buy, no sell, no exit, exactly like a staircase). Works for stocks and ETFs | Owner request: ETF staircase = price flat for days, then jumps in steps |
| Stocks vs ETFs | One rule set | Separate rule sets: `circuit_etf`, `staircase_etf`, `chronic_etf` (only the keys that differ). Asset class per file from its `product_class` / `asset_class` column (ETF vs EQUITY); output column `ASSET_CLASS` | Owner request [1] |
| Climbing vs falling | Same S, E, volume test | `start_confirm_days_*`, `end_confirm_days_*`, `tag_vol_frac_*`, `ladder_break_days_*`, `step_jump_pct_*` (`_climbing` / `_falling`). None = the shared value | Owner request [2] |
| Volume | Real volume in tag / untag; OHLC fallback only when volume is MISSING. A ZERO day counted as volume 0 | Owner rule [3]: real volume wherever it exists; OHLC (with a warning) when volume is ZERO, MISSING or in an unreliable stretch (< 50% real-volume sessions in the last 60, typical before 2010). New column `staircase_vol_reason` (ZERO / MISSING / UNRELIABLE) | Zero / missing volume is not information about trading |
| Interrupted ladders | Any non-ladder day resets the run | Optional `ladder_break_days` (per direction): break days tolerated while BUILDING. Default 0 = v2.4.2 | 54 cases in a 21-stock sample: 3 locked days, 1 break, locked again |
| Corporate actions | A split / bonus / ETF unit split looked like a normal day and polluted the band inference for 20 sessions | `ca_jump_pct` (35%): a bigger move that is not at a matched band is `ca_suspect`. Staircase and STEP hold their state; the day does not feed band inference | Real ETF files: unit splits and 100× data spikes (IVZINGOLD, GOLDIETF, GILT5YBEES) |
| Absolute illiquidity | Only relative tests (a stock vs its own past) | Optional `chronic.min_traded_value` (₹ median of close × real volume) with exit hysteresis; off by default; can differ for ETFs | Always-illiquid names never look "thin" vs their own baseline |
| Blank symbol cells | `load_eod` filled them with the file name. For ETF files (`AXISBPSETF_NSE.csv` holds `AXISBPSETF`) the blank rows became a second symbol and split one history in two | Filled with the file's own symbol (most frequent value); blank `product_class` too | 319 ETF files have blank symbol cells |
| ETF folder in `run_four_flags` | Stocks + indices only | `paths.etfs_eod_subdir` (e.g. `Final_ETF_EoD_Data`) → `eod_etfs\`, `four_flags_summary_etfs.csv`, `staircase_episodes_etfs.csv`, `step_episodes_etfs.csv` | Asset-class rules need ETF runs |
| Packaging | Plain files only | Also importable as a package (`__init__.py`, relative-or-absolute imports) | The flags will become part of the qbeast_exec wheel |
| Exact old behaviour | `legacy_v241_config()` | + `legacy_v242_config()`: bit-identical v2.4.2 (checked on 589 ETF + 23 stock files, batch and tracker) | Safe migration |

## 2. New parameters (all keyword, all with defaults)

**circuit**
- `ca_jump_pct` = 35.0 (None = off).

**staircase: STEP**
- `step_enabled` = True
- `step_tag_stale_run` = 3
- `step_min_stale` = 2
- `step_jump_pct` = 2.0 (%)
- `step_window` = 40
- `step_events_to_tag` = 2
- `step_end_confirm_days` = 2
- `step_stale_vol_frac` = 0.2
- `step_price_eq_rel_tol` = 1e-6
- `step_exempt_pattern` = None

**staircase: volume**
- `zero_volume_as_missing` = True
- `vol_reliability_window` = 60
- `vol_reliability_min` = 0.5 (None = off)

**staircase: direction**
- `ladder_break_days` = 0
- `*_climbing` / `*_falling` for `start_confirm_days`, `end_confirm_days`, `tag_vol_frac` (0 = no test), `ladder_break_days`, `step_jump_pct`. All default None (= the shared value).

**chronic**
- `min_traded_value` = None
- `traded_value_window` = 20
- `traded_value_exit_mult` = 1.5

**Config sections**
- `circuit_etf`, `staircase_etf`, `chronic_etf`: the same key names, listing only those that differ for ETFs.
- `paths.etfs_eod_subdir` = null.

**Library API**
- `StaircaseParams.for_class("ETF")`, `.dir_value(name, direction)`.
- `CircuitParams.for_class`, `ChronicParams.for_class`.
- `asset_class_of(label)`.
- `CircuitLiquidityTracker(..., asset_class=None)`: the class comes from the first bar's `product_class` / `asset_class` when it is not given.
- `cfg.tracker(symbol, calendar, asset_class=None)`.
- `flags_io.step_episodes(o)`.

**New columns**
- `asset_class_used` / `ASSET_CLASS`
- `ca_suspect`
- `staircase_vol_reason`
- `ladder_break_used`
- `step_*` (stale day, stale run, event, events in window, state, tag, direction, event id, normal count, warning) / `STEP`
- `traded_value_med`
- `low_traded_value`

## 3. STEP staircase rule (causal, per bar t)

- **STALE bar**
  - The close equals the previous close (relative tolerance 1e-6).
  - **and** there was no real trading: volume ZERO, or real volume < 0.2 × baseline (the median of the last 20 real volumes on non-stale days), or a single-price bar (O=H=L=C).
  - When volume is MISSING / ZERO / unreliable, the bar is judged on price alone, with warning `STALE_NO_VOL`.
- **STEP event:** the first non-stale bar after ≥ 2 stale bars whose move is ≥ 2% (direction-specific values allowed). Its direction (climbing / falling) is the sign of the move.
- **TAG:** either of
  - 3 stale bars in a row (direction FLAT until a jump), or
  - a STEP event that makes ≥ 2 events in the last 40 bars.
- **UNTAG:** 2 NORMAL bars in a row. A NORMAL bar is one where the price moved, it was not a step, and the 3-day average real volume is ≥ 0.5 × baseline. With MISSING volume it is judged on price alone, with a warning.
- **Other bars:** gap-filled bars, exchange switches and CA-suspect days hold the state.
- **Gate:** TRADE_BLOCKED `STEP_STAIRCASE`: no buy, no sell, no exit while tagged. A holding stays held until untagged (owner rule, 18-Oct-2026).

## 4. Sandbox results (sample data, cloud)

| Check | Result |
|---|---|
| Unit tests | 60 / 60: the 36 from v2.4.2 + 13 STEP + 11 v2.4.3. Every new test was checked by breaking the code on purpose: 12 deliberate bugs, each caught |
| `verify_install.py` | 60 / 60 (new sections 7c STEP, 7d asset classes / ETF folder / directions / package import) |
| Upgrade simulation: the v2.4.2 folder (`QBEAST_circuit_flags_v2.4.2`) overwritten with the v2.4.3 files | `pytest` 60 / 60, `python test_circuit_liquidity_flags.py` 60 / 60, `verify_install.py` 60 / 60; package import OK |
| `legacy_v242_config()` = v2.4.2, every v2.4.2 column | 589 / 589 ETF files, 23 / 23 stock files; tracker = batch 59 / 59 ETF + 23 / 23 stock |
| ETFs, v2.4.3 defaults | Blocked ETF-days 87,866 → 88,645 (+779, +0.9%); STEP days 7,774, mostly already chronic; CA-suspect days 54 (unit splits, 100× data spikes) |
| Liquid ETFs (NIFTYBEES, GOLDBEES, JUNIORBEES, MID150BEES, MON100, MAFANG, METALIETF…) | 0 STEP days |
| Stocks (21-stock sample incl. INDOTHAI, RELIANCE, illiquid names) | Blocked days 13,302 → 13,625 (+2.4%); staircase days 1,025 → 1,147 (META: volume unreliable / zero → OHLC basis); RELIANCE, DMART, NBCC unchanged |

**Still to do on the full data (PC, after the tier-C run):**
- The 1,272 stocks + 589 ETFs from the project folder: parity, before/after counts.
- Calibration of the per-class and per-direction defaults. Today the ETF sections are empty, and the direction values = the shared v2.4.2 values (owner decision).

## 5. Not changed
- **`TRADE_BLOCKED` semantics.** Tagged = no new buy, no new sell, no exit, both directions. This is the owner rule of 26-Sep-2026, re-confirmed 18-Oct-2026.
- **Chronic thresholds; MWCB rules; intraday early block** (circuit ladders only; STEP is decided at EOD and carried into the next session).
- **`QBEAST_Circuit_Liquidity_Flags_Guide.pdf`** still describes 2.4.1. README, SPEC, CHANGELOG and this file cover 2.4.3.
