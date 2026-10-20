"""Run QBEAST v2.4.4, then all four costed, QBEAST-gated strategy backtests."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_FLAGS = ROOT / "QBEAST_RUN_NIFTY500_v2.4.4" / "output"


def run_step(label: str, command: list[str]) -> None:
    print(f"\n=== {label} ===", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def validate_flag_coverage(flags_dir: Path) -> int:
    strategy_dirs = (
        ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY500_EoD_Data",
        ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY100_EoD_Data",
        ROOT / "DATASET" / "Final_without_survivorship_data" / "Final_NIFTY200_EoD_Data",
    )
    non_stocks = {"NIFTY50", "NIFTY 50", "NIFTY100", "NIFTY 100", "NIFTY200", "NIFTY 200",
                  "NIFTY500", "NIFTY 500"}
    expected = set()
    for folder in strategy_dirs:
        if not folder.is_dir():
            raise FileNotFoundError(f"Strategy price folder not found: {folder}")
        expected.update(p.stem.strip().upper() for p in folder.glob("*.csv")
                        if p.stem.strip().upper() not in non_stocks)
    actual = {p.stem.strip().upper() for p in flags_dir.glob("*.csv")}
    missing = sorted(expected - actual)
    if missing:
        raise FileNotFoundError(f"QBEAST output missing flags for {len(missing)} strategy symbols: {missing[:20]}")
    extra = sorted(actual - expected)
    if extra:
        raise ValueError(f"QBEAST stock output contains non-strategy symbols: {extra[:20]}")
    print(f"QBEAST symbol coverage: {len(expected)}/{len(expected)} strategy symbols", flush=True)
    return len(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flags-output", type=Path, default=DEFAULT_FLAGS,
                        help="Folder for QBEAST per-symbol flags; consumed by all strategy backtests.")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--check-every", type=int, default=10,
                        help="Causal/parity self-check sample interval; 1 checks every stock.")
    parser.add_argument("--skip-qbeast", action="store_true",
                        help="Reuse existing flags at --flags-output; fail if output is incomplete.")
    args = parser.parse_args()
    flags_dir = args.flags_output if args.flags_output.is_absolute() else ROOT / args.flags_output
    flags_dir = flags_dir.resolve()

    if args.workers < 1 or args.check_every < 0:
        parser.error("workers must be positive and check-every cannot be negative")

    stock_dir = (ROOT / "DATASET" / "Final_without_survivorship_data"
                 / "Final_NIFTY500_EoD_Data")
    stock_index_files = [p.name for p in stock_dir.glob("*.csv")
                         if p.stem.strip().upper() in {
                             "NIFTY50", "NIFTY 50", "NIFTY100", "NIFTY 100",
                             "NIFTY200", "NIFTY 200", "NIFTY500", "NIFTY 500",
                         }]
    with (ROOT / "QBEAST_pipeline_config.json").open(encoding="utf-8") as f:
        qbeast_config = json.load(f)
    index_dir = (ROOT / qbeast_config["paths"]["data_dir"]
                 / qbeast_config["paths"]["indices_eod_subdir"])
    mwcb_index_files = list(qbeast_config["paths"]["mwcb_index_files"].values())
    missing_indices = [name for name in mwcb_index_files if not (index_dir / name).is_file()]
    if missing_indices:
        raise FileNotFoundError(f"Configured QBEAST MWCB index files missing: {missing_indices}")
    if not args.skip_qbeast:
        exclude_args = ["--exclude-stock-files", *sorted(stock_index_files)] if stock_index_files else []
        include_index_args = ["--include-index-files", *mwcb_index_files]
        run_step("QBEAST v2.4.4 EOD flag generation", [
            sys.executable, str(ROOT / "QBEAST_circuit_flags_v2.4.4" / "run_four_flags.py"),
            "--config", str(ROOT / "QBEAST_pipeline_config.json"),
            "--out", str(flags_dir), "--workers", str(args.workers),
            "--check-every", str(args.check_every),
            *exclude_args,
            *include_index_args,
        ])

    qbeast_stock_flags = flags_dir / "eod_stocks"
    if not qbeast_stock_flags.is_dir() or not any(qbeast_stock_flags.glob("*.csv")):
        raise FileNotFoundError(f"QBEAST EOD output is missing or empty: {flags_dir}")
    for input_name in stock_index_files:
        stale_flag = qbeast_stock_flags / f"{Path(input_name).stem}.csv"
        if stale_flag.is_file():
            stale_flag.unlink()
            print(f"Removed stale non-stock QBEAST flag: {stale_flag.name}", flush=True)
    qbeast_index_flags = flags_dir / "eod_indices"
    allowed_index_names = {Path(name).name.casefold() for name in mwcb_index_files}
    if qbeast_index_flags.is_dir():
        for stale_index in qbeast_index_flags.glob("*.csv"):
            if stale_index.name.casefold() not in allowed_index_names:
                stale_index.unlink()
                print(f"Removed stale non-MWCB index output: {stale_index.name}", flush=True)
    validate_flag_coverage(qbeast_stock_flags)

    gate_arg = ["--qbeast-flags-dir", str(qbeast_stock_flags)]
    run_step("CODE1 signal generation", [sys.executable, str(ROOT / "STRATEGY" / "CODE_1.PY")])
    run_step("CODE1 costed backtest with QBEAST gate", [
        sys.executable, str(ROOT / "TESTER" / "backtester.py"), *gate_arg,
    ])
    for script, label in (("CODE_2.py", "CODE2"), ("CODE_3.py", "CODE3"), ("CODE_4.py", "CODE4")):
        run_step(f"{label} costed backtest with QBEAST gate", [
            sys.executable, str(ROOT / "STRATEGY" / script), *gate_arg,
        ])

    print(f"\nPipeline complete. QBEAST flags: {flags_dir}", flush=True)


if __name__ == "__main__":
    main()
