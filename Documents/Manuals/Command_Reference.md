# Command Reference

Run from the project root. Use `--help` for current descriptions.

| Command | Main options |
|---|---|
| `python run_submission_pipeline.py` | `--flags-output PATH`, `--workers N`, `--check-every N`, `--skip-qbeast`. |
| `python STRATEGY/CODE_1.PY` | `--prices`, `--membership`, `--output`. |
| `python STRATEGY/CODE_2.py` | `--prices`, `--membership`, `--output`, `--benchmark`, `--qbeast-flags-dir`, cost options. |
| `python STRATEGY/CODE_3.py` | Date range, price directory, membership, output, flags directory, cost options. |
| `python STRATEGY/CODE_4.py` | Date range, price directory, benchmark, membership, output, flags directory, costs, portfolio size, minimum volatility observations. |
| `python TESTER/backtester.py` | `--selections`, `--prices`, `--benchmark`, `--output`, `--qbeast-flags-dir`, cost options. |
| `python QBEAST_circuit_flags_v2.4.4/run_four_flags.py` | Config/data/output paths, workers, check interval, intraday, file include/exclude options. |

Cost options are `--slippage-bps` and `--transaction-cost-bps` per side. Pipeline defaults: flags in `QBEAST_RUN_NIFTY500_v2.4.4/output`, 2 workers, sample every 10 stocks. `--check-every 1` checks every stock; `0` disables sampling. `--skip-qbeast` reuses existing flags.
