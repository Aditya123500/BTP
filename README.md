# Equity Strategy Backtests

Four research strategies run on local historical prices and point-in-time membership snapshots. They are transparent backtest implementations, not official NSE index replications. Stock returns use adjusted prices. Portfolio results below are net of modeled costs; benchmark results are gross.

## Run

Run the full submission pipeline from project root (`C:\BTP`). It generates QBEAST v2.4.4 flags first, then runs all four costed strategy backtests with that gate enabled.

```powershell
python -m pip install -r requirements.txt
python run_submission_pipeline.py
```

To reuse existing QBEAST outputs, run `python run_submission_pipeline.py --skip-qbeast`. The four strategy scripts also accept `--qbeast-flags-dir` for an alternate flag-output folder. A missing symbol file stops the backtest; a missing symbol/date flag fails closed and blocks orders for that symbol on that decision date.

All strategies use default cost assumptions of **10 bps slippage + 10 bps transaction cost per traded side**. Buy/sell turnover and initial entry are charged. Final exits are charged when QBEAST permits them; blocked positions remain open and do not incur a fictitious exit charge. The model does not include taxes, exchange fees, market impact beyond flat slippage, or capacity limits.

## QBEAST integration

QBEAST v2.4.4 `TRADE_BLOCKED` states now gate order changes in CODE1–4. Each strategy checks the flag available at its signal close before next-session execution. Blocked buys are skipped; blocked holdings cannot be sold or exited and remain held. Any unused target weight stays in cash. Missing symbol files stop a run; missing dated flags fail closed for that symbol and decision date. The implementation, release rules, and technical details are in [`QBEAST_circuit_flags_v2.4.4`](QBEAST_circuit_flags_v2.4.4/README.md); submission steps and evidence requirements are in [`PIPELINE_READ_ME.md`](PIPELINE_READ_ME.md).

Two CODE3 selected symbol/date pairs had no QBEAST row for the signal date; both were blocked as `FLAG_DATA_MISSING` and were not treated as tradable.

The QBEAST run processes 495 equity files from the no-survivorship NIFTY 500 folder; the `NIFTY500.csv` index file in that folder is explicitly excluded from stock flags. NIFTY 50 supplies market-wide breaker flags. QBEAST uses supplied volume as-is because no separate point-in-time split-adjusted-volume field or corporate-action master is present; volume-based flags around share-count actions are provisional. No ETF history or intraday files were supplied, so those rules have no real-history evaluation. Benchmark returns remain ungated gross references. Strategy summaries record the QBEAST flag folder and blocked-order/holding counts.

## Strategy logic

| Script | Universe and rebalance | Signal and portfolio construction | Execution |
|---|---|---|---|
| [CODE1](STRATEGY/CODE_1.PY) | Point-in-time Nifty 500; semiannual May/November reviews; up to 50 stocks | Combine equally weighted cross-sectional z-scores of 6- and 12-month returns divided by annualized volatility. Exclude bottom liquidity decile using six-month average `close x volume`. Keep eligible incumbents ranked 75 or better, admit up to 25 top new names, then fill by score; equal weights. | Signal at month end; holdings start at next Nifty 500 session close and earn from following session. Costed by [backtester](TESTER/backtester.py). |
| [CODE2](STRATEGY/CODE_2.py) | Point-in-time Nifty 500; semiannual June/December reviews; up to 50 stocks | Available-data proxy with momentum and low-volatility factors. Rank 6- and 12-month returns adjusted by annualized volatility; form pool from top 25 per factor; average factor percentiles, then weight selected names by composite score. Apply bottom-decile traded-value screen. Quality and value fundamentals are not available to this implementation. | Signal at month end; next session close execution; daily adjusted-close returns. |
| [CODE3](STRATEGY/CODE_3.py) | Point-in-time Nifty 100; monthly; top decile (10 stocks) | 12-1 momentum: adjusted close at prior month end versus 12 months earlier, skipping latest month. Equal-weight long-only. | Enter at next month's first adjusted open; exit at following month's first adjusted open. |
| [CODE4](STRATEGY/CODE_4.py) | Point-in-time Nifty 200; monthly; top 30 stocks | Q-Mom-style proxy: 11-month adjusted log momentum, skipping latest month, divided by annualized daily adjusted-close volatility. Equal-weight long-only. | Enter/exit at successive month-first adjusted opens. Formula is an explicit proxy; source paper does not fully disclose Q-Mom construction. |

## Net strategy results

| Strategy | Measured period | Rebalance/holding periods | Total return | CAGR | Max drawdown |
|---|---|---:|---:|---:|---:|
| CODE1: Nifty 500 Momentum 50 proxy | 2009-06-01 to 2026-06-08 | 35 rebalances | 6,126.35% | 27.48% | -36.53% |
| CODE2: Nifty 500 two-factor price proxy | 2009-07-01 to 2026-06-08 | 34 rebalances | 3,103.13% | 22.71% | -29.45% |
| CODE3: Nifty 100 12-1 momentum | 2011-01-03 to 2019-10-01 | 105 monthly periods | 535.07% | 23.55% | -25.76% |
| CODE4: Nifty 200 volatility-adjusted momentum proxy | 2014-01-01 to 2021-07-01 | 90 monthly periods | 490.75% | 26.74% | -28.75% |

