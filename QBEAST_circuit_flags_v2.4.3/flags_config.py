"""
QBEAST AI - configuration loader for circuit_liquidity_flags
=============================================================
Reads qbeast_flags_config.json and turns it into the parameter objects the
library uses. Every script in the bundle calls load_config(), so ONE file
controls paths, workers and every flag parameter.

Where the config is found (first match wins):
    1. the path you pass:            load_config("my_config.json")   /   --config my_config.json
    2. environment variable:         QBEAST_FLAGS_CONFIG=C:\\path\\to\\config.json
    3. qbeast_flags_config.json next to this file
    4. built-in defaults (identical to the shipped JSON)

Rules
    * Keys starting with "_" are comments and are ignored.
    * An unknown section or key is an error (catches typos such as "start_confrim_days").
    * Anything you leave out keeps its default.

Usage (Python):
    from flags_config import load_config
    cfg = load_config()                                   # or load_config("qbeast_flags_config.json")
    circ  = C.compute_circuit_hit_flag(df, mode="eod", circuit_params=cfg.circuit)
    stair = C.compute_staircase_flag(circ, cfg.staircase)
    chron = C.compute_chronic_illiquidity_flag(stair, cfg.chronic)
    mw    = C.compute_mwcb_flag(nifty, **cfg.mwcb_kwargs())
    table = C.build_universe_exclusion_table(chron, mw_by_date, **cfg.gate_kwargs())
    tr    = cfg.tracker("INDOTHAI")                       # CircuitLiquidityTracker with these parameters
    v2.4.3: the STEP staircase parameters live in the "staircase" section (step_*), so every existing call
    (compute_staircase_flag(circ, cfg.staircase), cfg.tracker(...)) picks them up unchanged.
    legacy_v242_config() = exactly v2.4.2; legacy_v241_config() = exactly v2.4.1.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

try:                                       # v2.4.3: works as plain files AND inside a package / wheel
    from . import circuit_liquidity_flags as C
except ImportError:
    import circuit_liquidity_flags as C

CONFIG_FILE_NAME = "qbeast_flags_config.json"
ENV_VAR = "QBEAST_FLAGS_CONFIG"


class ConfigError(ValueError):
    """Raised for a missing / unreadable config file or an invalid key or value."""


def _dataclass_defaults(cls) -> dict:
    obj = cls()
    out = {}
    for f in fields(cls):
        if f.name == "etf_overrides":          # v2.4.3: set through the "<section>_etf" sections instead
            continue
        v = getattr(obj, f.name)
        out[f.name] = list(v) if isinstance(v, tuple) else v
    return out


DEFAULTS: dict[str, dict[str, Any]] = {
    "paths": {
        "data_dir": r"E:\Downloads\Final_Data",
        "stocks_eod_subdir": "Final_Clean_Stocks_EOD_Data",
        "etfs_eod_subdir": None,                      # v2.4.3: e.g. "Final_ETF_EoD_Data" -> run_four_flags also does ETFs
        "indices_eod_subdir": "Final_Clean_Indices_EOD_Data",
        "stocks_intraday_subdir": "Final_Clean_Stocks_INTRADAY_Data",
        "indices_intraday_subdir": "Final_Clean_Indices_INTRADAY_Data",
        "mwcb_index_files": {"NIFTY50": "Nifty 50.csv", "SENSEX": "SENSEX.csv"},
        "output_dir": None,
    },
    "run": {
        "workers": 25,
        "check_every": 10,
        "mp_start_method": None,
    },
    "circuit": _dataclass_defaults(C.CircuitParams),
    "staircase": _dataclass_defaults(C.StaircaseParams),
    "chronic": _dataclass_defaults(C.ChronicParams),
    # v2.4.3: separate rules for ETFs -- only the keys you list here differ from the stock section above
    # (asset class from the files' product_class / asset_class column: ETF vs EQUITY)
    "circuit_etf": {},
    "staircase_etf": {},
    "chronic_etf": {},
    "mwcb": {
        "basis": "auto",
        "quarterly_basis_before": "2013-07-01",
        "use_high_low": True,
        "levels": [10, 15, 20],
        "reopen_auction_minutes": 15,
        "market_close": "15:30",
        "halt_rules": {str(k): [list(x) for x in v] for k, v in C.DEFAULT_MWCB_HALT_RULES.items()},
    },
    "gate": {
        "block_on_mwcb_day": True,
    },
}


# v2.4.2: the overrides that reproduce v2.4.1 exactly (volume quality, volume in the staircase tag / untag and
# missing-volume handling all off). Use: load_config("legacy_v241.json") with this content, or
# F.legacy_v241_config(). Tests check bit-identity with v2.4.1 on synthetic and real data.
LEGACY_V241: dict[str, dict[str, Any]] = {
    "circuit": {"volume_quality": False, "ca_jump_pct": None},
    "staircase": {"vol_avg_days": 1, "tag_vol_frac": None, "missing_volume_fallback": False,
                  "step_enabled": False, "zero_volume_as_missing": False,
                  "vol_reliability_min": None},              # v2.4.3: none of the 2.4.3 rules existed in 2.4.1
    "chronic": {"missing_volume_as_no_trade": True},
}

# v2.4.3: the overrides that reproduce v2.4.2 exactly (the new STEP staircase off). Use F.legacy_v242_config().
LEGACY_V242: dict[str, dict[str, Any]] = {
    "circuit": {"ca_jump_pct": None},
    "staircase": {"step_enabled": False, "zero_volume_as_missing": False, "vol_reliability_min": None},
}
# (direction-specific settings default to None = shared value, ladder_break_days 0, the *_etf sections empty and
#  chronic.min_traded_value None -- all identical to v2.4.2 unless you set them)


@dataclass
class FlagsConfig:
    """Everything the scripts need, built from the JSON file."""
    paths: dict
    run: dict
    circuit: C.CircuitParams
    staircase: C.StaircaseParams
    chronic: C.ChronicParams
    mwcb: dict
    gate: dict
    source: str = "built-in defaults"

    # ---------------- paths ----------------
    def data_dir(self, override: str | os.PathLike | None = None) -> Path:
        return Path(override) if override else Path(self.paths["data_dir"])

    def sub(self, key: str, data_dir: Path) -> Path:
        return data_dir / self.paths[key]

    def output_dir(self, data_dir: Path, default_name: str, override: str | None = None) -> Path:
        if override:
            return Path(override)
        base = self.paths.get("output_dir")
        return (Path(base) / default_name) if base else (data_dir / default_name)

    # ---------------- keyword bundles for the library ----------------
    def mwcb_kwargs(self, mode: str = "eod") -> dict:
        m = self.mwcb
        return {
            "mode": mode,
            "basis": m["basis"],
            "quarterly_basis_before": m["quarterly_basis_before"],
            "use_high_low": bool(m["use_high_low"]),
            "levels": tuple(int(x) for x in m["levels"]),
            "halt_rules": {int(k): [(str(a), (None if b is None else int(b))) for a, b in v]
                           for k, v in m["halt_rules"].items()},
            "reopen_auction_minutes": int(m["reopen_auction_minutes"]),
            "market_close": m["market_close"],
        }

    def gate_kwargs(self) -> dict:
        return {"block_on_mwcb_day": bool(self.gate["block_on_mwcb_day"])}

    def tracker(self, symbol: str, calendar=None, asset_class=None) -> C.CircuitLiquidityTracker:
        return C.CircuitLiquidityTracker(symbol, circuit_params=self.circuit, staircase_params=self.staircase,
                                         chronic_params=self.chronic, calendar=calendar, asset_class=asset_class)

    def summary(self) -> str:
        s = self.staircase
        return (f"config: {self.source} | S={s.start_confirm_days} E={s.end_confirm_days} "
                f"lock={self.circuit.lock_mode} tick={self.circuit.tick_size} "
                f"mwcb_basis={self.mwcb['basis']} block_on_mwcb_day={self.gate['block_on_mwcb_day']} | "
                f"volume: quality={self.circuit.volume_quality} zero_run_missing={self.circuit.zero_run_missing} "
                f"avg_days={s.vol_avg_days} tag<{s.tag_vol_frac} untag>={s.normal_vol_frac} "
                f"missing_fallback={s.missing_volume_fallback} "
                f"chronic_missing_as_no_trade={self.chronic.missing_volume_as_no_trade} | "
                f"step: enabled={s.step_enabled} stale_run={s.step_tag_stale_run} jump>={s.step_jump_pct}% "
                f"after>={s.step_min_stale} stale, {s.step_events_to_tag} in {s.step_window} "
                f"untag={s.step_end_confirm_days} stale_vol<{s.step_stale_vol_frac} | "
                f"zero_vol_as_missing={s.zero_volume_as_missing} vol_reliability<{s.vol_reliability_min} "
                f"ca_jump>{self.circuit.ca_jump_pct}% | ETF overrides: circuit {len(self.circuit.etf_overrides)}, "
                f"staircase {len(s.etf_overrides)}, chronic {len(self.chronic.etf_overrides)}")


# ------------------------------------------------------------------ loading
def _find(path: str | os.PathLike | None) -> Path | None:
    if path:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"config file not found: {p}")
        return p
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env)
        if not p.exists():
            raise ConfigError(f"{ENV_VAR} points to a missing file: {p}")
        return p
    p = Path(__file__).resolve().parent / CONFIG_FILE_NAME
    return p if p.exists() else None


def _merge(user: dict, source: str) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if not isinstance(user, dict):
        raise ConfigError(f"{source}: the top level must be a JSON object")
    for section, values in user.items():
        if section.startswith("_") or section == "version":
            continue
        if section not in cfg:
            raise ConfigError(f"{source}: unknown section '{section}'. Valid sections: {sorted(cfg)}")
        if not isinstance(values, dict):
            raise ConfigError(f"{source}: section '{section}' must be a JSON object")
        for key, val in values.items():
            if key.startswith("_"):
                continue
            valid = cfg[section[:-4]] if section.endswith("_etf") else cfg[section]   # v2.4.3: *_etf = base keys
            if key not in valid:
                raise ConfigError(f"{source}: unknown key '{section}.{key}'. Valid keys: {sorted(valid)}")
            cfg[section][key] = val
    return cfg


def _build(cls, values: dict, section: str, source: str, etf: dict | None = None):
    kw = {}
    for f in fields(cls):
        if f.name == "etf_overrides":
            continue
        v = values[f.name]
        if f.name == "band_candidates":
            v = tuple(float(x) for x in v)
        kw[f.name] = v
    if etf:                                    # v2.4.3: ETF rule set = the listed keys of "<section>_etf"
        kw["etf_overrides"] = tuple((k, tuple(float(x) for x in v) if k == "band_candidates" else v)
                                    for k, v in sorted(etf.items()))
    try:
        obj = cls(**kw)
        obj.validate(f"{source} [{section}]")
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{source}: invalid value in section '{section}': {exc}") from exc
    return obj


def load_config(path: str | os.PathLike | None = None) -> FlagsConfig:
    """Load the config (see module docstring for the search order)."""
    p = _find(path)
    if p is None:
        cfg, source = copy.deepcopy(DEFAULTS), "built-in defaults"
    else:
        try:
            with open(p, encoding="utf-8") as fh:
                user = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{p}: not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from exc
        source = str(p)
        cfg = _merge(user, source)
    m = cfg["mwcb"]
    if m["basis"] not in ("auto", "prev_close", "quarterly"):
        raise ConfigError(f"{source}: mwcb.basis must be 'auto', 'prev_close' or 'quarterly'")
    if not isinstance(cfg["run"]["workers"], int) or cfg["run"]["workers"] < 1:
        raise ConfigError(f"{source}: run.workers must be a positive integer")
    if cfg["run"]["mp_start_method"] not in (None, "spawn", "fork", "forkserver"):
        raise ConfigError(f"{source}: run.mp_start_method must be null, 'spawn', 'fork' or 'forkserver'")
    return FlagsConfig(
        paths=cfg["paths"], run=cfg["run"],
        circuit=_build(C.CircuitParams, cfg["circuit"], "circuit", source, cfg["circuit_etf"]),
        staircase=_build(C.StaircaseParams, cfg["staircase"], "staircase", source, cfg["staircase_etf"]),
        chronic=_build(C.ChronicParams, cfg["chronic"], "chronic", source, cfg["chronic_etf"]),
        mwcb=m, gate=cfg["gate"], source=source,
    )


def write_default_config(path: str | os.PathLike) -> Path:
    """Write the built-in defaults to a JSON file (a starting point for your own)."""
    p = Path(path)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"version": C.__version__, **DEFAULTS}, fh, indent=2)
    return p


def mp_context(cfg: FlagsConfig):
    """multiprocessing context for ProcessPoolExecutor (None = platform default)."""
    import multiprocessing as mp
    m = cfg.run.get("mp_start_method")
    return mp.get_context(m) if m else None


def _with_overrides(path, overrides: dict, label: str) -> FlagsConfig:
    cfg = load_config(path)
    out = copy.deepcopy(cfg)
    for section, kv in overrides.items():
        obj = getattr(out, section)
        merged = {**{f.name: getattr(obj, f.name) for f in fields(obj)}, **kv}
        # v2.4.3: the legacy presets also neutralise the same keys inside the ETF rule set
        merged["etf_overrides"] = tuple((k, v) for k, v in obj.etf_overrides if k not in kv)
        setattr(out, section, type(obj)(**merged))
    out.source = f"{cfg.source} + {label}"
    return out


def legacy_v241_config(path: str | os.PathLike | None = None) -> FlagsConfig:
    """v2.4.2: the config at `path` (or the default search) with LEGACY_V241 applied = v2.4.1 results."""
    return _with_overrides(path, LEGACY_V241, "LEGACY_V241")


def legacy_v242_config(path: str | os.PathLike | None = None) -> FlagsConfig:
    """v2.4.3: the config at `path` (or the default search) with LEGACY_V242 applied = v2.4.2 results
    (the STEP staircase switched off)."""
    return _with_overrides(path, LEGACY_V242, "LEGACY_V242")
