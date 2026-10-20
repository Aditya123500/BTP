"""Price-only Nifty 500 multifactor proxy using the data currently available.

Only momentum and low volatility can be calculated from this workspace's
historical prices. Quality and value require historical fundamentals and are
not fabricated. Thus results are NOT the Nifty500 Multifactor MQVLv 50 index.
Uses dated Nifty 500 constituents, semiannual June/December review, one-year
listing history, a traded-value liquidity proxy, next-session execution, and
score weights. NSE eligibility filters and free-float-cap weighting are absent.
The costed simulation applies the separate QBEAST v2.4.4 order gate.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from TESTER.qbeast_gate import DEFAULT_FLAGS_DIR, QbeastFlagStore, gated_targets
DEFAULT_PRICE_DIR = ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY500_EoD_Data"
DEFAULT_MEMBERSHIP = ROOT / "DATASET" / "Survivorship_Bias" / "Nifty500_membership.csv"
DEFAULT_OUTPUT = ROOT / "STRATEGY" / "output_mqvlv_price_proxy"
DEFAULT_BENCHMARK = ROOT / "TRI" / "NIFTY_500_TRI.csv"
N_TRADING_DAYS = 252
PORTFOLIO_SIZE = 50
FACTORS = ("momentum", "low_volatility")


def load_prices(price_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """Load adjusted closes and daily traded value; keep missing quotes missing."""
    closes: dict[str, pd.Series] = {}
    traded_values: dict[str, pd.Series] = {}
    calendar_file = price_dir / "NIFTY500.csv"
    if not calendar_file.exists():
        raise FileNotFoundError(f"Nifty 500 session calendar missing: {calendar_file}")
    cal = pd.read_csv(calendar_file, usecols=["date"])
    cal["date"] = pd.to_datetime(cal["date"], dayfirst=True, errors="coerce")
    calendar = pd.DatetimeIndex(cal.date.dropna().drop_duplicates().sort_values())
    if calendar.empty:
        raise ValueError(f"No valid sessions in {calendar_file}")

    for path in sorted(price_dir.glob("*.csv")):
        symbol = path.stem.strip().upper()
        if symbol == "NIFTY500":
            continue
        try:
            frame = pd.read_csv(path, usecols=["date", "adj_close", "close", "volume"])
        except (ValueError, KeyError):
            continue
        frame["date"] = pd.to_datetime(frame.date, dayfirst=True, errors="coerce")
        for col in ("adj_close", "close", "volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
        frame = frame.set_index("date").reindex(calendar)
        close = frame.adj_close.where(frame.adj_close > 0)
        traded = frame.close.where(frame.close > 0) * frame.volume.where(frame.volume >= 0)
        if close.notna().any():
            closes[symbol] = close
            traded_values[symbol] = traded
    if not closes:
        raise ValueError(f"No valid adjusted-close files in {price_dir}")
    return pd.DataFrame(closes, index=calendar).sort_index(), pd.DataFrame(traded_values, index=calendar).sort_index(), calendar


def load_membership(path: Path) -> list[tuple[pd.Timestamp, set[str]]]:
    raw = pd.read_csv(path, dtype={"symbols": str})
    if not {"effective_date", "symbols"}.issubset(raw.columns):
        raise ValueError("Membership CSV needs effective_date and symbols columns")
    raw["effective_date"] = pd.to_datetime(raw.effective_date, errors="coerce")
    snapshots = []
    for row in raw.dropna(subset=["effective_date"]).sort_values("effective_date").itertuples():
        symbols = {x.strip().upper() for x in str(row.symbols).split(",") if x.strip()}
        snapshots.append((row.effective_date.normalize(), symbols))
    if not snapshots:
        raise ValueError(f"No dated snapshots in {path}")
    return snapshots


def last_value(series: pd.Series, date: pd.Timestamp) -> float:
    available = series.loc[:date].dropna()
    return float(available.iloc[-1]) if not available.empty else math.nan


def returns_from_observed_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute quote-to-quote returns; missing dates stay unpriced, not flat."""
    return prices.apply(lambda s: s.dropna().pct_change(fill_method=None).reindex(s.index))


