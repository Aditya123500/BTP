# Operational Manual

## Before running

From `C:\BTP`, install root dependencies with `python -m pip install -r requirements.txt`. Check the configured files exist:

- Stock and index price folders under `DATASET/Final_without_survivorship_data/`.
- Nifty 50 EOD file for QBEAST.
- Nifty 500/100/200 membership CSVs under `DATASET/Survivorship_Bias/`.
- `TRI/NIFTY_500_TRI.csv`.

CSV fields vary by strategy. Required columns are listed in [Technical Specification](Technical_Specification.md) and each script's loader.

## Run

```powershell
cd C:\BTP
python run_submission_pipeline.py
```

This generates flags and runs all four strategies. CODE1 results are in `TESTER/output/`. To run CODE1 alone, first ensure QBEAST flags are current:

```powershell
python STRATEGY/CODE_1.PY
python TESTER/backtester.py
```

## Check and archive

Confirm all stages finish, then inspect each strategy's summary and output files. Save the command, config, input coverage, run log, and outputs together. Do not reuse flags from different data/config without checking coverage.

For QBEAST validation, run `python QBEAST_circuit_flags_v2.4.4/verify_install.py` and `python QBEAST_circuit_flags_v2.4.4/test_circuit_liquidity_flags.py`. The recorded results are 62/62 and 63/63; rerun to validate a new environment.

If a run stops, check the missing path or CSV columns named in the error. Missing symbol flag files stop the run; missing dated flags block that trade. Preserve console output when diagnosing failures.
