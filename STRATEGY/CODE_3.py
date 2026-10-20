"""Monthly Nifty 100 long-only momentum strategy (Raju & Chandrasekaran, 2019).

Method implemented from the paper: at each month end, calculate 12-1 adjusted
momentum (prior month-end adjusted close / adjusted close 12 calendar months earlier), rank the
then-current Nifty 100 members, equal-weight the top decile (10 names), and
enter at the next month's first session using the open scaled by that date's
adjustment factor. Positions are held until following month's first session.

Uses dated membership snapshots to limit survivorship bias. The supplied
dataset may not contain all historical prices; summary reports rank coverage.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from TESTER.qbeast_gate import DEFAULT_FLAGS_DIR, QbeastFlagStore, gated_targets
DEFAULT_PRICE_DIR = ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY100_EoD_Data"
DEFAULT_MEMBERSHIP = ROOT / "DATASET" / "Survivorship_Bias" / "Nifty100_membership.csv"
DEFAULT_OUTPUT = ROOT / "STRATEGY" / "output_long_only_momentum_nifty100"
DEFAULT_START = "2011-01-01"
DEFAULT_END = "2019-09-30"
PORTFOLIO_SIZE = 10


def args_parser() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-date", default=DEFAULT_START, help="first monthly entry date allowed")
    p.add_argument("--end-date", default=DEFAULT_END, help="last monthly entry date allowed")
    p.add_argument("--price-dir", type=Path, default=DEFAULT_PRICE_DIR)
    p.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--qbeast-flags-dir", type=Path, default=DEFAULT_FLAGS_DIR,
                   help="QBEAST v2.4.4 per-stock EOD outputs (strict coverage required).")
    p.add_argument("--slippage-bps", type=float, default=10.0, help="slippage per traded notional, per side")
    p.add_argument("--transaction-cost-bps", type=float, default=10.0,
                   help="transaction costs per traded notional, per side")
    return p.parse_args()


def load_inputs(price_dir: Path, membership_path: Path):
    index_file = price_dir / "NIFTY 100.csv"
    if not index_file.exists():
        raise FileNotFoundError(f"Nifty 100 trading calendar/index prices not found: {index_file}")
    index = pd.read_csv(index_file)
    required_index = {"date", "open", "close", "adjusted_close"}
    if not required_index.issubset(index.columns):
        raise ValueError(f"{index_file} must contain {sorted(required_index)}")
    index["date"] = pd.to_datetime(index.date, dayfirst=True, errors="coerce")
    index["open"] = pd.to_numeric(index.open, errors="coerce")
    index["close"] = pd.to_numeric(index.close, errors="coerce")
    index["adjusted_close"] = pd.to_numeric(index.adjusted_close, errors="coerce")
    index["adjusted_open"] = index.open * index.adjusted_close / index.close.where(index.close > 0)
    index = index.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    calendar = pd.DatetimeIndex(index.index).sort_values()

    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    for path in sorted(price_dir.glob("*.csv")):
        symbol = path.stem.strip().upper()
        if symbol in {"NIFTY 100", "NIFTY100"}:
            continue
        try:
            frame = pd.read_csv(path, usecols=lambda c: c in {"date", "open", "close", "adj_close"})
        except (ValueError, OSError):
            continue
        if not {"date", "open", "close", "adj_close"}.issubset(frame.columns):
            continue
        frame["date"] = pd.to_datetime(frame.date, dayfirst=True, errors="coerce")
        frame["open"] = pd.to_numeric(frame.open, errors="coerce")
        frame["close"] = pd.to_numeric(frame.close, errors="coerce")
        frame["adj_close"] = pd.to_numeric(frame.adj_close, errors="coerce")
        frame["adj_open"] = frame.open * frame.adj_close / frame.close.where(frame.close > 0)
        frame = frame.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        closes[symbol] = frame.adj_close.where(frame.adj_close > 0).reindex(calendar)
        opens[symbol] = frame.adj_open.where(frame.adj_open > 0).reindex(calendar)
    if not closes:
        raise ValueError(f"No usable stock OHLC files found in {price_dir}")

    membership = pd.read_csv(membership_path)
    required_mem = {"effective_date", "index_type", "symbols"}
    if not required_mem.issubset(membership.columns):
        raise ValueError(f"Membership file must contain {sorted(required_mem)}")
    membership = membership[membership.index_type.astype(str).str.strip().str.lower().eq("nifty 100")].copy()
    membership["effective_date"] = pd.to_datetime(membership.effective_date, errors="coerce")
    membership = (membership.dropna(subset=["effective_date"]).sort_values("effective_date")
                  .drop_duplicates("effective_date", keep="last").reset_index(drop=True))
    if membership.empty:
        raise ValueError(f"No Nifty 100 membership snapshots found in {membership_path}")
    return calendar, index.adjusted_open.reindex(calendar), closes, opens, membership


def point_in_time_members(mem: pd.DataFrame, dates: np.ndarray, symbols: list[str], when: pd.Timestamp) -> set[str]:
    pos = int(np.searchsorted(dates, np.datetime64(when), side="right") - 1)
    if pos < 0:
        return set()
    return {x.strip().upper() for x in str(symbols[pos]).split(",") if x.strip()}


def calc_stats(returns: pd.Series, equity: pd.Series) -> dict[str, float]:
    if returns.empty or equity.empty:
        return {"total_return": math.nan, "cagr": math.nan, "annualized_volatility": math.nan,
                "sharpe": math.nan, "max_drawdown": math.nan}
    span_years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 12)
    wealth = float(equity.iloc[-1])
    cagr = wealth ** (1.0 / span_years) - 1.0 if wealth > 0 else -1.0
    sd = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    vol = sd * math.sqrt(12.0)
    sharpe = float(returns.mean() / sd * math.sqrt(12.0)) if sd > 0 else math.nan
    drawdown = float((equity / equity.cummax() - 1.0).min())
    return {"total_return": wealth - 1.0, "cagr": cagr, "annualized_volatility": vol,
            "sharpe": sharpe, "max_drawdown": drawdown}


def main() -> None:
    args = args_parser()
    qbeast = QbeastFlagStore(args.qbeast_flags_dir)
    if min(args.slippage_bps, args.transaction_cost_bps) < 0:
        raise ValueError("Cost assumptions cannot be negative")
    start, end = pd.Timestamp(args.start_date), pd.Timestamp(args.end_date)
    if start > end:
        raise ValueError("start date must not be after end date")
    calendar, benchmark_open, close_dict, open_dict, mem = load_inputs(args.price_dir, args.membership)
    symbols = sorted(close_dict)
    close = np.column_stack([close_dict[s].to_numpy(dtype=float) for s in symbols])
    open_px = np.column_stack([open_dict[s].to_numpy(dtype=float) for s in symbols])
    sym_col = {s: i for i, s in enumerate(symbols)}
    mem_dates = mem.effective_date.to_numpy(dtype="datetime64[ns]")
    mem_rows = mem.symbols.astype(str).tolist()

    # One record per calendar month: the actual final market session and first
    # market session, determined from the supplied Nifty 100 index calendar.
    by_month: dict[tuple[int, int], list[int]] = {}
    for i, d in enumerate(calendar):
        by_month.setdefault((d.year, d.month), []).append(i)
    month_keys = sorted(by_month)
    month_end_pos = {key: by_month[key][-1] for key in month_keys}
    month_first_pos = {key: by_month[key][0] for key in month_keys}
    terminal_month = (end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1)

    # Form every month's portfolio from the preceding month-end close.
    all_execs: list[dict] = []
    selection_rows: list[dict] = []
    for k, formation_month in enumerate(month_keys):
        next_month = (formation_month[0] + (formation_month[1] == 12),
                      (formation_month[1] % 12) + 1)
        if next_month not in month_first_pos or k < 12:
            continue
        formation_idx = month_end_pos[formation_month]
        entry_idx = month_first_pos[next_month]
        prior_month = month_keys[k - 1]
        lag12_month = month_keys[k - 12]
        entry_date = calendar[entry_idx]
        if entry_date < start or (entry_date > end and next_month != terminal_month):
            continue
        signal_date = calendar[formation_idx]
        universe = point_in_time_members(mem, mem_dates, mem_rows, signal_date)
        candidates: list[tuple[str, float]] = []
        for symbol in universe:
            col = sym_col.get(symbol)
            if col is None:
                continue
            p_lag = close[month_end_pos[prior_month], col]
            p_old = close[month_end_pos[lag12_month], col]
            if np.isfinite(p_lag) and np.isfinite(p_old) and p_lag > 0 and p_old > 0:
                candidates.append((symbol, float(np.log(p_lag / p_old))))
        candidates.sort(key=lambda item: (-item[1], item[0]))
        if not candidates:
            continue
        # The paper selects the top decile (about ten of the 100 members).
        n_select = min(PORTFOLIO_SIZE, max(1, len(universe) // 10), len(candidates))
        # Entry opens are observed only at execution. Walk ranked candidates
        # then fill target count from names actually tradable at that open.
        picks = [(symbol, score) for symbol, score in candidates
                 if np.isfinite(open_px[entry_idx, sym_col[symbol]])
                 and open_px[entry_idx, sym_col[symbol]] > 0][:n_select]
        if not picks:
            continue
        n_select = len(picks)
        all_execs.append({"signal_date": signal_date, "execution_idx": entry_idx,
                          "execution_date": calendar[entry_idx], "symbols": [x[0] for x in picks],
                          "scores": dict(picks), "candidate_count": len(candidates),
                          "universe_count": len(universe)})
        if entry_date <= end:
            for symbol, score in picks:
                selection_rows.append({"signal_date": signal_date.date().isoformat(),
                                       "execution_date": calendar[entry_idx].date().isoformat(),
                                       "symbol": symbol, "momentum_log_return_12_1": score,
                                       "weight": 1.0 / n_select,
                                       "qbeast_signal_block": qbeast.reason(symbol, signal_date)})

    # Need the next rebalance open to measure each open-to-open holding return.
    if len(all_execs) < 2:
        raise RuntimeError("Insufficient monthly selections to form open-to-open holding periods")
    rate = (args.slippage_bps + args.transaction_cost_bps) / 10000.0
    rows: list[dict] = []
    equity = 1.0
    previous_weights: dict[str, float] = {}
    for i in range(len(all_execs) - 1):
        current, nxt = all_execs[i], all_execs[i + 1]
        if current["execution_date"] > end:
            break
        entry_idx, exit_idx = current["execution_idx"], nxt["execution_idx"]
        proposed = {s: 1.0 / len(current["symbols"]) for s in current["symbols"]}
        if previous_weights:
            denominator = 1.0 + previous_gross
            drifted = ({s: w * (1.0 + previous_asset_returns.get(s, 0.0)) / denominator
                        for s, w in previous_weights.items()} if denominator > 0 else {})
        else:
            drifted = {}
        blocked = qbeast.blocked_symbols(set(drifted) | set(proposed), current["signal_date"])
        target = gated_targets(drifted, proposed, blocked)
        selected = list(target)
        asset_returns = {}
        missing_exit_marks = 0
        for s in selected:
            col = sym_col[s]
            exit_open = open_px[exit_idx, col]
            if not np.isfinite(exit_open) or exit_open <= 0:
                # No scheduled exit quote: use last observed open before exit,
                # flag period. This is a mark proxy, not confirmed execution.
                prior = np.flatnonzero(np.isfinite(open_px[entry_idx + 1:exit_idx + 1, col])
                                       & (open_px[entry_idx + 1:exit_idx + 1, col] > 0))
                exit_open = (float(open_px[entry_idx + 1 + prior[-1], col]) if len(prior)
                             else float(open_px[entry_idx, col]))
                missing_exit_marks += 1
            asset_returns[s] = float(exit_open / open_px[entry_idx, col] - 1.0)
        gross_return = sum(target[s] * asset_returns[s] for s in selected)
        if gross_return <= -1:
            gross_return = -1.0

        # Rebalance at this month's entry. Use the drifted prior holdings to
        # estimate actual buys+sells; initial investment turnover is 100%.
        traded_notional = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0))
                              for s in set(target) | set(drifted))
        turnover = 0.5 * traded_notional
        cost = min(1.0, traded_notional * rate)
        net_return = (1.0 - cost) * (1.0 + gross_return) - 1.0
        equity *= max(0.0, 1.0 + net_return)

        b0, b1 = float(benchmark_open.iloc[entry_idx]), float(benchmark_open.iloc[exit_idx])
        benchmark_return = b1 / b0 - 1.0 if b0 > 0 and b1 > 0 else np.nan
        rows.append({"signal_date": current["signal_date"].date().isoformat(),
                     "execution_date": current["execution_date"].date().isoformat(),
                     "exit_date": nxt["execution_date"].date().isoformat(),
                     "holding_sessions": exit_idx - entry_idx,
                     "universe_count": current["universe_count"],
                     "ranked_count": current["candidate_count"], "selected_count": len(selected),
                     "qbeast_blocked_order_count": len(blocked),
                     "qbeast_blocked_holding_count": sum(s in drifted for s in blocked),
                     "cash_weight": max(0.0, 1.0 - sum(target.values())),
                     "missing_scheduled_exit_quotes": missing_exit_marks,
                     "one_way_turnover": turnover, "gross_return": gross_return,
                     "cost_return": cost, "net_return": net_return, "equity": equity,
                     "nifty100_price_return": benchmark_return})
        selection_rows  # retained for the selection CSV below
        previous_weights = target
        previous_asset_returns = asset_returns
        previous_gross = gross_return

    if not rows:
        raise RuntimeError("No monthly portfolio periods were produced for the requested date range")
    # Liquidate only positions tradable at the final execution opportunity.
    final_blocked = qbeast.blocked_symbols(previous_weights, all_execs[-1]["signal_date"])
    final_liquidation_cost = rate * sum(w for s, w in previous_weights.items() if s not in final_blocked)
    rows[-1]["cost_return"] += final_liquidation_cost
    rows[-1]["net_return"] = ((1.0 + rows[-1]["net_return"]) * (1.0 - final_liquidation_cost)) - 1.0
    rows[-1]["equity"] = rows[-2]["equity"] * (1.0 + rows[-1]["net_return"]) if len(rows) > 1 else 1.0 + rows[-1]["net_return"]

    args.output.mkdir(parents=True, exist_ok=True)
    daily = pd.DataFrame(rows)
    daily.to_csv(args.output / "monthly_portfolio.csv", index=False)
    pd.DataFrame(selection_rows).to_csv(args.output / "monthly_selections.csv", index=False)
    equity_series = pd.Series(
        np.r_[1.0, daily.equity.to_numpy()],
        index=pd.DatetimeIndex([pd.Timestamp(daily.execution_date.iloc[0]), *pd.to_datetime(daily.exit_date).tolist()]),
    )
    strategy_returns = daily.net_return.astype(float)
    benchmark_returns = daily.nifty100_price_return.astype(float)
    benchmark_growth = (1.0 + benchmark_returns.fillna(0.0)).cumprod().to_numpy()
    benchmark_equity = pd.Series(
        np.r_[1.0, benchmark_growth],
        index=pd.DatetimeIndex([pd.Timestamp(daily.execution_date.iloc[0]), *pd.to_datetime(daily.exit_date).tolist()]),
    )
    summary = {
        "strategy": "Raju & Chandrasekaran (2019) 12-1 momentum; monthly top-decile Nifty 100; equal-weight long-only",
        "requested_period": [start.date().isoformat(), end.date().isoformat()],
        "actual_execution_period": [daily.execution_date.iloc[0], daily.exit_date.iloc[-1]],
        "holding_periods": int(len(daily)), "average_selected_stocks": float(daily.selected_count.mean()),
        "average_rankable_constituents": float(daily.ranked_count.mean()),
        "nominal_universe_size": 100,
        "average_one_way_turnover_excluding_initial_entry": float(daily.one_way_turnover.iloc[1:].mean()) if len(daily) > 1 else math.nan,
        "slippage_bps_per_traded_notional_per_side": args.slippage_bps,
        "transaction_cost_bps_per_traded_notional_per_side": args.transaction_cost_bps,
        "cost_model": "cost applies to buys+sells implied by weight changes; final exit cost applies only to positions QBEAST permits to exit; blocked positions remain open",
        "qbeast_gate": {"version": "2.4.4", "flags_dir": str(qbeast.flags_dir),
                        "blocked_order_events": int(daily.qbeast_blocked_order_count.sum()),
                        "blocked_holding_events": int(daily.qbeast_blocked_holding_count.sum()),
                        "blocked_positions_at_final_exit": final_blocked},
        "metrics_net": calc_stats(strategy_returns, equity_series),
        "metrics_nifty100_price_index": calc_stats(benchmark_returns, benchmark_equity),
        "benchmark_caveat": "Nifty 100 price index open-to-open; stock prices use adj_close and opens scaled by same-day adj_close/close. Benchmark has no matching TRI series, so distributions may not be comparable.",
        "paper_reported_annual_outperformance_percentage_points": 10.70,
        "paper_reported_mean_monthly_turnover": 0.321,
        "limitations": [
            "Paper period is Jan 2011 through Sep 2019; results depend on local OHLC history and historical membership snapshots.",
            "Ranking requires valid month-end closes at both 12-1 endpoints; incomplete prices reduce the eligible universe.",
            "Costs are configurable flat bps and do not model impact, taxes by exchange order details, or capacity.",
        ],
        "files": ["monthly_portfolio.csv", "monthly_selections.csv", "equity_curve.png", "summary.json"],
    }
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(equity_series.index, equity_series.values, label="Momentum portfolio (net)", linewidth=1.6)
    ax.plot(benchmark_equity.index, benchmark_equity.values, label="Nifty 100 price index", linewidth=1.3)
    ax.set(title="Monthly Nifty 100 12–1 long-only momentum", xlabel="Date", ylabel="Equity multiple (start = 1)")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.output / "equity_curve.png", dpi=150)
    plt.close(fig)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
