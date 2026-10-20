# CODE2 — Nifty 500 Momentum and Low-Volatility Price Proxy

## Purpose and status

CODE2 approximates a multifactor strategy using only price data available in this workspace. Quality and value factors are not calculated, so this is not an MQVLv 50 replication. Official eligibility screens and free-float weighting are not reproduced.

## Universe and signal

- Universe: point-in-time Nifty 500 membership; semiannual June/December reviews; one-year listing history requirement.
- Calculate six- and twelve-month returns adjusted for annualized volatility; combine the two momentum measures.
- Form candidate pool from the top 25 names for each available factor: momentum and low volatility.
- Convert momentum and inverse volatility to cross-sectional percentile scores and average the available scores.
- Apply the bottom-decile traded-value screen and select up to 50 names. Selected weights are proportional to positive composite scores, with equal-weight fallback if their sum is zero.

## Execution, costs, and gate

The signal is generated at month end and implemented at the next session close. Daily adjusted-close returns are costed using 10 bps slippage and 10 bps transaction cost per traded side by default. QBEAST-gated buys are skipped and blocked holdings are retained.

## Inputs and outputs

Inputs: Nifty 500 OHLCV/adjusted-close histories, `NIFTY500.csv` session calendar, `Nifty500_membership.csv`, Nifty 500 TRI benchmark, and QBEAST flags. Outputs under `STRATEGY/output_mqvlv_price_proxy/`: `rebalance_selections.csv`, `daily_portfolio.csv`, and `summary.json`.

## Run

```powershell
python STRATEGY/CODE_2.py --help
python STRATEGY/CODE_2.py
```

Options include `--prices`, `--membership`, `--output`, `--benchmark`, `--qbeast-flags-dir`, `--slippage-bps`, and `--transaction-cost-bps`.
