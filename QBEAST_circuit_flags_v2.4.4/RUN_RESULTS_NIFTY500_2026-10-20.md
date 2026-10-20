# QBEAST v2.4.4 - Real-data run results

Run date: 2026-10-20

## Scope

- Stock input folder: `DATASET/Final_without_survivorship_data/Final_NIFTY500_EoD_Data`
- Equity CSVs processed: 495. The `NIFTY500.csv` index file in that folder was excluded from stock processing.
- Market-wide circuit-breaker input: `Final_NIFTY50_EoD_Data/Nifty 50.csv` (NIFTY 50 only)
- Environment: Python 3.14.5, pandas 3.0.3, NumPy 2.4.5
- Equity symbol-days: 1,857,499
- Equity data coverage: 2000-01-03 through 2026-08-06
- ETFs: not run; no ETF EOD folder was supplied
- Intraday: not run; matching intraday input was not supplied

## Run outcome

- All 495 equity files completed; 0 file errors.
- QBEAST stock flags: 495 files. Fifty strategy symbol files overlap NIFTY 50 membership; all 495 strategy symbols are covered.
- `TRADE_BLOCKED`: 24,809 equity-days (1.34% of equity symbol-days).
- Circuit staircase: 83 episodes across 45 equities.
- STEP staircase: 203 episodes across 61 equities.
- NIFTY 50 produced 10 market-wide circuit-breaker trigger dates.
- Real-data causality/parity check: 50 sampled files passed; 445 files were not sampled (`check_every=10`).
- QBEAST processing time: 592 seconds for stocks; 654 seconds total including the configured NIFTY 50 index and report writing (2 workers, reduced-memory file aggregation).
- Bundle verification: `verify_install.py` passed 62/62 checks; `test_circuit_liquidity_flags.py` passed 63/63 checks.

Block-reason counts may overlap because one symbol-day can carry multiple reasons. Machine-readable summaries and flags are under `QBEAST_RUN_NIFTY500_v2.4.4/output`.

## Limits

Input assumption: circuit checks use supplied OHLC; volume thresholds use supplied volume as-is because no point-in-time split-adjusted-volume field or corporate-action master is present. Volume-based staircase and chronic thresholds may be distorted around splits, bonuses, or consolidations, so affected flag dates are provisional.

This is a flag-pipeline run, not strategy P&L. ETF-specific thresholds were covered by synthetic checks only; no ETF history was run. No matching intraday data was supplied. No SENSEX file was available, so MWCB used NIFTY 50 only. Equity input files end on 2026-08-06. The flag outputs are consumed by the separately reported, costed CODE1–4 strategy backtests.
