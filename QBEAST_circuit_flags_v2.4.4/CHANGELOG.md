# Changelog: QBEAST AI Circuit & Liquidity Flags

## 2.4.4 (2026-10-20): final stock / ETF calibration

- Circuit staircase uses 5 same-direction locked sessions and releases after 3 normal sessions.
- STEP keeps the 3-session and two-events-within-40 rules, with a 20% stock / 10% ETF stale-volume cutoff; 2 normal sessions release it.
- ETF chronic rule adds a ₹250,000 median traded-value floor from 2020-01-01, with release at ₹375,000. Stock absolute floor stays disabled.
- Added effective-date handling for the ETF floor; pre-effective observations warm the trailing median but cannot trigger the floor.
- Added targeted calibration checks and updated the shipped configuration and submission guide.
- Aligns STEP with the final rule: zero volume qualifies as no real trading; missing volume alone does not unless OHLC is single-price. Chronic percentages now wait for a full 60-session window, and ETF value uses a full 20-observation median.
- The runner aggregates per-symbol files in the parent process instead of serializing full multi-year frames from workers, reducing peak memory for the submission dataset.
- Full historical ETF validation was not run: the supplied workspace has no ETF EOD input in the configured QBEAST layout. Synthetic rule checks are included; see `UPGRADE_v2.4.4.md`.

## 2.4.3 (2026-10-18): STEP staircase, separate ETF and climbing / falling rules, owner volume rule

Drop-in for 2.4.2: no file, function, class, parameter or column was renamed or removed. Overwrite the 2.4.2 files. Full comparison table, parameters and sandbox results: **`UPGRADE_v2.4.3.md`**.

- **STEP staircase** (new, stocks and ETFs, no band needed): an illiquid "flat, then jump" pattern.
  - Tag: 3 stale sessions in a row, or 2 "stale run → jump of 2% or more" events within 40 sessions.
  - Untag: 2 normal sessions with volume back.
  - While tagged, `TRADE_BLOCKED` carries `STEP_STAIRCASE`: no buy, no sell, no exit.
  - New column `STEP` (CLIMBING / FALLING / FLAT / BUILDING) and the `step_*` columns.
- **Separate ETF rules.** New config sections `circuit_etf`, `staircase_etf` and `chronic_etf` (only the keys that differ). The asset class comes from `product_class` / `asset_class`. New column `ASSET_CLASS`.
- **Separate climbing / falling settings:** `start_confirm_days_*`, `end_confirm_days_*`, `tag_vol_frac_*`, `ladder_break_days_*`, `step_jump_pct_*`.
- **Owner volume rule.**
  - Real volume where it exists.
  - OHLC with a warning when volume is ZERO, MISSING or unreliable (fewer than 50% real-volume sessions in the last 60).
  - New column `staircase_vol_reason`.
- **Ladder break tolerance** (`ladder_break_days`, default 0 = 2.4.2).
- **Corporate-action guard** (`ca_jump_pct` = 35%, column `ca_suspect`).
- **Optional ₹ traded-value floor** for chronic illiquidity (`min_traded_value`, off by default).
- **Fixes:**
  - `load_eod` fills blank symbol cells with the file's own symbol. Before, ETF files split one history into two symbols.
  - The step objects keep the trailing volume baseline on REAL volume only.
- **`run_four_flags.py`** also processes an ETF folder (`paths.etfs_eod_subdir`) and writes STEP episode files.
- **Package import:** the bundle can be imported as a package (`__init__.py`), ready for the qbeast_exec wheel.
- **Exactly 2.4.2:** `flags_config.LEGACY_V242` / `legacy_v242_config()`. Bit-identical on 589 ETF and 23 stock files (batch and tracker).
- **Tests:** 60 unit tests (24 new), each new one mutation-checked. `verify_install.py` has 60 checks.

## 2.4.2 (2026-10-17): real volume in the staircase tag and untag; missing / erroneous volume

Drop-in for 2.4.1: no function, class, parameter or column was renamed or removed. New parameters are keywords with defaults; new columns are added next to the old ones. Overwrite the 2.4.1 files.

- **Volume quality (new `volume_status` column from the circuit step, causal).**
  - REAL: volume > 0.
  - ZERO: zero volume, price unchanged (a true no-trade day).
  - MISSING: blank, negative or infinite volume; zero volume while the price moved; or the `zero_run_missing`-th (20) zero/blank day in a row so far.
  - GAP: a gap-filled row.
  - New `CircuitParams`: `volume_quality` (True), `zero_run_missing` (20).
