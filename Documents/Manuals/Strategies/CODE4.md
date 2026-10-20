# CODE4 — Nifty 200 Volatility-Adjusted Momentum Proxy

## Purpose and status

CODE4 is an explicit monthly volatility-adjusted momentum proxy for a point-in-time Nifty 200 universe. The cited Q-Mom description does not disclose a complete formula, and this implementation does not reproduce official Nifty 200 Momentum 30 weighting.

## Signal and portfolio

- At month end, compute 11-month adjusted log momentum from month t-12 to t-1, skipping the latest month.
- Divide momentum by annualized daily adjusted-close volatility over the formation window.
- Rank eligible constituents and select the top 30 by default, equal weighted and long only.
- A minimum 120 daily return observations is required by default for volatility eligibility.

## Execution, costs, and gate

Enter and exit at successive month-first adjusted opens. Default costs are 10 bps slippage plus 10 bps transaction cost per traded side. QBEAST blocks target changes; blocked positions may remain open at the final date. The benchmark is the Nifty 200 adjusted price-index series, so dividends are excluded.

## Inputs and outputs

Inputs: Nifty 200 daily OHLC/adjusted-close histories, `NIFTY 200.csv` benchmark/calendar, `Nifty200_membership.csv`, and QBEAST flags. Default window is 2014-01-01 through 2021-06-30. Outputs under `STRATEGY/output_momentum_vol_adjusted/`: `monthly_selections.csv`, `monthly_portfolio.csv`, `summary.json`, and `equity_curve.png`.

## Run

```powershell
python STRATEGY/CODE_4.py --help
python STRATEGY/CODE_4.py
```

Options include `--start-date`, `--end-date`, `--price-dir`, `--benchmark-file`, `--membership`, `--output`, `--qbeast-flags-dir`, `--slippage-bps`, `--transaction-cost-bps`, `--portfolio-size`, and `--min-vol-observations`.
