# QBEAST circuit & liquidity flags: v2.4.3 → v2.4.4

## Release purpose

This release calibrates the existing causal pipeline to the final stock and ETF blocking rules. Data ingestion, flag columns, gate semantics, and pipeline entry points remain compatible. Versioned folder name should be `QBEAST_circuit_flags_v2.4.4` when packaged.

## Final effective defaults

| Rule | Stocks | ETFs |
|---|---|---|
| Circuit staircase | 5 consecutive same-direction locked sessions; thin-volume qualification; release after 3 normal sessions | Same |
| STEP staircase | 3 unchanged/no-real-trade sessions, or 2 flat-then-≥2% jump events in 40 sessions; stale volume <20% baseline; release after 2 normal sessions | Same, stale volume <10% baseline |
| Chronic illiquidity | 60-session window; tag at ≥20% single-price, ≥20% no-trade, or ≥30% circuit days; release when all are <10%, <10%, <15% | Same |
| Minimum traded value | Off | From 2020-01-01: median of trailing 20 real-volume `close × volume` observations below ₹250,000 tags; clear at ₹375,000 |
| Market-wide circuit breaker | Block on breaker day | Same |

While any reason is active, `TRADE_BLOCKED` prevents buying, selling, and exiting. Multiple reasons can coexist. No stock minimum traded-value rule is applied.

### Explicit operational interpretation

The rule sheet says “typical daily traded value”; this code uses the median of a complete trailing 20 real-volume observations. Valid pre-2020 observations warm the median, but the ETF floor cannot activate before 2020-01-01. Windows are trading sessions. Chronic percentages activate only after a complete 60-session window. STEP treats zero volume as no real trading; missing volume alone does not qualify unless OHLC shows one price for the day. A circuit staircase's thin-volume qualification retains the calibrated definition: trailing 3-session real-volume average below 50% of the 20-session median baseline. If volume is missing or unreliable, the existing OHLC fallback applies and records a warning.

## Implementation changes

- Added `ChronicParams.min_traded_value_start_date` and applied it in both batch and streaming chronic-state paths.
- Set circuit staircase release confirmation to 3 normal sessions.
- Set the shipped ETF STEP stale-volume override to 10%; stock remains 20%.
- Set the shipped ETF value floor to ₹250,000 from 2020-01-01 with 1.5× release hysteresis.
- Updated config summary, verifier checks, unit checks, README, SPEC, and changelog.

## Validation and limits

- Added synthetic checks for asset-class STEP cutoffs, effective-date behavior, release hysteresis, and shipped configuration values.
- `pytest` is not installed in the available Python environment. The bundle's direct test runner passed 63/63 checks.
- The built-in end-to-end `verify_install.py --workers 1` passed 62/62 checks.
- Integrated real-data run on 495 no-survivorship NIFTY 500 equity files (the `NIFTY500.csv` index file in the stock folder is excluded): 1,857,499 symbol-days, 495/495 files successful, 25,890 blocked stock-days (1.39%), 83 circuit-staircase episodes, and 204 STEP episodes. Fifty sampled real-data causal/parity checks passed; 445 were skipped by the configured 1-in-10 sampling. Full metrics: `RUN_RESULTS_NIFTY500_2026-10-20.md`.
- The workspace contains no ETF EOD history, so no full historical ETF result or impact estimate is claimed. No SENSEX file was supplied; MWCB ran against NIFTY 50 only. The stock data ends on 2026-08-06.
- The measured results describe flag events only; they are not a strategy return/P&L backtest.
