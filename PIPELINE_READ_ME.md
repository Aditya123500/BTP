# QBEAST Pipeline Submission Guide

This guide covers the files, run steps, and validation evidence needed to submit the integrated QBEAST and strategy pipeline. QBEAST flags are generated first and consumed by all four costed strategy backtests. Rule definitions are documented in the bundle's [README](QBEAST_circuit_flags_v2.4.4/README.md) and [specification](QBEAST_circuit_flags_v2.4.4/QBEAST_AI_Circuit_Liquidity_Flags_SPEC_v2.md).

## Reproducible run steps

1. **Prepare and inventory the inputs.** Use daily stock EOD CSVs with date, OHLC, and volume; index EOD files for market-wide circuit breaker detection; and ETF files if the submission evaluates ETFs. Intraday files are needed only for intraday results. Record the universe definition, symbol/file count, coverage dates, data adjustments, missing files, and index sources.
2. **Set the run configuration.** The integrated runner uses root `QBEAST_pipeline_config.json`. Confirm its data paths, stock/ETF folders, market index inputs, worker count, causality-check sampling, and output directory. Include this exact config with the submission.
3. **Record the environment.** Record Python, pandas, NumPy, and Matplotlib versions and the command lines used. Install integrated pipeline dependencies from root `requirements.txt`; the standalone QBEAST bundle has its own `requirements.txt`.
4. **Verify the bundle.** Run `python verify_install.py`; require `RESULT: 62/62 checks passed`. Run `python test_circuit_liquidity_flags.py`; current suite reports `63/63 passed`. When real input data is available, also run `python verify_install.py --real-data "<data-folder>"` and record the sample size and any skipped checks.
5. **Run the integrated pipeline.** From the project root, run `python run_submission_pipeline.py`. It generates QBEAST EOD flags, then runs CODE1–4 using those flags. Use `--skip-qbeast` only when reusing a complete existing QBEAST output folder. A missing symbol file stops a strategy run; a missing dated flag fails closed and blocks orders for that symbol on that decision date. In the current run, two CODE3 selected symbol/date pairs lacked a QBEAST row and were blocked as `FLAG_DATA_MISSING`.
6. **Review the outputs.** Keep QBEAST summaries/reports and per-symbol flags alongside all four costed strategy outputs, summaries, selections, daily/monthly portfolios, and equity plots. Review the QBEAST version/path and blocked-order, blocked-holding, and residual-holding counts recorded by each strategy.
7. **Archive the run.** Keep the exact bundle version, configuration, commands, environment details, input manifest, logs, validation results, outputs, and a limitations statement together. Report flag-pipeline counts separately from strategy returns or P&L.

## Submission contents

- `QBEAST_circuit_flags_v2.4.4.zip` and the extracted versioned source bundle. Include the library, config, loaders, runner scripts, tests, verifier, README, specification, upgrade notes, and guide PDF.
- Integration code: `run_submission_pipeline.py`, `QBEAST_pipeline_config.json`, `TESTER/qbeast_gate.py`, `TESTER/backtester.py`, and `STRATEGY/CODE_1.PY` through `CODE_4.py`.
- Root `requirements.txt` for the integrated strategy pipeline; QBEAST bundle `requirements.txt` for standalone flag runs.
- Exact configuration and commands used, including worker and causal-check settings. Private paths may be redacted if folder roles and filenames remain clear.
- Input manifest: universe and survivorship treatment, symbols/files included, date coverage, fields and adjustment method, index files used, and all exclusions or errors.
- Environment and validation record: Python/pandas/NumPy versions, unit-check result, built-in verifier result, real-data smoke-check result, self-check sample size, skipped checks, and any failures.
- Generated results: `four_flags_summary.csv`, `four_flags_report.txt`, combined daily flags, per-symbol stock/ETF/index files, and circuit/STEP episode files where generated.
- Strategy results: CODE1–4 costed daily/monthly outputs, summary metrics, equity plots, selections, and recorded QBEAST gate metadata.
- A concise results report: total symbols and symbol-days, successful/failed files, flag-day and episode counts, runtime, coverage, validation status, strategy performance, and limitations.

Do not claim a complete ETF evaluation unless ETF history was processed. Do not claim SENSEX-based market-breaker coverage unless SENSEX data was used. Do not include raw licensed/vendor data in a public submission unless redistribution is allowed; provide an input manifest and reproducible data instructions instead.

## Current real-data run in this workspace

The detailed report is [`RUN_RESULTS_NIFTY500_2026-10-20.md`](QBEAST_circuit_flags_v2.4.4/RUN_RESULTS_NIFTY500_2026-10-20.md). It records 495 no-survivorship NIFTY 500 equity files and 1,857,499 symbol-days from 2000-01-03 to 2026-08-06. The mixed-in `NIFTY500.csv` index file was excluded; all 495 equity files completed successfully. The latest run reported 24,809 blocked equity-days (1.34%), 83 circuit-staircase episodes, and 203 STEP episodes. Fifty sampled real-data no-repaint/parity checks passed; 445 equities were not sampled with `check_every=10`. NIFTY 50 produced 10 market-wide circuit-breaker trigger dates. No ETF EOD history, matching intraday data, or SENSEX file was supplied, so this run provides no real-history ETF or intraday result and uses NIFTY 50 alone for MWCB. Volume is used as supplied because no separate point-in-time split-adjusted-volume field or corporate-action master is present; volume-based flags around share-count actions remain provisional. The integrated pipeline uses these stock flags in CODE1–4; flag-pipeline counts remain separate from strategy returns and P&L. Gated results and blocked-decision counts are summarized in the root [README](README.md); detailed metrics and gate metadata are in `TESTER/output` and the four `STRATEGY/output_*` folders.

Verified environment: Python 3.14.5, pandas 3.0.3, NumPy 2.4.5, Matplotlib 3.11.1. The QBEAST bundle verifier passed 62/62 checks and its direct unit suite passed 63/63 checks in this run.

For command options, input schemas, output descriptions, and technical limits, see the bundle [README](QBEAST_circuit_flags_v2.4.4/README.md). For the release's implementation and validation history, see [UPGRADE_v2.4.4.md](QBEAST_circuit_flags_v2.4.4/UPGRADE_v2.4.4.md).
