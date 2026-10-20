"""Cost-aware backtest for STRATEGY/CODE_1.PY selections.

Trade weights become active at each recorded execution-date close. Thus daily
close-to-close returns on that date belong to prior holdings; new holdings earn
returns starting next session. Slippage and transaction costs apply on buys and
sells, including initial entry. Benchmark is the supplied Nifty 500 gross TRI.

Run: python TESTER/backtester.py
Rates default to 10 bps slippage + 10 bps transaction cost, per side. Override
with --slippage-bps and --transaction-cost-bps.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from qbeast_gate import DEFAULT_FLAGS_DIR, QbeastFlagStore, gated_targets

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICE_DIR = ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY500_EoD_Data"
DEFAULT_SELECTIONS = ROOT / "STRATEGY" / "output" / "rebalance_selections.csv"
DEFAULT_BENCHMARK = ROOT / "TRI" / "NIFTY_500_TRI.csv"
DEFAULT_OUTPUT = ROOT / "TESTER" / "output"


def load_prices(price_dir: Path, symbols: set[str]) -> pd.DataFrame:
    """Load selected ticker adjusted closes."""
    prices: dict[str, pd.Series] = {}
    for symbol in sorted(symbols):
        path = price_dir / f"{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Selected ticker price file missing: {path}")
        frame = pd.read_csv(path, usecols=["date", "adj_close"])
        frame["date"] = pd.to_datetime(frame["date"], dayfirst=True, errors="coerce")
        frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
        series = frame.set_index("date")["adj_close"]
        prices[symbol] = series.where(series > 0)
    return pd.concat(prices, axis=1, sort=True).sort_index()


def load_benchmark(path: Path) -> pd.Series:
    """Load NSE Nifty 500 gross Total Return Index (TRI) series."""
    if not path.exists():
        raise FileNotFoundError(f"Nifty 500 TRI CSV not found: {path}")
    benchmark_file = pd.read_csv(path, usecols=["date", "total_return_index"])
    benchmark_file["date"] = pd.to_datetime(benchmark_file["date"], errors="coerce")
    benchmark_file["total_return_index"] = pd.to_numeric(
        benchmark_file["total_return_index"], errors="coerce"
    )
    benchmark = (benchmark_file.dropna(subset=["date"]).sort_values("date")
                 .drop_duplicates("date", keep="last").set_index("date")["total_return_index"])
    return benchmark.where(benchmark > 0)


def load_rebalances(path: Path) -> dict[pd.Timestamp, dict[str, float]]:
    """Read target holdings and validate dates/weights before simulation."""
    if not path.exists():
        raise FileNotFoundError(f"Missing selections: {path}. Run STRATEGY/CODE_1.PY first.")
    frame = pd.read_csv(path)
    required = {"execution_date", "symbol"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Selection CSV must contain {sorted(required)}")
    frame = frame.dropna(subset=["execution_date", "symbol"])
    if frame.empty:
        raise ValueError("Selection CSV contains no executable holdings.")
    frame["execution_date"] = pd.to_datetime(frame["execution_date"], errors="coerce")
    frame = frame.dropna(subset=["execution_date"])
    rebalances = {}
    for date, rows in frame.groupby("execution_date", sort=True):
        symbols = rows["symbol"].astype(str).str.strip().str.upper()
        if symbols.duplicated().any():
            raise ValueError(f"Duplicate ticker in rebalance {date.date()}")
        if "proxy_weight" in rows and rows["proxy_weight"].notna().all():
            weights = pd.to_numeric(rows["proxy_weight"], errors="raise").to_numpy(dtype=float).copy()
            if (weights < 0).any() or not np.isfinite(weights).all() or weights.sum() <= 0:
                raise ValueError(f"Invalid target weights on {date.date()}")
            weights /= weights.sum()
        else:
            weights = np.full(len(rows), 1 / len(rows))
        rebalances[date.normalize()] = dict(zip(symbols, weights))
    return rebalances


def load_signal_dates(path: Path) -> dict[pd.Timestamp, pd.Timestamp]:
    frame = pd.read_csv(path, usecols=["signal_date", "execution_date"])
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce").dt.normalize()
    frame["execution_date"] = pd.to_datetime(frame["execution_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["signal_date", "execution_date"])
    pairs = frame[["execution_date", "signal_date"]].drop_duplicates()
    if pairs.execution_date.duplicated().any():
        raise ValueError("An execution date maps to multiple signal dates")
    return dict(zip(pairs.execution_date, pairs.signal_date))


def simulate(prices: pd.DataFrame, benchmark: pd.Series,
             rebalances: dict[pd.Timestamp, dict[str, float]],
             signal_dates: dict[pd.Timestamp, pd.Timestamp], qbeast: QbeastFlagStore,
             slippage_bps: float, transaction_cost_bps: float) -> pd.DataFrame:
    """Close-to-close portfolio simulation with two-sided turnover costs."""
    if slippage_bps < 0 or transaction_cost_bps < 0:
        raise ValueError("Cost rates must be nonnegative.")
    cost_rate = (slippage_bps + transaction_cost_bps) / 10_000
    # Use TRI dates as the exchange-session calendar. Stock files can contain
    # extra dates absent from NSE's index series; those are not valid sessions.
    # Never synthesize missing quotes. Returns span observed exchange sessions;
    # an unquoted session contributes zero, with no stale-price flat return.
    benchmark = benchmark.sort_index()
    session_start = max(prices.index.min(), benchmark.index.min())
    session_end = min(prices.index.max(), benchmark.index.max())
    sessions = benchmark.index[(benchmark.index >= session_start) & (benchmark.index <= session_end)]
    session_prices = prices.sort_index().reindex(sessions)
    returns = session_prices.apply(
        lambda series: series.dropna().pct_change(fill_method=None).reindex(sessions)
    )
    benchmark_returns = benchmark.pct_change(fill_method=None).reindex(sessions)
    holdings: dict[str, float] = {}
    equity = 1.0
    rows = []
    blocked_order_count = 0
    blocked_holding_days = 0
    for session_i, date in enumerate(sessions):
        prior_equity = equity
        r = returns.loc[date]
        gross_return = sum(weight * (float(r[symbol]) if symbol in r and pd.notna(r[symbol]) else 0.0)
                           for symbol, weight in holdings.items())
        gross_factor = max(0.0, 1.0 + gross_return)
        equity *= gross_factor

        # Drift existing weights through today's close-to-close move.
        if holdings and gross_factor > 0:
            holdings = {
                symbol: weight * (1.0 + (float(r[symbol]) if symbol in r and pd.notna(r[symbol]) else 0.0)) / gross_factor
                for symbol, weight in holdings.items()
            }
        elif gross_factor <= 0:
            holdings = {}

        buy_turnover = sell_turnover = cost = 0.0
        # Rebalance after today's close: today's return used old holdings.
        targets = rebalances.get(date.normalize())
        if targets is not None:
            signal_date = signal_dates.get(date.normalize())
            if signal_date is None:
                raise ValueError(f"Missing signal date for execution {date.date()}")
            blocked = qbeast.blocked_symbols(set(holdings) | set(targets), signal_date)
            blocked_order_count += len(blocked)
            blocked_holding_days += sum(s in holdings for s in blocked)
            targets = gated_targets(holdings, targets, blocked)
            symbols = set(holdings) | set(targets)
            deltas = {s: targets.get(s, 0.0) - holdings.get(s, 0.0) for s in symbols}
            buy_turnover = sum(max(delta, 0.0) for delta in deltas.values())
            sell_turnover = sum(max(-delta, 0.0) for delta in deltas.values())
            cost = (buy_turnover + sell_turnover) * cost_rate
            equity *= max(0.0, 1.0 - cost)
            holdings = dict(targets)
        # Mark the portfolio as closed at the end of the measured period.
        if date == sessions[-1] and holdings:
            known_flag_date = sessions[session_i - 1] if session_i > 0 else date
            final_blocked = qbeast.blocked_symbols(holdings, known_flag_date)
            liquidation_turnover = sum(weight for symbol, weight in holdings.items()
                                       if symbol not in final_blocked)
            liquidation_cost = liquidation_turnover * cost_rate
            sell_turnover += liquidation_turnover
            cost += liquidation_cost
            equity *= max(0.0, 1.0 - liquidation_cost)
            holdings = {symbol: weight for symbol, weight in holdings.items()
                        if symbol in final_blocked}
        net_return = equity / prior_equity - 1.0 if prior_equity > 0 else np.nan
        rows.append({
            "date": date,
            "portfolio_gross_return": gross_return,
            "buy_turnover": buy_turnover,
            "sell_turnover": sell_turnover,
            "slippage_bps_per_side": slippage_bps,
            "transaction_cost_bps_per_side": transaction_cost_bps,
            "cost_fraction": cost,
            "portfolio_net_return": net_return,
            "benchmark_return": benchmark_returns.loc[date],
            "holdings_count": len(holdings),
            "qbeast_blocked_orders_cumulative": blocked_order_count,
            "qbeast_blocked_holding_events_cumulative": blocked_holding_days,
        })
    result = pd.DataFrame(rows).set_index("date")
    first_trade = min(rebalances)
    result = result.loc[first_trade:].copy()
    result["benchmark_return"] = result["benchmark_return"].fillna(0.0)
    result.loc[result.index[0], "benchmark_return"] = 0.0
    result["portfolio_equity"] = 100.0 * (1.0 + result["portfolio_net_return"].fillna(0.0)).cumprod()
    result["benchmark_equity"] = 100.0 * (1.0 + result["benchmark_return"]).cumprod()
    result["portfolio_cumulative_return"] = result["portfolio_equity"] / 100.0 - 1.0
    result["benchmark_cumulative_return"] = result["benchmark_equity"] / 100.0 - 1.0
    result["portfolio_drawdown"] = result["portfolio_equity"] / result["portfolio_equity"].cummax() - 1.0
    result["benchmark_drawdown"] = result["benchmark_equity"] / result["benchmark_equity"].cummax() - 1.0
    return result


def performance_summary(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    years = ((results.index[-1] - results.index[0]).days / 365.25
             if len(results) > 1 else 0.0)
    for label, returns, equity, drawdown in (
        ("portfolio_net", results["portfolio_net_return"], results["portfolio_equity"], results["portfolio_drawdown"]),
        ("nifty500_gross_tri", results["benchmark_return"], results["benchmark_equity"], results["benchmark_drawdown"]),
    ):
        clean = returns.dropna()
        cagr = (equity.iloc[-1] / 100.0) ** (1 / years) - 1 if years > 0 else np.nan
        annual_vol = clean.std(ddof=1) * np.sqrt(252) if len(clean) > 1 else np.nan
        rows.append({
            "series": label,
            "start_date": results.index.min().date().isoformat(),
            "end_date": results.index.max().date().isoformat(),
            "total_return": equity.iloc[-1] / 100.0 - 1,
            "cagr": cagr,
            "annualized_volatility": annual_vol,
            "max_drawdown": drawdown.min(),
        })
    return pd.DataFrame(rows)


def save_plot(results: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.plot(results.index, results["portfolio_equity"], label="Strategy portfolio (net costs)", linewidth=1.7)
    ax.plot(results.index, results["benchmark_equity"], label="Nifty 500 gross TRI", linewidth=1.5)
    ax.set_title("Strategy portfolio vs Nifty 500 TRI")
    ax.set_ylabel("Growth of 100")
    ax.set_xlabel("Date")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selections", type=Path, default=DEFAULT_SELECTIONS)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_DIR)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--qbeast-flags-dir", type=Path, default=DEFAULT_FLAGS_DIR,
                        help="QBEAST v2.4.4 per-stock EOD outputs (strict coverage required).")
    parser.add_argument("--slippage-bps", type=float, default=10.0, help="Slippage per buy or sell side, in basis points.")
    parser.add_argument("--transaction-cost-bps", type=float, default=10.0, help="Transaction cost per buy or sell side, in basis points.")
    args = parser.parse_args()
    if args.slippage_bps < 0 or args.transaction_cost_bps < 0:
        parser.error("cost rates must be nonnegative")
    rebalances = load_rebalances(args.selections)
    signal_dates = load_signal_dates(args.selections)
    qbeast = QbeastFlagStore(args.qbeast_flags_dir)
    symbols = {symbol for weights in rebalances.values() for symbol in weights}
    prices = load_prices(args.prices, symbols)
    benchmark = load_benchmark(args.benchmark)
    results = simulate(prices, benchmark, rebalances, signal_dates, qbeast,
                       args.slippage_bps, args.transaction_cost_bps)
    summary = performance_summary(results)
    summary["qbeast_version"] = "2.4.4"
    summary["qbeast_flags_dir"] = str(qbeast.flags_dir)
    summary["qbeast_blocked_order_events"] = int(results.qbeast_blocked_orders_cumulative.iloc[-1])
    summary["qbeast_blocked_holding_events"] = int(results.qbeast_blocked_holding_events_cumulative.iloc[-1])
    summary["qbeast_unliquidated_final_holdings"] = int(results.holdings_count.iloc[-1])
    args.output.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output / "backtest_daily.csv", index_label="date")
    summary.to_csv(args.output / "performance_summary.csv", index=False)
    save_plot(results, args.output / "equity_plot.png")
    print(f"Rebalances: {len(rebalances)}; holdings universe: {len(symbols)}")
    print(f"Cost each side: slippage {args.slippage_bps:g} bps + transaction {args.transaction_cost_bps:g} bps")
    print(f"QBEAST v2.4.4 gate: {qbeast.flags_dir}; blocked order/holding events: "
          f"{int(results.qbeast_blocked_orders_cumulative.iloc[-1])}/"
          f"{int(results.qbeast_blocked_holding_events_cumulative.iloc[-1])}")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.2%}"))
    print(f"Saved daily returns, summary, and equity plot under {args.output}")


if __name__ == "__main__":
    main()