All four portfolios used QBEAST v2.4.4. “Blocked decisions” counts blocked symbol decisions at scheduled rebalances; “held through block” counts positions whose requested trade was deferred. CODE4 ended with ATGL and ADANIENSOL still blocked by staircase flags, so no final exit cost was charged for those two open positions.

CODE3 and CODE4 measured periods include the first scheduled exit after their final requested signal month: 2019-10-01 and 2021-07-01 respectively. Their standalone summaries retain their native index comparisons (Nifty 100 for CODE3 and Nifty 200 for CODE4); the common Nifty 500 / Nifty 200 comparisons follow below.

| Strategy | Blocked decisions | Held through block | Open positions at end |
|---|---:|---:|---:|
| CODE1 | 20 | 8 | 0 |
| CODE2 | 13 | 4 | 0 |
| CODE3 | 5 | 5 | 0 |
| CODE4 | 26 | 13 | 2 |

## Benchmark comparison

Returns and drawdowns use each strategy's measured dates. Nifty 500 benchmark is the gross total-return index (TRI). Nifty 200 benchmark is its adjusted price-index series, not a TRI. CODE1/2 use close-based benchmark returns; CODE3/4 use adjusted open-to-open Nifty 200 benchmark returns to match their open execution. TRI is close-based because no TRI open series exists.

| Strategy | Benchmark | Total return | CAGR | Max drawdown |
|---|---|---:|---:|---:|
| CODE1 | Nifty 500 gross TRI | 632.40% | 12.41% | -38.11% |
| CODE1 | Nifty 200 adjusted price index | 468.80% | 10.75% | -38.22% |
| CODE2 | Nifty 500 gross TRI | 657.73% | 12.70% | -38.11% |
| CODE2 | Nifty 200 adjusted price index | 489.69% | 11.05% | -38.22% |
| CODE3 | Nifty 500 gross TRI, sampled at holding dates | 106.12% | 8.63% | -21.64% |
| CODE3 | Nifty 200 adjusted price index, open-to-open holding dates | 87.74% | 7.47% | -22.22% |
| CODE4 | Nifty 500 gross TRI, sampled at holding dates | 198.00% | 15.68% | -31.37% |
| CODE4 | Nifty 200 adjusted price index, open-to-open holding dates | 163.20% | 13.78% | -29.43% |

CODE1/2 benchmark drawdowns use daily strategy sessions. CODE3/4 benchmark drawdowns use the same monthly entry/exit dates as each strategy; they do not capture intra-month benchmark drawdowns. Strategy and benchmark periods differ by strategy, so cross-row strategy rankings are not like-for-like. Benchmarks are buy-and-hold gross returns without trading costs.

## Outputs

- Integrated run entry point/config: [`run_submission_pipeline.py`](run_submission_pipeline.py), [`QBEAST_pipeline_config.json`](QBEAST_pipeline_config.json), and shared gate [`TESTER/qbeast_gate.py`](TESTER/qbeast_gate.py)
- QBEAST per-symbol flags and run report: [`QBEAST_RUN_NIFTY500_v2.4.4/output`](QBEAST_RUN_NIFTY500_v2.4.4/output)
- CODE1 raw signal selections and diagnostic series: [`STRATEGY/output`](STRATEGY/output)
- CODE1 costed comparison: [`TESTER/output/performance_summary.csv`](TESTER/output/performance_summary.csv), [`backtest_daily.csv`](TESTER/output/backtest_daily.csv), [`equity_plot.png`](TESTER/output/equity_plot.png)
- CODE2: [`STRATEGY/output_mqvlv_price_proxy`](STRATEGY/output_mqvlv_price_proxy)
- CODE3: [`STRATEGY/output_long_only_momentum_nifty100`](STRATEGY/output_long_only_momentum_nifty100)
- CODE4: [`STRATEGY/output_momentum_vol_adjusted`](STRATEGY/output_momentum_vol_adjusted)

## Data and limitations

- Main price inputs are under `DATASET/Final_without_survivorship_data`; membership histories are under `DATASET/Survivorship_Bias`. Nifty 500 TRI is `TRI/NIFTY_500_TRI.csv`.
- Price files do not cover every ticker in historical membership snapshots. Missing/insufficient histories reduce rankable universes; CODE1/2 have 495 available stock files.
- CODE1 uses traded value as a liquidity proxy. QBEAST adds causal price-derived circuit/liquidity flags, but official point-in-time price bands, free-float weights, F&O membership, and complete liquidity inputs are unavailable.
- CODE2 is only a momentum/low-volatility price proxy. Quality/value factors and several official eligibility filters are not replicated.
- CODE3 and CODE4 use equal weights and adjusted-open execution proxies. CODE4 does not replicate a fully disclosed Q-Mom formula or official Nifty 200 Momentum 30 weighting.
- Nifty 200 benchmark is a price index; it excludes constituent dividends. Benchmark comparisons involving it are not total-return comparisons.
- Backtests are nominal, not inflation-adjusted. Results depend on the supplied data and execution assumptions; they do not guarantee live performance.