def percentile(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
    # Percentile scores in [0, 1], deterministic average handling for ties.
    return values.rank(pct=True, ascending=higher_is_better, method="average")


def rebalances(calendar: pd.DatetimeIndex) -> list[pd.Timestamp]:
    result = []
    for year in sorted(set(calendar.year)):
        for month in (6, 12):
            sessions = calendar[(calendar.year == year) & (calendar.month == month)]
            if len(sessions):
                result.append(sessions[-1])
    return result


def score_at(date: pd.Timestamp, universe: set[str], prices: pd.DataFrame,
             traded: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol in sorted(universe):
        if symbol not in prices:
            continue
        p = prices[symbol].loc[:date]
        observed = p.dropna()
        # 1 year listing history; require sufficiently complete price windows.
        if observed.empty or observed.index[0] > date - pd.Timedelta(days=365):
            continue
        if date not in prices.index or pd.isna(prices.at[date, symbol]):
            continue
        p_end = last_value(prices[symbol], date)
        p6 = last_value(prices[symbol], date - pd.DateOffset(months=6))
        p12 = last_value(prices[symbol], date - pd.DateOffset(months=12))
        # Keep calendar alignment so gaps are excluded from daily volatility.
        vol_daily = np.log(p / p.shift(1)).loc[date - pd.Timedelta(days=370):date].dropna()
        if len(vol_daily) < 220 or not all(np.isfinite(v) and v > 0 for v in (p_end, p6, p12)):
            continue
        vol = float(vol_daily.std(ddof=1) * np.sqrt(N_TRADING_DAYS))
        if not np.isfinite(vol) or vol <= 0:
            continue
        liquidity = traded[symbol].loc[date - pd.DateOffset(months=6):date].dropna() if symbol in traded else pd.Series(dtype=float)
        if liquidity.empty:
            continue
        r6, r12 = p_end / p6 - 1, p_end / p12 - 1
        # NSE-style volatility-adjusted momentum proxy; official standardization
        # cannot be confirmed from local inputs, so cross-sectional ranks follow.
        mom6, mom12 = r6 / vol, r12 / vol
        rows.append({
            "symbol": symbol,
            "return_6m": r6,
            "return_12m": r12,
            "momentum_6m_vol_adjusted": mom6,
            "momentum_12m_vol_adjusted": mom12,
            "momentum_raw": 0.5 * (mom6 + mom12),
            "annualized_volatility": vol,
            "avg_daily_traded_value_6m": float(liquidity.mean()),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    # Local proxy for NSE's liquidity screen: bottom decile by six-month
    # average daily traded value. Official turnover-ratio screen unavailable.
    result = result[result.avg_daily_traded_value_6m >= result.avg_daily_traded_value_6m.quantile(0.10)].copy()
    if result.empty:
        return result
    eligible_universe_size = len(result)

    result["m_score"] = percentile(result.momentum_raw)
    result["lv_score"] = percentile(result.annualized_volatility, higher_is_better=False)
    factor_score_columns = {"momentum": "m_score", "low_volatility": "lv_score"}
    # Candidate pool mirrors top-25-per-factor rule for the two available
    # factors. Pool can be smaller than 50 because two factors are unavailable.
    candidate_idx: set[int] = set()
    for col in factor_score_columns.values():
        ordered = result.sort_values([col, "symbol"], ascending=[False, True])
        candidate_idx.update(ordered.head(25).index.tolist())
    result = result.loc[sorted(candidate_idx)].copy()
    result["composite_score"] = result[list(factor_score_columns.values())].mean(axis=1)
    result["eligible_universe_size"] = eligible_universe_size
    result["factor_candidate_pool_size"] = len(result)
    result = result.sort_values(["composite_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    result["rank"] = np.arange(1, len(result) + 1)
    result["selected"] = result.index < PORTFOLIO_SIZE
    selected_scores = result.loc[result.selected, "composite_score"].clip(lower=0)
    if len(selected_scores) and selected_scores.sum() > 0:
        result["proxy_weight"] = 0.0
        result.loc[result.selected, "proxy_weight"] = selected_scores / selected_scores.sum()
    else:
        result["proxy_weight"] = np.where(result.selected, 1 / max(int(result.selected.sum()), 1), 0)
    return result


def run(prices: pd.DataFrame, traded: pd.DataFrame, calendar: pd.DatetimeIndex,
        snapshots: list[tuple[pd.Timestamp, set[str]]], benchmark: pd.Series,
        slippage_bps: float = 10.0, transaction_cost_bps: float = 10.0,
        qbeast: QbeastFlagStore | None = None
        ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if min(slippage_bps, transaction_cost_bps) < 0:
        raise ValueError("Cost rates must be nonnegative")
    cost_rate = (slippage_bps + transaction_cost_bps) / 10_000.0
    events: dict[pd.Timestamp, dict[str, float]] = {}
    signal_dates: dict[pd.Timestamp, pd.Timestamp] = {}
    selection_rows = []
    for signal_date in rebalances(calendar):
        eligible_snapshots = [members for effective, members in snapshots if effective <= signal_date]
        if not eligible_snapshots:
            continue
        scored = score_at(signal_date, eligible_snapshots[-1], prices, traded)
        if scored.empty:
            continue
        chosen = scored[scored.selected].copy()
        future_sessions = calendar[calendar > signal_date]
        if chosen.empty or not len(future_sessions):
            continue
        execution_date = future_sessions[0]
        events[execution_date] = dict(zip(chosen.symbol, chosen.proxy_weight.astype(float)))
        signal_dates[execution_date] = signal_date
        if qbeast is not None:
            chosen["qbeast_signal_block"] = [qbeast.reason(s, signal_date) for s in chosen.symbol]
        chosen.insert(0, "signal_date", signal_date.date().isoformat())
        chosen["execution_date"] = execution_date.date().isoformat()
        # `eligible_universe_size` is number passing local price/liquidity checks.
        chosen["portfolio_size"] = len(chosen)
        selection_rows.extend(chosen.to_dict("records"))

    # Compare and simulate only dates with observed Nifty 500 TRI values.
    benchmark = benchmark.sort_index().dropna()
    calendar = calendar.intersection(benchmark.index)
    if calendar.empty:
        raise ValueError("No overlapping stock and Nifty 500 TRI sessions")
    events = {d: w for d, w in events.items() if d in calendar}
    daily_returns = returns_from_observed_prices(prices).reindex(calendar)
    benchmark_returns = benchmark.pct_change(fill_method=None).reindex(calendar)
    holdings: dict[str, float] = {}
    daily_rows = []
    blocked_order_count = 0
    blocked_holding_events = 0
    for session_i, date in enumerate(calendar):
        returns = daily_returns.loc[date]
        usable = {s: float(returns[s]) if s in returns.index and pd.notna(returns[s]) else 0.0
                  for s in holdings}
        gross_ret = sum(w * usable[s] for s, w in holdings.items()) if holdings else 0.0
        gross_factor = max(0.0, 1.0 + gross_ret)
        if holdings and gross_factor > 0:
            holdings = {s: w * (1.0 + usable[s]) / gross_factor for s, w in holdings.items()}
        elif gross_factor <= 0:
            holdings = {}
        cost = turnover = 0.0
        # Close rebalance: current holdings earn today's return, targets start next session.
        if date in events:
            targets = events[date]
            if qbeast is not None:
                blocked = qbeast.blocked_symbols(set(holdings) | set(targets), signal_dates[date])
                blocked_order_count += len(blocked)
                blocked_holding_events += sum(s in holdings for s in blocked)
                targets = gated_targets(holdings, targets, blocked)
            turnover = sum(abs(targets.get(s, 0.0) - holdings.get(s, 0.0))
                           for s in set(targets) | set(holdings))
            cost = turnover * cost_rate
            gross_factor *= max(0.0, 1.0 - cost)
            holdings = dict(targets)
        if date == calendar[-1] and holdings:
            known_flag_date = calendar[session_i - 1] if session_i > 0 else date
            final_blocked = qbeast.blocked_symbols(holdings, known_flag_date) if qbeast is not None else {}
            liquidation_turnover = sum(weight for symbol, weight in holdings.items()
                                       if symbol not in final_blocked)
            liquidation_cost = liquidation_turnover * cost_rate
            turnover += liquidation_turnover
            cost += liquidation_cost
            gross_factor *= max(0.0, 1.0 - liquidation_cost)
            holdings = {symbol: weight for symbol, weight in holdings.items()
                        if symbol in final_blocked}
        net_ret = gross_factor - 1.0
        daily_rows.append({"date": date.date().isoformat(), "gross_return": gross_ret,
                           "turnover": turnover, "cost_fraction": cost,
                           "return": net_ret, "holdings_count": len(holdings),
                           "qbeast_blocked_orders_cumulative": blocked_order_count,
                           "qbeast_blocked_holding_events_cumulative": blocked_holding_events,
                           "benchmark_return": benchmark_returns.loc[date]})
    daily = pd.DataFrame(daily_rows)
    first_trade = min(events) if events else None
    if first_trade is None:
        raise ValueError("No executable portfolio rebalances in benchmark period")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily[daily.date >= first_trade].reset_index(drop=True)
    daily["benchmark_return"] = daily.benchmark_return.fillna(0.0)
    daily.loc[0, "benchmark_return"] = 0.0
    daily["index_value"] = 100.0 * (1.0 + daily["return"]).cumprod()
    daily["benchmark_index"] = 100.0 * (1.0 + daily.benchmark_return).cumprod()
    daily["drawdown"] = daily.index_value / daily.index_value.cummax() - 1.0
    daily["benchmark_drawdown"] = daily.benchmark_index / daily.benchmark_index.cummax() - 1.0
    years = max((daily.date.iloc[-1] - daily.date.iloc[0]).days / 365.25, 1 / 252)
    def stats(ret_col: str, equity_col: str, dd_col: str) -> dict:
        rets = daily[ret_col].dropna()
        equity = float(daily[equity_col].iloc[-1] / 100.0)
        return {"total_return": equity - 1.0, "cagr": equity ** (1 / years) - 1.0,
                "annualized_volatility": float(rets.std(ddof=1) * np.sqrt(252)),
                "sharpe": float(rets.mean() / rets.std(ddof=1) * np.sqrt(252)) if rets.std(ddof=1) > 0 else math.nan,
                "max_drawdown": float(daily[dd_col].min())}
    summary = {"costs_bps_per_side": {"slippage": slippage_bps, "transaction_cost": transaction_cost_bps},
               "period": [daily.date.iloc[0].date().isoformat(), daily.date.iloc[-1].date().isoformat()],
               "strategy_net": stats("return", "index_value", "drawdown"),
               "nifty500_gross_tri": stats("benchmark_return", "benchmark_index", "benchmark_drawdown"),
               "qbeast_gate": {"version": "2.4.4", "blocked_order_events": blocked_order_count,
                               "blocked_holding_events": blocked_holding_events,
                               "flags_dir": str(qbeast.flags_dir) if qbeast else None,
                               "unliquidated_final_holdings": int(daily.holdings_count.iloc[-1])},
               "cost_model": "cost on buys+sells from absolute portfolio weight changes; initial entry and final liquidation included"}
    return pd.DataFrame(selection_rows), daily, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_DIR)
    parser.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--transaction-cost-bps", type=float, default=10.0)
    parser.add_argument("--qbeast-flags-dir", type=Path, default=DEFAULT_FLAGS_DIR)
    args = parser.parse_args()
    prices, traded, calendar = load_prices(args.prices)
    snapshots = load_membership(args.membership)
    qbeast = QbeastFlagStore(args.qbeast_flags_dir)
    benchmark_frame = pd.read_csv(args.benchmark, usecols=["date", "total_return_index"])
    benchmark_frame["date"] = pd.to_datetime(benchmark_frame.date, errors="coerce")
    benchmark_frame["total_return_index"] = pd.to_numeric(benchmark_frame.total_return_index, errors="coerce")
    benchmark = benchmark_frame.dropna().drop_duplicates("date", keep="last").set_index("date").total_return_index
    selections, daily, summary = run(prices, traded, calendar, snapshots, benchmark,
                                     args.slippage_bps, args.transaction_cost_bps, qbeast)
    args.output.mkdir(parents=True, exist_ok=True)
    selections.to_csv(args.output / "rebalance_selections.csv", index=False)
    daily.to_csv(args.output / "daily_portfolio.csv", index=False)
    import json
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Sessions: {len(calendar)} ({calendar.min().date()} to {calendar.max().date()}); price symbols: {len(prices.columns)}")
    print(f"Rebalances: {selections.signal_date.nunique() if not selections.empty else 0}; selected rows: {len(selections)}")
    print(f"QBEAST v2.4.4 gate: {qbeast.flags_dir}; blocked order events: "
          f"{summary['qbeast_gate']['blocked_order_events']}; blocked holding events: "
          f"{summary['qbeast_gate']['blocked_holding_events']}")
    print(f"Wrote {args.output / 'rebalance_selections.csv'} and {args.output / 'daily_portfolio.csv'}")
    print("PRICE-ONLY PROXY: momentum + low volatility. Quality and value factors unavailable; results are not MQVLv 50 replication.")
    print("Eligibility proxy: one-year listing + bottom decile traded value; official turnover, pledge, and F&O filters absent. QBEAST v2.4.4 applies a separate order gate.")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
