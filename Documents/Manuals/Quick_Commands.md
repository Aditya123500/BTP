# Quick Commands

```powershell
cd C:\BTP
python -m pip install -r requirements.txt
python run_submission_pipeline.py
```

Run CODE1 alone, after flags are generated:

```powershell
python STRATEGY/CODE_1.PY
python TESTER/backtester.py
```

Run QBEAST checks:

```powershell
python QBEAST_circuit_flags_v2.4.4/verify_install.py
python QBEAST_circuit_flags_v2.4.4/test_circuit_liquidity_flags.py
```

CODE1 results: `TESTER/output/performance_summary.csv`, `backtest_daily.csv`, and `equity_plot.png`.
