"""Strict loader and portfolio overlay for precomputed QBEAST EOD flags."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


DEFAULT_FLAGS_DIR = Path(__file__).resolve().parents[1] / "QBEAST_RUN_NIFTY500_v2.4.4" / "output" / "eod_stocks"


class QbeastFlagStore:
    """Load per-symbol TRADE_BLOCKED states; missing dates fail closed."""

    def __init__(self, flags_dir: Path = DEFAULT_FLAGS_DIR):
        self.flags_dir = Path(flags_dir)
        if not self.flags_dir.is_dir():
            raise FileNotFoundError(f"QBEAST EOD flags folder not found: {self.flags_dir}")
        self._cache: dict[str, pd.Series] = {}

    def _series(self, symbol: str) -> pd.Series:
        key = str(symbol).strip().upper()
        if key not in self._cache:
            path = self.flags_dir / f"{key}.csv"
            if not path.is_file():
                raise FileNotFoundError(f"QBEAST flags missing for {key}: {path}")
            frame = pd.read_csv(path, usecols=["date", "TRADE_BLOCKED"])
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
            if frame.date.isna().any() or frame.date.duplicated().any():
                raise ValueError(f"Invalid or duplicate dates in QBEAST flags: {path}")
            state = frame["TRADE_BLOCKED"].fillna("").astype(str).str.strip().str.upper()
            if state.eq("").any():
                raise ValueError(f"Blank TRADE_BLOCKED values in QBEAST flags: {path}")
            self._cache[key] = pd.Series(state.to_numpy(), index=frame.date, name=key).sort_index()
        return self._cache[key]

    def reason(self, symbol: str, date: pd.Timestamp) -> str:
        day = pd.Timestamp(date).normalize()
        series = self._series(symbol)
        if day not in series.index:
            # Never infer tradability when QBEAST did not emit a row for the
            # decision date (for example, a special session absent from that
            # symbol's input history). Preserve an existing holding; suppress
            # every order for this symbol until a dated flag is available.
            return "FLAG_DATA_MISSING"
        state = str(series.at[day])
        return "" if state == "NO" else state

    def blocked_symbols(self, symbols, date: pd.Timestamp) -> dict[str, str]:
        reasons = {str(s).upper(): self.reason(str(s), date) for s in symbols}
        return {s: reason for s, reason in reasons.items() if reason}


def gated_targets(current_weights: dict[str, float], proposed_weights: dict[str, float],
                  blocked: dict[str, str]) -> dict[str, float]:
    """Freeze blocked holdings; suppress blocked buys; scale buys into free capital."""
    frozen = {s: float(w) for s, w in current_weights.items()
              if s in blocked and float(w) > 0}
    capacity = max(0.0, 1.0 - sum(frozen.values()))
    desired = {s: float(w) for s, w in proposed_weights.items()
               if s not in blocked and float(w) > 0}
    desired_total = sum(desired.values())
    scale = min(1.0, capacity / desired_total) if desired_total > 0 else 0.0
    return {**frozen, **{s: w * scale for s, w in desired.items()}}

