"""Point-in-time Nifty 500 Momentum 50 research backtest.

Implements NSE momentum signal and semi-annual May/November cut-offs.
Transparent proxy, not exact index replication: dataset lacks historical free-
float market caps, promoter pledges, F&O status, point-in-time exchange bands,
and full official liquidity inputs. Uses traded-value liquidity proxy and equal
weights. The costed backtester applies the separate QBEAST v2.4.4 order gate.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import math
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICE_DIR = ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY500_EoD_Data"
DEFAULT_MEMBERSHIP = ROOT / "DATASET" / "Survivorship_Bias" / "Nifty500_membership.csv"
DEFAULT_OUTPUT = ROOT / "STRATEGY" / "output"
N_TRADING_DAYS = 252
PORTFOLIO_SIZE = 50


def load_prices(price_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load available adjusted-close prices and traded-value data."""
    close_cols, turnover_cols = {}, {}
    for path in sorted(price_dir.glob("*.csv")):
        symbol = path.stem.strip().upper()
        # This file defines the exchange-session calendar, not a tradable stock.
        if symbol == "NIFTY500":
            continue
        frame = pd.read_csv(path, usecols=lambda c: c in {"date", "adj_close", "close", "volume"})
        if not {"date", "adj_close", "close", "volume"}.issubset(frame.columns):
            continue
        frame["date"] = pd.to_datetime(frame["date"], dayfirst=True, errors="coerce")
        for col in ("adj_close", "close", "volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        adj = frame["adj_close"].where(frame["adj_close"] > 0)
        traded_value = frame["close"].where(frame["close"] > 0) * frame["volume"].where(frame["volume"] >= 0)
        if adj.notna().any():
            close_cols[symbol] = adj
            turnover_cols[symbol] = traded_value
    if not close_cols:
        raise ValueError(f"No valid price CSVs found in {price_dir}")
    calendar_path = price_dir / "NIFTY500.csv"
    if not calendar_path.exists():
        raise FileNotFoundError(f"Nifty 500 exchange calendar not found: {calendar_path}")
    calendar_data = pd.read_csv(calendar_path, usecols=["date"])
    calendar_data["date"] = pd.to_datetime(calendar_data["date"], dayfirst=True, errors="coerce")
    calendar = pd.DatetimeIndex(calendar_data["date"].dropna().drop_duplicates().sort_values())
    if calendar.empty:
        raise ValueError(f"No valid exchange-session dates in {calendar_path}")
    # Keep missing sessions missing. Forward-filling can carry a delisted or
    # suspended stock's stale close indefinitely and fabricate flat returns.
    prices = pd.concat(close_cols, axis=1, sort=True).sort_index().reindex(calendar)
    turnover = pd.concat(turnover_cols, axis=1, sort=True).reindex(calendar)
    return prices, turnover


def load_membership(path: Path) -> list[tuple[pd.Timestamp, set[str]]]:
    """Read dated constituent snapshots; later snapshots never leak into past."""
    raw = pd.read_csv(path, dtype={"symbols": str})
    if not {"effective_date", "symbols"}.issubset(raw.columns):
        raise ValueError(f"Membership file needs effective_date and symbols: {path}")
    raw["effective_date"] = pd.to_datetime(raw["effective_date"], errors="coerce")
    snapshots = []
    for row in raw.dropna(subset=["effective_date"]).sort_values("effective_date").itertuples():
        symbols = {s.strip().upper() for s in str(row.symbols).split(",") if s.strip()}
        snapshots.append((row.effective_date.normalize(), symbols))
    if not snapshots:
        raise ValueError(f"No dated membership snapshots in {path}")
    return snapshots


def constituents_asof(snapshots: list[tuple[pd.Timestamp, set[str]]], date: pd.Timestamp) -> set[str]:
    matches = [members for effective, members in snapshots if effective <= date]
    return matches[-1] if matches else set()


def last_on_or_before(series: pd.Series, date: pd.Timestamp) -> float:
    values = series.loc[:date].dropna()
    return float(values.iloc[-1]) if not values.empty else math.nan


def returns_from_observed_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute quote-to-quote returns; missing dates stay unpriced, not flat."""
    return prices.apply(lambda s: s.dropna().pct_change(fill_method=None).reindex(s.index))


def score_universe(signal_date: pd.Timestamp, universe: set[str], prices: pd.DataFrame,
                   turnover: pd.DataFrame, previous_holdings: set[str]) -> pd.DataFrame:
    """NSE momentum ratios and cross-sectional normalized score, plus available filters."""
    rows = []
    start_6m = signal_date - pd.DateOffset(months=6)
    start_12m = signal_date - pd.DateOffset(months=12)
    vol_start = signal_date - pd.DateOffset(days=370)
    liquidity_start = signal_date - pd.DateOffset(months=6)
    for symbol in sorted(universe):
        if symbol not in prices.columns:
            continue
        p = prices[symbol].loc[:signal_date]
        observed = p.dropna()
        if observed.empty or observed.index.min() > signal_date - pd.Timedelta(days=365):
            continue
        # Require a current signal-date close; older endpoint closes remain
        # valid for calendar lookbacks, but stale current marks do not.
        if signal_date not in p.index or not np.isfinite(p.loc[signal_date]):
            continue
        p_end, p6, p12 = (last_on_or_before(p, d) for d in (signal_date, start_6m, start_12m))
        if not all(np.isfinite(x) and x > 0 for x in (p_end, p6, p12)):
            continue
        # Volatility uses adjacent exchange sessions only; gaps do not become
        # fictitious one-day moves.
        daily_log_returns = np.log(p / p.shift(1)).loc[vol_start:signal_date].dropna()
        if len(daily_log_returns) < 220:
            continue
        vol = float(daily_log_returns.std(ddof=1) * np.sqrt(N_TRADING_DAYS))
        if not np.isfinite(vol) or vol <= 0:
            continue
        t = turnover[symbol].loc[liquidity_start:signal_date].dropna() if symbol in turnover else pd.Series(dtype=float)
        if t.empty:
            continue
        r6, r12 = p_end / p6 - 1, p_end / p12 - 1
        rows.append({"symbol": symbol, "return_6m": r6, "return_12m": r12,
                     "annualized_volatility": vol, "momentum_ratio_6m": r6 / vol,
                     "momentum_ratio_12m": r12 / vol,
                     "avg_daily_turnover_proxy": float(t.mean()),
                     "is_existing_member": symbol in previous_holdings})
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    # Bottom decile by 6-month average traded value: proxy for official turnover.
    cutoff = result["avg_daily_turnover_proxy"].quantile(0.10)
    result = result.loc[result["avg_daily_turnover_proxy"] >= cutoff].copy()
    for col in ("momentum_ratio_6m", "momentum_ratio_12m"):
        sd = result[col].std(ddof=0)
        result[f"z_{col}"] = (result[col] - result[col].mean()) / sd if sd > 0 else 0.0
    result["weighted_average_z"] = 0.5 * (result["z_momentum_ratio_6m"] + result["z_momentum_ratio_12m"])
    z = result["weighted_average_z"]
    result["normalized_momentum_score"] = np.where(z >= 0, 1 + z, 1 / (1 - z))
    result = result.sort_values(["normalized_momentum_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    result["rank"] = np.arange(1, len(result) + 1)
    return result


def buffered_selection(scored: pd.DataFrame, previous: set[str], size: int) -> list[str]:
    """NSE hysteresis: hold existing through rank 75; admit top 25 new names."""
    if scored.empty:
        return []
    ranks = dict(zip(scored.symbol, scored["rank"]))
    eligible = set(ranks)
    incumbents = {s for s in previous if s in eligible and ranks[s] <= 75}
    mandatory_new = [s for s in scored.symbol if s not in previous][:25]
    # Keep all mandatory entrants; retain highest-ranked eligible incumbents
    # next, then fill remaining slots in overall score order.
    selected = set(mandatory_new)
    for symbol in sorted(incumbents, key=lambda s: (ranks[s], s)):
        if len(selected) >= size:
            break
        selected.add(symbol)
    for symbol in scored.symbol:
        if len(selected) >= size:
            break
        selected.add(symbol)
    return sorted(selected, key=lambda s: (ranks.get(s, 10**9), s))[:size]


def rebalance_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    dates = []
    for year in sorted(set(index.year)):
        for month in (5, 11):
            month_dates = index[(index.year == year) & (index.month == month)]
            if len(month_dates):
                dates.append(month_dates[-1])
    return dates


def run_backtest(prices: pd.DataFrame, turnover: pd.DataFrame,
                 snapshots: list[tuple[pd.Timestamp, set[str]]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_returns = returns_from_observed_prices(prices.sort_index())
    selection_rows, weight_events = [], {}
    held: set[str] = set()
    sessions = prices.index
    for signal_date in rebalance_dates(sessions):
        universe = constituents_asof(snapshots, signal_date)
        scored = score_universe(signal_date, universe, prices, turnover, held)
        chosen = buffered_selection(scored, held, PORTFOLIO_SIZE)
        later = sessions[sessions > signal_date]
        if later.size:
            # Signal close is known before next session. Weights apply at next
            # session close; returns start the following session, avoiding lookahead.
            execution_date = later[0]
            weight_events[execution_date] = ({s: 1 / len(chosen) for s in chosen} if chosen else {})
        if not scored.empty:
            selected = scored[scored.symbol.isin(chosen)].copy()
            selected.insert(0, "signal_date", signal_date.date().isoformat())
            selected["execution_date"] = later[0].date().isoformat() if later.size and chosen else ""
            selected["proxy_weight"] = 1 / len(chosen) if chosen else np.nan
            selected["eligible_universe_size"] = len(scored)
            selected["portfolio_size"] = len(chosen)
            selection_rows.extend(selected.to_dict("records"))
        held = set(chosen)
    portfolio, weights = [], {}
    for date in sessions:
        day_returns = daily_returns.loc[date]
        valid = {s: w for s, w in weights.items() if s in day_returns.index and pd.notna(day_returns[s])}
        # Missing quote means unpriced exposure; hold its weight as zero-return
        # cash for this session and do not renormalize the observed names.
        ret = sum(valid[s] * float(day_returns[s]) for s in valid) if weights else np.nan
        # Closing rebalance happens after this session's close-to-close return.
        if date in weight_events:
            weights = weight_events[date].copy()
        portfolio.append({"date": date.date().isoformat(), "return": ret, "holdings_count": len(weights)})
    daily = pd.DataFrame(portfolio)
    first_active = daily["holdings_count"].gt(0).idxmax() if daily["holdings_count"].gt(0).any() else None
    daily["index_value"] = np.nan
    if first_active is not None:
        daily.loc[first_active, "index_value"] = 1000.0
        for i in range(first_active + 1, len(daily)):
            prev_value = daily.loc[i - 1, "index_value"]
            daily.loc[i, "index_value"] = prev_value * (1 + daily.loc[i, "return"]) if pd.notna(prev_value) and pd.notna(daily.loc[i, "return"]) else prev_value
    daily["drawdown"] = daily["index_value"] / daily["index_value"].cummax() - 1
    return pd.DataFrame(selection_rows), daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_DIR)
    parser.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    prices, turnover = load_prices(args.prices)
    snapshots = load_membership(args.membership)
    selections, daily = run_backtest(prices, turnover, snapshots)
    args.output.mkdir(parents=True, exist_ok=True)
    selections.to_csv(args.output / "rebalance_selections.csv", index=False)
    daily.to_csv(args.output / "daily_portfolio.csv", index=False)
    active = daily.dropna(subset=["index_value"])
    returns = active["return"].dropna()
    years = len(returns) / N_TRADING_DAYS
    cagr = (active["index_value"].iloc[-1] / active["index_value"].iloc[0]) ** (1 / years) - 1 if years else np.nan
    print(f"Price symbols: {prices.shape[1]}; sessions: {len(prices)} ({prices.index.min().date()} to {prices.index.max().date()})")
    print(f"Membership snapshots: {len(snapshots)} ({snapshots[0][0].date()} to {snapshots[-1][0].date()})")
    print(f"Rebalances: {selections.signal_date.nunique() if not selections.empty else 0}; CAGR proxy: {cagr:.2%}; max drawdown proxy: {daily.drawdown.min():.2%}")
    print(f"Wrote {args.output / 'rebalance_selections.csv'} and {args.output / 'daily_portfolio.csv'}")


if __name__ == "__main__":
    main()