- **Staircase tag needs low real volume.** At S ladder days, tag only if the average REAL volume of the last `vol_avg_days` (3) days < `tag_vol_frac` (0.5) × baseline. Otherwise the state stays BUILDING (`LADDER_HIGH_VOL`).
- **Staircase untag needs volume back.** A NORMAL day needs the same 3-day average ≥ `normal_vol_frac` × baseline.
- **Missing volume falls back to OHLC** for both tag and untag (`missing_volume_fallback`), with a warning in the new `staircase_vol_warn` / `STAIRCASE_VOL_WARN` columns: `TAGGED_NO_VOL`, `NORMAL_NO_VOL`, `UNTAGGED_NO_VOL`. In 2.4.1 a tagged staircase whose volume went missing could never untag.
- **Chronic:** a MISSING-volume day is no longer a no-trade day (`ChronicParams.missing_volume_as_no_trade = False`).
- **Exactly 2.4.1:** `flags_config.LEGACY_V241` / `legacy_v241_config()`. Bit-identical to 2.4.1 on 1,861 real files (1,272 stocks + 589 ETFs, 4.84 M rows), batch and tracker.
- **Effect with the new defaults (real data, 2002–2026):**
  - stock staircase days 26,196 → 14,155;
  - episodes 1,416 → 673;
  - stock chronic days 141,392 → 139,894;
  - ETF chronic days 93,766 → 87,554;
  - ETFs have no staircase in either version.
  - INDOTHAI Dec-2021 is tagged on 28-Dec instead of 23-Dec (heavy volume on 23-Dec).
- **Outputs:** `run_four_flags.py` EOD files and the summary add `STAIRCASE_VOL_WARN`. `staircase_episodes.csv` adds `vol_warn`. `flags_io.OUTCOLS` is unchanged (5 columns); the new `flags_io.OUTCOLS_ALL` adds the warning.
- **Tests:** 36 unit tests (9 new for 2.4.2: classification, heavy-volume ladder, missing-volume tag and untag, untag needs average volume, chronic, no-repaint and streaming parity with the new columns, legacy preset). `test_thin_volume_days_do_not_untag` now checks the 2.4.1 behaviour under the legacy preset and the 2.4.2 behaviour (untag one day later) under the defaults.
- **`verify_install.py`:** 39 checks (7 new, section 7b).
- **Not updated:** `QBEAST_Circuit_Liquidity_Flags_Guide.pdf` describes 2.4.1. README section 5 and the SPEC cover 2.4.2.

## 2.4.1 (2026-09-28): explicit two-direction staircase block

- **Staircases block both directions.** Confirmed and now tested explicitly: a tagged staircase is barred from buying and selling (and exiting) whether it is CLIMBING or FALLING. The flag logic is unchanged from 2.4.0; this release adds checks and documents the rule.
- **New unit test:** `test_both_staircase_directions_block_buy_and_sell`, for batch and tracker (27 tests).
- **New `verify_install.py` checks** (32 in total, 34 with `--real-data`):
  - every FALLING day is TRADE_BLOCKED;
  - every CLIMBING day is TRADE_BLOCKED;
  - the one-day script reports FALL1 as FALLING and blocked.
- **README** section 10 states the two-direction rule.

## 2.4.0 (2026-09-27): team bundle

- **Config file.** `qbeast_flags_config.json` + `flags_config.py`: paths, workers and every flag parameter in one place.
  - Unknown keys and invalid values are refused with a clear message.
  - Every script accepts `--config`.
- **Shared I/O.** `flags_io.py`: shared loaders and the EOD / intraday pipelines, so every script computes exactly the same thing.
- **Library.** `compute_circuit_hit_flag` accepts `circuit_params=` (a full `CircuitParams` object). Existing calls are unchanged.
- **Runner.** `run_four_flags.py` also writes `staircase_episodes.csv`. It replaces `run_circuit_flags_universe.py`, which was removed.
- **Portability.** `call_four_functions.py` builds paths that work on Windows, macOS and Linux.
- **Verification.** New `verify_install.py`: an end-to-end self-test on synthetic data (29 checks), with an optional real-data check.
- **Tests.** 26 unit tests (2 new, for the config).
- **Compatibility.** Output is identical to 2.3.0 with the default config (47,291 of 47,291 stock-days identical on the real-data sample).
- **Tested on:** Python 3.10, 3.11 and 3.12; pandas 2.0.3, 2.2.3 and 3.0.x; the multiprocessing spawn start method (as on Windows).

## 2.3.0 (2026-09-27)

- New `TRADE_BLOCKED` gate column: `NO`, or `STAIRCASE` / `CHRONIC` / `MWCB_DAY` / `MWCB_HALT`.
- New scripts `daily_backtest_loop.py`, `flags_for_one_day.py`, `call_four_functions.py` and `example_daily_usage.py`.

## 2.2.0 (2026-09-26)

- `four_flag_columns()`: one readable column per flag.
- New script `run_four_flags.py`.

## 2.1.0 (2026-09-26)

- Tolerance for off-grid (back-adjusted) prices capped at 0.5%.
- Intraday uses only the band known from EOD history, plus a session-extreme guard.
- The volume baseline resets on an exchange change only.

## 2.0.0 (2026-09-26)

Causal rewrite of v1, keeping the same function names:

- No back-marking of staircase days.
- End rule: E days reached.
- Grace days stay tagged.
- Direction flip keeps the tag.
- Tick-aware tolerance.
- Causal band inference.
- MWCB on the index's high/low with a day-level aggregate.
- Chronic illiquidity flag.
- Streaming tracker.
