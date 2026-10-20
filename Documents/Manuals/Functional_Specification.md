# Functional Specification

| Strategy | Rule | Execution and benchmark |
|---|---|---|
| CODE1 | Nifty 500; May/November; rank 6- and 12-month volatility-adjusted momentum; 50 equal-weight names with liquidity and incumbent buffers. | Next Nifty 500 session close; Nifty 500 TRI. |
| CODE2 | Nifty 500; June/December; momentum and low-volatility price proxy; up to 50 names. Quality/value inputs are unavailable. | Next session close; Nifty 500 TRI. |
| CODE3 | Nifty 100; monthly 12–1 momentum; top decile, equal weight. | Month-first adjusted opens; Nifty 100. |
| CODE4 | Nifty 200; monthly 11-month momentum divided by volatility; top 30, equal weight. | Month-first adjusted opens; Nifty 200 price index. Proxy, not official Q-Mom replication. |

## Shared behavior

- QBEAST `TRADE_BLOCKED` suppresses buys and exits; blocked holdings remain open. Missing dated flags block the trade.
- Default costs: 10 bps slippage plus 10 bps transaction cost per traded side. Benchmarks are gross.
- Summaries report returns, CAGR, volatility, drawdown, and gate counts. Portfolio/selection CSVs provide the underlying periods and holdings.
- Taxes, exchange fees, market impact, capacity, and financing are not modeled. Nifty 200 is a price index, not TRI.

See [CODE1–CODE4 guides](Strategies/) for formulas, dates, inputs, outputs, and commands.
