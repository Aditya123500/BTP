# CODE3 — Nifty 100 Monthly 12–1 Momentum

## Purpose and signal

CODE3 implements a long-only monthly momentum strategy based on the 12–1 month formation rule. At each month end, it compares the prior month-end adjusted close with the adjusted close 12 calendar months earlier, ranks the point-in-time Nifty 100 members, and selects the top decile (up to 10 names). Selected names are equal weighted. Missing or insufficient price history reduces the rankable universe.

## Execution, costs, and risk behavior

Entries use the next month's first session open scaled by that day's price adjustment factor. Holdings exit at the following month's first session open. Default costs are 10 bps slippage plus 10 bps transaction cost per traded side. QBEAST blocks buys and exits where required; blocked positions remain open and can extend the final measured position. Benchmark is the Nifty 100 price series, with the open-to-open convention described in the result summary.

## Inputs and outputs

Inputs: Nifty 100 daily OHLC/adjusted-close histories, `NIFTY 100.csv` calendar/index, `Nifty100_membership.csv`, and QBEAST per-symbol flags. Default date window is 2011-01-01 through 2019-09-30. Outputs under `STRATEGY/output_long_only_momentum_nifty100/`: `monthly_selections.csv`, `monthly_portfolio.csv`, `summary.json`, and `equity_curve.png`.

## Run

```powershell
python STRATEGY/CODE_3.py --help
python STRATEGY/CODE_3.py
```

Options: `--start-date`, `--end-date`, `--price-dir`, `--membership`, `--output`, `--qbeast-flags-dir`, `--slippage-bps`, and `--transaction-cost-bps`.
