"""Monthly volatility-adjusted momentum proxy for Indian equities.

QED Capital's 2021 working paper describes Q-Mom as ranking momentum more
highly when its return path has lower volatility, but does not publish a full
replicable Q-Mom formula. This script therefore provides an explicit proxy:

* Point-in-time Nifty 200 universe; select the top 30 names each month.
* Momentum = 11-month adjusted log return from month t-12 to t-1 (skip latest month).
* Rank by momentum / annualized daily volatility over the same formation window.
* Equal weights; enter at next month's first open scaled by same-day adjustment
  factor; hold to following first adjusted open.
* Compare with the Nifty 200 adjusted-index open-to-open series.

The volatility-adjusted portfolio is an independently specified proxy, not a
replication of QED's proprietary Q-Mom construction or the Nifty 200 Momentum 30
index weighting methodology.
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from TESTER.qbeast_gate import DEFAULT_FLAGS_DIR, QbeastFlagStore, gated_targets
DEFAULT_PRICE_DIR = ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY200_EoD_Data"
DEFAULT_BENCHMARK = DEFAULT_PRICE_DIR / "NIFTY 200.csv"
DEFAULT_MEMBERSHIP = ROOT / "DATASET" / "Survivorship_Bias" / "Nifty200_membership.csv"
DEFAULT_OUTPUT = ROOT / "STRATEGY" / "output_momentum_vol_adjusted"
DEFAULT_START = "2014-01-01"
DEFAULT_END = "2021-06-30"
PORTFOLIO_SIZE = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=DEFAULT_START, help="first monthly entry date")
    parser.add_argument("--end-date", default=DEFAULT_END, help="last monthly entry date")
    parser.add_argument("--price-dir", type=Path, default=DEFAULT_PRICE_DIR)
    parser.add_argument("--benchmark-file", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--qbeast-flags-dir", type=Path, default=DEFAULT_FLAGS_DIR,
                        help="QBEAST v2.4.4 per-stock EOD outputs (strict coverage required).")
    parser.add_argument("--slippage-bps", type=float, default=10.0, help="slippage per traded notional, per side")
    parser.add_argument("--transaction-cost-bps", type=float, default=10.0,
                        help="transaction costs per traded notional, per side")
    parser.add_argument("--portfolio-size", type=int, default=PORTFOLIO_SIZE)
    parser.add_argument("--min-vol-observations", type=int, default=120,
                        help="minimum daily returns in formation window for a stock to be eligible")
    return parser.parse_args()


def read_ohlc(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=lambda c: c in {"date", "open", "close", "adj_close", "adjusted_close"})
    adjusted_column = "adj_close" if "adj_close" in frame else "adjusted_close"
    if not {"date", "open", "close"}.issubset(frame.columns) or adjusted_column not in frame.columns:
        raise ValueError(f"{path} must include date, open, close, and an adjusted-close column")
    frame["date"] = pd.to_datetime(frame.date, dayfirst=True, errors="coerce")
    frame["open"] = pd.to_numeric(frame.open, errors="coerce")
    frame["close"] = pd.to_numeric(frame.close, errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame[adjusted_column], errors="coerce")
    factor = frame.adjusted_close / frame.close.where(frame.close > 0)
    frame["adjusted_open"] = frame.open * factor
    return (frame.dropna(subset=["date"]).sort_values("date")
            .drop_duplicates("date", keep="last").set_index("date"))


def load_data(price_dir: Path, benchmark_file: Path, membership_file: Path):
    index_path = price_dir / "NIFTY 200.csv"
    if not index_path.exists():
        raise FileNotFoundError(f"Nifty 200 calendar missing: {index_path}")
    index = read_ohlc(index_path)
    calendar = pd.DatetimeIndex(index.index).sort_values()
    benchmark = read_ohlc(benchmark_file).adjusted_open.reindex(calendar)

    close_map: dict[str, pd.Series] = {}
    open_map: dict[str, pd.Series] = {}
    for path in sorted(price_dir.glob("*.csv")):
        symbol = path.stem.strip().upper()
        if symbol in {"NIFTY 200", "NIFTY200"}:
            continue
        try:
            frame = read_ohlc(path)
        except (ValueError, OSError, pd.errors.ParserError):
            continue
        close_map[symbol] = frame.adjusted_close.where(frame.adjusted_close > 0).reindex(calendar)
        open_map[symbol] = frame.adjusted_open.where(frame.adjusted_open > 0).reindex(calendar)
    if not close_map:
        raise ValueError(f"No usable stock price files in {price_dir}")

    mem = pd.read_csv(membership_file)
    required = {"effective_date", "index_type", "symbols"}
    if not required.issubset(mem.columns):
        raise ValueError(f"Membership data must include {sorted(required)}")
    mem = mem[mem.index_type.astype(str).str.strip().str.lower().eq("nifty 200")].copy()
    mem["effective_date"] = pd.to_datetime(mem.effective_date, errors="coerce")
    mem = (mem.dropna(subset=["effective_date"]).sort_values("effective_date")
           .drop_duplicates("effective_date", keep="last").reset_index(drop=True))
    if mem.empty:
        raise ValueError(f"No Nifty 200 snapshots in {membership_file}")
    return calendar, benchmark, close_map, open_map, mem


def asof_universe(mem_dates: np.ndarray, mem_rows: list[str], date: pd.Timestamp) -> set[str]:
    pos = int(np.searchsorted(mem_dates, np.datetime64(date), side="right") - 1)
    if pos < 0:
        return set()
    return {x.strip().upper() for x in mem_rows[pos].split(",") if x.strip()}


def calc_stats(returns: pd.Series, equity: pd.Series) -> dict[str, float]:
    if returns.empty or equity.empty:
        return {"total_return": math.nan, "cagr": math.nan, "annualized_volatility": math.nan,
                "sharpe": math.nan, "max_drawdown": math.nan}
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 12)
    wealth = float(equity.iloc[-1])
    cagr = wealth ** (1 / years) - 1 if wealth > 0 else -1.0
    sd = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    vol = sd * math.sqrt(12.0)
    sharpe = float(returns.mean() / sd * math.sqrt(12.0)) if sd > 0 else math.nan
    mdd = float((equity / equity.cummax() - 1).min())
    return {"total_return": wealth - 1, "cagr": cagr, "annualized_volatility": vol,
            "sharpe": sharpe, "max_drawdown": mdd}


def build_monthly_signals(calendar: pd.DatetimeIndex, close: np.ndarray, open_px: np.ndarray,
                          symbols: list[str], mem: pd.DataFrame, start: pd.Timestamp,
                          end: pd.Timestamp, min_vol_obs: int, portfolio_size: int) -> list[dict]:
    month_positions: dict[tuple[int, int], list[int]] = {}
    for i, date in enumerate(calendar):
        month_positions.setdefault((date.year, date.month), []).append(i)
    months = sorted(month_positions)
    month_end = {m: pos[-1] for m, pos in month_positions.items()}
    month_first = {m: pos[0] for m, pos in month_positions.items()}
    mem_dates = mem.effective_date.to_numpy(dtype="datetime64[ns]")
    mem_rows = mem.symbols.astype(str).tolist()
    terminal_month = (end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1)
    output: list[dict] = []

    for k, formation_month in enumerate(months):
        next_month = (formation_month[0] + (formation_month[1] == 12),
                      formation_month[1] % 12 + 1)
        if next_month not in month_first or k < 12:
            continue
        entry_idx = month_first[next_month]
        entry_date = calendar[entry_idx]
        # Keep one next-month execution after end date to mark the final holding period.
        if entry_date < start or (entry_date > end and next_month != terminal_month):
            continue
        formation_date = calendar[month_end[formation_month]]
        prev_idx = month_end[months[k - 1]]
        old_idx = month_end[months[k - 12]]
        universe = asof_universe(mem_dates, mem_rows, formation_date)
        if not universe:
            continue
        close_lag = close[prev_idx]
        close_old = close[old_idx]
        with np.errstate(divide="ignore", invalid="ignore"):
            momentum = np.log(close_lag / close_old)
        # Volatility from daily close-to-close returns over the exact same
        # t-12 to t-1 formation interval; latest month is excluded.
        daily = close[old_idx:prev_idx + 1]
        with np.errstate(divide="ignore", invalid="ignore"):
            daily_returns = np.diff(np.log(daily), axis=0)
        valid_return_count = np.isfinite(daily_returns).sum(axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            vol = np.nanstd(daily_returns, axis=0, ddof=1)
        eligible = np.fromiter((s in universe for s in symbols), dtype=bool, count=len(symbols))
        valid = (eligible & np.isfinite(momentum) & np.isfinite(vol) & (vol > 0)
                 & (valid_return_count >= min_vol_obs))
        cols = np.flatnonzero(valid)
        if not len(cols):
            continue
        # Annualization multiplier is constant for the cross-section and does
        # not alter rank; retained in formula to make units interpretable.
        adj_score = momentum / (vol * math.sqrt(252.0))
        order_adj = cols[np.argsort(-adj_score[cols], kind="stable")]
        n = min(len(cols), portfolio_size)
        # Rank from signal-date data only. At the next open, fill from ranked
        # names that have an executable opening quote.
        order_adj = np.asarray([j for j in order_adj
                                if np.isfinite(open_px[entry_idx, j]) and open_px[entry_idx, j] > 0], dtype=int)
        n = min(len(order_adj), portfolio_size)
        if n == 0:
            continue
        output.append({
            "signal_date": formation_date, "entry_idx": entry_idx, "entry_date": entry_date,
            "candidate_count": int(len(cols)), "universe_count": int(len(universe)),
            "vol_adjusted": {symbols[j]: float(adj_score[j]) for j in order_adj[:n]},
        })
    return output


def backtest(name: str, signals: list[dict], open_px: np.ndarray, benchmark: pd.Series,
             sym_col: dict[str, int], rate: float,
             qbeast: QbeastFlagStore) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    rows: list[dict] = []
    picks_log: list[dict] = []
    previous_weights: dict[str, float] = {}
    equity = 1.0
    previous_asset_returns: dict[str, float] = {}
    previous_gross = 0.0
    blocked_order_count = 0
    blocked_holding_count = 0

    for i in range(len(signals) - 1):
        current, nxt = signals[i], signals[i + 1]
        target_names = list(current[name])
        proposed = {s: 1.0 / len(target_names) for s in target_names} if target_names else {}
        if previous_weights:
            denominator = 1.0 + previous_gross
            drifted = ({s: w * (1.0 + previous_asset_returns.get(s, 0.0)) / denominator
                        for s, w in previous_weights.items()} if denominator > 0 else {})
        else:
            drifted = {}
        blocked = qbeast.blocked_symbols(set(drifted) | set(proposed), current["signal_date"])
        blocked_order_count += len(blocked)
        blocked_holding_count += sum(s in drifted for s in blocked)
        target = gated_targets(drifted, proposed, blocked)
        target_names = list(target)
        e0, e1 = current["entry_idx"], nxt["entry_idx"]
        asset_ret: dict[str, float] = {}
        missing_exit_marks = 0
        for s in target_names:
            col = sym_col[s]
            exit_open = open_px[e1, col]
            if not np.isfinite(exit_open) or exit_open <= 0:
                # If a quote is absent on scheduled exit, liquidate at the
                # last recorded open during the holding interval and flag it.
                prior_quotes = np.flatnonzero(np.isfinite(open_px[e0 + 1:e1 + 1, col])
                                              & (open_px[e0 + 1:e1 + 1, col] > 0))
                if len(prior_quotes):
                    exit_open = float(open_px[e0 + 1 + prior_quotes[-1], col])
                else:
                    exit_open = float(open_px[e0, col])
                missing_exit_marks += 1
            asset_ret[s] = float(exit_open / open_px[e0, col] - 1.0)
        gross = sum(target[s] * asset_ret[s] for s in target_names)
        gross = max(gross, -1.0)
        traded_notional = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0))
                              for s in set(target) | set(drifted))
        one_way_turnover = 0.5 * traded_notional
        entry_cost = min(1.0, traded_notional * rate)
        net = (1.0 - entry_cost) * (1.0 + gross) - 1.0
        equity *= max(0.0, 1.0 + net)
        b0, b1 = float(benchmark.iloc[e0]), float(benchmark.iloc[e1])
        bench_ret = b1 / b0 - 1.0 if b0 > 0 and b1 > 0 else np.nan
        rows.append({"strategy": name, "signal_date": current["signal_date"].date().isoformat(),
                     "entry_date": current["entry_date"].date().isoformat(),
                     "exit_date": nxt["entry_date"].date().isoformat(),
                     "holding_sessions": e1 - e0, "universe_count": current["universe_count"],
                     "ranked_count": current["candidate_count"], "selected_count": len(target_names),
                     "qbeast_blocked_order_count": len(blocked),
                     "qbeast_blocked_holding_count": sum(s in drifted for s in blocked),
                     "cash_weight": max(0.0, 1.0 - sum(target.values())),
                     "missing_scheduled_exit_quotes": missing_exit_marks,
                     "one_way_turnover": one_way_turnover, "gross_return": gross,
                     "entry_cost_return": entry_cost, "net_return": net, "equity": equity,
                     "nifty200_price_return": bench_ret})
        for s in target:
            score = current[name].get(s, np.nan)
            picks_log.append({"strategy": name, "signal_date": current["signal_date"].date().isoformat(),
                              "entry_date": current["entry_date"].date().isoformat(),
                              "symbol": s, "score": score, "weight": target[s]})
        previous_weights, previous_asset_returns, previous_gross = target, asset_ret, gross

    final_blocked = qbeast.blocked_symbols(previous_weights, signals[-1]["signal_date"]) if rows else {}
    if rows:
        final_cost = rate * sum(w for s, w in previous_weights.items() if s not in final_blocked)
        rows[-1]["exit_cost_return"] = final_cost
        rows[-1]["net_return"] = (1.0 + rows[-1]["net_return"]) * (1.0 - final_cost) - 1.0
        rows[-1]["equity"] = rows[-2]["equity"] * (1.0 + rows[-1]["net_return"]) if len(rows) > 1 else 1.0 + rows[-1]["net_return"]
    for row in rows[:-1]:
        row["exit_cost_return"] = 0.0
    if rows:
        rows[-1]["qbeast_blocked_positions_at_final_exit"] = len(final_blocked)
        for row in rows[:-1]:
            row["qbeast_blocked_positions_at_final_exit"] = 0
    return pd.DataFrame(rows), pd.DataFrame(picks_log), final_blocked


def equity_and_metrics(frame: pd.DataFrame) -> tuple[pd.Series, dict[str, float]]:
    if frame.empty:
        return pd.Series(dtype=float), calc_stats(pd.Series(dtype=float), pd.Series(dtype=float))
    dates = [pd.Timestamp(frame.entry_date.iloc[0]), *pd.to_datetime(frame.exit_date).tolist()]
    equity = pd.Series(np.r_[1.0, frame.equity.to_numpy(dtype=float)], index=pd.DatetimeIndex(dates))
    metrics = calc_stats(frame.net_return.astype(float), equity)
    return equity, metrics


def main() -> None:
    args = parse_args()
    qbeast = QbeastFlagStore(args.qbeast_flags_dir)
    if args.portfolio_size < 1 or args.min_vol_observations < 2:
        raise ValueError("portfolio size must be positive and min volatility observations at least 2")
    if args.slippage_bps < 0 or args.transaction_cost_bps < 0:
        raise ValueError("Costs cannot be negative")
    start, end = pd.Timestamp(args.start_date), pd.Timestamp(args.end_date)
    if start > end:
        raise ValueError("start date must not be after end date")
    calendar, benchmark, close_map, open_map, mem = load_data(args.price_dir, args.benchmark_file, args.membership)
    symbols = sorted(close_map)
    close = np.column_stack([close_map[s].to_numpy(dtype=float) for s in symbols])
    open_px = np.column_stack([open_map[s].to_numpy(dtype=float) for s in symbols])
    sym_col = {s: i for i, s in enumerate(symbols)}
    signals = build_monthly_signals(calendar, close, open_px, symbols, mem, start, end,
                                    args.min_vol_observations, args.portfolio_size)
    if len(signals) < 2:
        raise RuntimeError("Not enough monthly signal dates; check historical price and membership coverage")
    rate = (args.slippage_bps + args.transaction_cost_bps) / 10000.0
    adjusted, adjusted_picks, final_blocked = backtest(
        "vol_adjusted", signals, open_px, benchmark, sym_col, rate, qbeast
    )
    if adjusted.empty:
        raise RuntimeError("The volatility-adjusted portfolio generated no holding periods")
    adjusted_eq, adjusted_stats = equity_and_metrics(adjusted)
    benchmark_returns = adjusted.nifty200_price_return.astype(float)
    benchmark_eq = pd.Series(np.r_[1.0, (1 + benchmark_returns.fillna(0.0)).cumprod().to_numpy()],
                             index=adjusted_eq.index)
    benchmark_stats = calc_stats(benchmark_returns, benchmark_eq)
    args.output.mkdir(parents=True, exist_ok=True)
    adjusted.to_csv(args.output / "monthly_portfolio.csv", index=False)
    adjusted_picks.to_csv(args.output / "monthly_selections.csv", index=False)

    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(adjusted_eq.index, adjusted_eq.values, label="Volatility-adjusted proxy (net)", linewidth=1.5)
    ax.plot(benchmark_eq.index, benchmark_eq.values, label="Nifty 200 price index", linewidth=1.2)
    ax.set(title="Monthly volatility-adjusted momentum proxy", xlabel="Date", ylabel="Equity multiple (start = 1)")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.output / "equity_curve.png", dpi=150)
    plt.close(fig)

    summary = {
        "paper": "QED Capital, Momentum Factor in Indian Markets: Evidence from the Long Side (2021 working paper)",
        "implementation_status": "transparent proxy; Q-Mom score formula is not fully disclosed in the paper",
        "requested_period": [start.date().isoformat(), end.date().isoformat()],
        "actual_entry_period": [adjusted.entry_date.iloc[0], adjusted.entry_date.iloc[-1]],
        "actual_measurement_period": [adjusted.entry_date.iloc[0], adjusted.exit_date.iloc[-1]],
        "universe": "point-in-time Nifty 200 membership; only names with usable monthly endpoints and volatility history rank",
        "portfolio": f"top {args.portfolio_size}, equal weight, long-only; monthly rotation",
        "momentum_formula": "log(adjusted close at month t-1 / adjusted close at month t-12); latest month skipped",
        "vol_adjusted_formula": "adjusted momentum divided by annualized daily adjusted-close volatility over same formation window",
        "benchmark": "Nifty 200 adjusted price index open-to-open; stock prices use adj_close-adjusted opens. No matching TRI benchmark is present.",
        "costs_bps_per_traded_notional_per_side": {"slippage": args.slippage_bps,
                                                      "transaction_cost": args.transaction_cost_bps},
        "cost_model": "costs apply to buys and sells implied by weight changes; final exit cost applies only to positions QBEAST permits to exit; blocked positions remain open",
        "qbeast_gate": {"version": "2.4.4", "flags_dir": str(qbeast.flags_dir),
                        "blocked_order_events": int(adjusted.qbeast_blocked_order_count.sum()),
                        "blocked_holding_events": int(adjusted.qbeast_blocked_holding_count.sum()),
                        "blocked_positions_at_final_exit_reasons": final_blocked,
                        "blocked_positions_at_final_exit": int(adjusted.qbeast_blocked_positions_at_final_exit.iloc[-1])},
        "metrics_net": {"volatility_adjusted_proxy": adjusted_stats,
                        "nifty200_price_index": benchmark_stats},
        "coverage": {"average_rankable": float(adjusted.ranked_count.mean()),
                     "average_selected_stocks": float(adjusted.selected_count.mean()),
                     "nominal_universe": 200},
        "paper_reference_post_2014_to_june_2021": {
            "wealth_from_100_nifty50": 261,
            "wealth_from_100_momentum30": 461,
            "wealth_from_100_q_mom": 538,
            "source_note": "paper chart values are gross/reference figures and not directly comparable to this costed proxy",
        },
        "limitations": [
            "The paper does not disclose a complete Q-Mom formula or exact portfolio construction; volatility-adjusted score here is a proxy.",
            "Nifty 200 Momentum 30 index weighting is not replicated; this proxy is equal weighted.",
            "Local price gaps reduce the historical Nifty 200 rankable universe; coverage is reported above.",
            "Open prices use same-day adjusted_close/close factor; source adjustment semantics apply.",
            "Flat bps costs omit market impact, capacity, taxes specific to actual order size, and corporate-action-specific execution effects.",
        ],
        "files": ["monthly_portfolio.csv", "monthly_selections.csv", "equity_curve.png", "summary.json"],
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