## Project map

Detailed contract, technical and functional specifications, operational manual, command reference, quick commands, version history, and individual strategy guides are in [`Documents/Manuals`](Documents/Manuals/README.md).

This is a map of the maintained project files and generated output folders. Individual `.csv` files inside the market-data folders are symbol or index histories; their names identify the instrument.

### Root files

| File | Purpose |
|---|---|
| `README.md` | Project overview, run instructions, strategy descriptions, recorded results, and this file map. |
| `run_submission_pipeline.py` | Runs QBEAST flag generation, checks flag coverage, then launches the four gated backtests. |
| `QBEAST_pipeline_config.json` | Input folders, MWCB index selection, worker/check settings, and QBEAST rule parameters. |
| `requirements.txt` | Python dependencies for the integrated strategy/backtest project. |
| `PIPELINE_READ_ME.md` | Detailed run, validation, submission, and evidence checklist. |
| `UPGRADE_v2.4.3.md` | Project-level upgrade notes for the previous QBEAST integration. |
| `BASE.pdf` | Reference document supplied with the project. |
| `QBEAST_circuit_flags_v2.4.4.zip` | Packaged copy of the QBEAST v2.4.4 source bundle. |
| `.gitignore` | Files and folders Git should ignore, including Python bytecode caches. |
| `.gitattributes` | Git text and line-ending handling rules. |

### Project folders

| Folder | Purpose and contents |
|---|---|
| `DATASET/` | Historical market data, index membership snapshots, and supplementary research files. |
| `DATASET/Final_without_survivorship_data/` | Price histories used for the primary backtests; `Final_NIFTY500_EoD_Data`, `Final_NIFTY100_EoD_Data`, `Final_NIFTY200_EoD_Data`, and the other `Final_*_EoD_Data` folders group daily OHLCV CSVs by index universe. |
| `DATASET/Final_with_survivorship_data/` | Alternate price histories that retain survivorship bias; for comparison/research, not the primary reported run. |
| `DATASET/Survivorship_Bias/` | Dated constituent membership snapshots used to reconstruct point-in-time index universes. |
| `DATASET/EXTRAS/` | Supplementary spreadsheets and research datasets, including VIX and constituent-history material. |
| `STRATEGY/` | Strategy source scripts and each strategy's generated selections, portfolios, summaries, and plots. |
| `STRATEGY/CODE_1.PY` | Nifty 500 momentum portfolio strategy. |
| `STRATEGY/CODE_2.py` | Nifty 500 momentum and low-volatility price proxy. |
| `STRATEGY/CODE_3.py` | Nifty 100 monthly 12-1 momentum strategy. |
| `STRATEGY/CODE_4.py` | Nifty 200 volatility-adjusted momentum proxy. |
| `STRATEGY/output/` | CODE1 selections and portfolio diagnostics. |
| `STRATEGY/output_mqvlv_price_proxy/` | CODE2 daily portfolio, selections, and summary. |
| `STRATEGY/output_long_only_momentum_nifty100/` | CODE3 monthly portfolio, selections, summary, and equity plot. |
| `STRATEGY/output_momentum_vol_adjusted/` | CODE4 monthly portfolio, selections, summary, and equity plot. |
| `TESTER/` | Shared backtesting engine, QBEAST gate adapter, and integrated backtest results. |
| `TESTER/backtester.py` | Executes the CODE1 costed backtest and creates its daily results, summary, and plot. |
| `TESTER/qbeast_gate.py` | Reads QBEAST flags and applies fail-closed order blocking to strategies. |
| `TESTER/output/` | CODE1 costed results: daily series, performance summary, and equity plot. |
| `TRI/` | Nifty 500 total-return index input and the script that derives or prepares it. |
| `QBEAST_circuit_flags_v2.4.4/` | Versioned QBEAST source bundle, standalone configuration, documentation, tests, and verifier. Its README describes each bundle file. |
| `QBEAST_RUN_NIFTY500_v2.4.4/` | Saved report and generated QBEAST output for the integrated Nifty 500 run. |
| `QBEAST_RUN_NIFTY500_v2.4.4/output/` | Flag summaries/reports, combined flags, per-symbol stock/index flags, and episode files. |
| `__pycache__/` | Python's generated bytecode cache; safe to delete and recreated automatically. |

### Current health

The saved run record reports that all 495 Nifty 500 equity files completed, the QBEAST verifier passed **62/62**, and its unit suite passed **63/63**. The strategy outputs and summaries are present. This indicates the recorded pipeline run completed successfully; no fresh pipeline or test run was performed while writing this README. Two CODE3 decisions were safely blocked because their dated QBEAST rows were missing. Real-data causal checks sampled 50 of 495 equities (`check_every=10`), and no ETF or intraday history was available, so those cases remain unevaluated.
