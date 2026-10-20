# CODE1 — Nifty 500 Momentum 50

## Purpose and status

CODE1 is a transparent Nifty 500 momentum strategy proxy. It is not an official NSE index replication because historical free-float weights, promoter pledges, F&O status, official circuit bands, and full liquidity inputs are not available.

## Universe and signal

- Universe: latest Nifty 500 membership snapshot effective on or before the signal date.
- Review: May and November month ends, using the Nifty 500 session calendar.
- Price series: adjusted close; liquidity proxy is six-month average unadjusted `close * volume`.
- Score: calculate six- and twelve-month return divided by annualized volatility; z-score each cross-section; average the two z-scores equally; transform the score monotonically for ranking.
- Liquidity: exclude bottom decile by traded-value proxy.
- Selection: target 50 equal-weight names. Eligible incumbents can remain through rank 75; admit up to 25 highest-ranked new names, then fill by score.

## Execution, costs, and gate

Signals use data through the month-end signal date. Target weights activate at the next Nifty 500 session close and earn returns starting the following session. `TESTER/backtester.py` applies default 10 bps slippage plus 10 bps transaction cost per traded side. QBEAST blocks target changes on blocked decisions; existing positions can remain held.

## Inputs and outputs

Inputs: Nifty 500 daily price CSVs with `date`, `adj_close`, `close`, `volume`; the `NIFTY500.csv` calendar; `Nifty500_membership.csv`; QBEAST per-symbol flags. Output from the signal script is `STRATEGY/output/rebalance_selections.csv` and `daily_portfolio.csv`. The costed result is under `TESTER/output/`: `backtest_daily.csv`, `performance_summary.csv`, and `equity_plot.png`.

## Run

```powershell
python STRATEGY/CODE_1.PY --help
python STRATEGY/CODE_1.PY
python TESTER/backtester.py
```

CODE1 accepts `--prices`, `--membership`, and `--output`. The backtester accepts selection, price, benchmark, output, QBEAST flags, and cost options; see [Command Reference](../Command_Reference.md).
