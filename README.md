# Nifty 500 Momentum 50 Backtest

Research backtest built from the local Nifty 500 price and membership data. It is a transparent approximation of the NSE Momentum 50 methodology, not an official index replication.

## Run

From the project root (`C:\BTP`), run the selection step first, then the costed backtest:

```powershell
python STRATEGY/CODE_1.PY
python TESTER/backtester.py
```

The strategy writes selections to `STRATEGY/output`. The backtester reads those selections and writes daily results, a performance summary, and an equity plot to `TESTER/output`.

## Strategy and data

- **Universe:** Nifty 500 constituents from dated snapshots in `DATASET/Survivorship_Bias/Nifty500_membership.csv`. Each rebalance uses the latest snapshot effective on or before its signal date.
- **Prices:** Adjusted-close and volume files in `DATASET/Final_without_survivorship_data/Final_NIFTY500_EoD_Data` (495 CSV files). `NIFTY500.csv` supplies the exchange-session calendar.
- **Signal:** Semi-annual May/November month-end ranking. Score combines equal-weighted z-scores of six- and twelve-month returns divided by annualized volatility. Use six-month average `close * volume` as the liquidity proxy; exclude the bottom liquidity decile.
- **Selection:** 50 equal-weighted stocks. Keep eligible incumbents ranked 75 or better; admit up to 25 highest-ranked new names, then fill by score.
- **Timing:** Signals use data through the signal date. Holdings take effect at the next Nifty 500 session's close and earn returns from the following session.
- **Benchmark:** Gross Nifty 500 TRI from `TRI/NIFTY_500_TRI.csv`, using its `total_return_index` column.

## Latest backtest result

Period: **2009-06-01 to 2026-06-08**. There were **35 rebalances**. Portfolio costs are **10 bps slippage plus 10 bps transaction cost on each buy and sell side**.

| Series | Total return | CAGR | Annualized volatility | Maximum drawdown |
|---|---:|---:|---:|---:|
| Momentum 50 portfolio, net modeled costs | 6,054.04% | 27.39% | 19.08% | -36.53% |
| Nifty 500 gross TRI | 632.40% | 12.41% | 16.53% | -38.11% |

Returns are nominal and **not adjusted for inflation**.

## Constraints

- The no-survivorship price folder has 495 files and does not cover every ticker in the historical membership snapshots. The strategy skips constituents without usable price history; the tested universe is therefore incomplete and results may still have survivorship or coverage bias.
- This is a proxy: official free-float, F&O, circuit, and liquidity screens are unavailable. `close * volume` is only a traded-value proxy.
- Costs model slippage and transaction costs only. Taxes, exchange charges, market impact beyond modeled slippage, and other execution effects are excluded.
- Adjusted-close daily bars and next-session-close execution are assumptions. Results are not a guarantee of live performance.

See [`STRATEGY/CODE_1.PY`](STRATEGY/CODE_1.PY) and [`TESTER/backtester.py`](TESTER/backtester.py) for implementation details. Outputs: [`TESTER/output/performance_summary.csv`](TESTER/output/performance_summary.csv), [`TESTER/output/backtest_daily.csv`](TESTER/output/backtest_daily.csv), and [`TESTER/output/equity_plot.png`](TESTER/output/equity_plot.png).
