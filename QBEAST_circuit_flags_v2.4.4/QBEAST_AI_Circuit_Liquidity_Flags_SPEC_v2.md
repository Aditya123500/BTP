# QBEAST AI — Circuit & Liquidity Risk Flags Specification

**Version:** 2.1 (supersedes v2.0 and v1.0)
**Date:** 2026-09-26
**Status:** Implemented in `circuit_liquidity_flags.py` v2.4.1 (27 unit tests + 32-check `verify_install.py`; full-universe run 1,272/1,272 self-checks OK). Parameters: `qbeast_flags_config.json` (see README.md section 5). Any tagged staircase, CLIMBING or FALLING, is barred from buying and selling.
**Scope:** Universe gate upstream of Wing A — EOD and INTRADAY, Backtest, Paper and Live

---

## 0. What changed from v1 (summary)

| Area | v1 | v2 |
|---|---|---|
| Causality | Staircase start back-marked S−1 days; end back-dated | **Strictly causal.** Row t uses rows ≤ t only. No back-marking, no back-dating |
| Staircase end | Break counter, end when count *exceeds* E | End after **E consecutive NORMAL days** (not locked, real volume). Grace days stay tagged |
| Direction flip | Hard reset to a new BUILDING run (stock became tradable) | **Stays tagged**, new `staircase_event_id` |
| Thin volume | Required for a ladder day; baseline starved after ~15 circuit days | Optional (`vol_frac=None` default); baseline = last N **clean observations**, reset on vendor/exchange change |
| Lock test | Strict O=H=L=C only | `close_locked` default (close = high for upper / low for lower); `strict` available |
| Band source | Required columns | Given columns **or causal inference** (tick-aware, per exchange) |
| Tick rounding | Relative tol 1e-4 (missed floored limits) | Slack = tick / prev_close + tol; penny-stock `tick_degenerate` guard |
| MWCB | Close vs prev close only | Day high/low; prev-close or quarterly basis; intraday halt + reopen-auction windows; one row per date |
| New | — | Chronic illiquidity flag; exclusion table; fill-feasibility columns; streaming tracker |

### 0.1 v2.1 changes (after the first full-universe run)

| Finding in the full run | Fix |
|---|---|
| Back-adjusted old history (AARTIIND 2000–03 at ~Rs 1.5) turned a 0.05 tick into a ~3% match window -> false circuits | Off the 0.05 grid (adjusted or fine-tick prices) the slack is capped at max(1 fine tick, 0.5%). Raw on-grid prices keep the full 1-tick slack |
| Intraday "freezes" on large caps with no band history (360ONE, ABB, 3MINDIA...) | Intraday matches only the session band known from EOD inference; guessing among 2/5/10/20% is opt-in (`intraday_candidate_mode`) |
| Stale band belief intraday | A bar is pinned at a band only if the session has not already traded beyond that band |
| Vendor switches (Kite/Dhan/Upstox) on the same exchange reset the volume baseline and delayed untagging | Baseline resets on exchange change only (same-exchange vendor switches: median volume ratio ~1.0) |

---

## 1. Purpose

Unchanged from v1: identify symbols and sessions whose printed prices were not actually accessible (circuit-locked, staircase ladders, market-wide halts, chronic illiquidity), so backtest–live parity is not destroyed by fills that could never happen.

---

## 2. Governing rules

### 2.1 No Forward Bias and Causal Iterative Flow

1. At bar t (1-min/tick bar in INTRADAY, daily bar in EOD) only data ≤ t is visible. Predictions made at bar t may be used.
2. Every flag on row t is "the state as of the close of bar t". A strategy decides at t using row t; the order fills at t+1's open.
3. Batch, expanding-window and streaming evaluation give identical values. Two automated checks enforce this, on synthetic and on real data:
   - **Truncation / no-repaint:** cutting the data at any t never changes a row ≤ t.
   - **Streaming parity:** feeding bars one at a time gives the same output as a full-history batch call.
4. The only look at bar t+1 is by the **execution simulator**, to decide whether a fill was physically possible (for example, the open was locked at the upper band). That is exactly what the exchange does to a live order. It is never a strategy input.

### 2.2 Trading rule for tagged symbols (owner decision, 2026-09-26)

While a symbol is tagged (staircase, chronic illiquid, or inside an MWCB halt):

- no new buy
- no new sell
- **no exit** of an existing position
- MtM continues as usual, whether in profit or loss

Trading resumes only when the symbol is untagged. Untagging is causal, never retroactive.

### 2.3 Exchange preference

NSE is preferred; BSE (or MCX/NCDEX for instruments listed only there) is used when NSE is not available. Flags are computed on the series as stitched; band inference state is kept per exchange. A bar right after an exchange switch is `data_unknown`, because its prev_close came from the other exchange.

MCX/NCDEX commodity daily price limits work differently (limit expansion after a cooling period) and are **out of scope** for v2.

---

## 3. Flag definitions

### 3.1 Price Band (attribute) — `compute_price_band_flag`

- Point-in-time `upper_band_pct`, `lower_band_pct` supplied by the caller: 0–100, `inf` = no band (F&O), NaN = unknown.
- Outputs:
  - `band_known`
  - `band_asymmetric`: only when both sides are known.
  - `band_tightened` / `band_widened`: compared with the last **known** value, so unknown rows are skipped. inf → 20 counts as tightening.
- Asymmetric GSM bands and upper = 0 ("no upward movement") are supported.

**Band inference (when no point-in-time band data exists — the case for Final_Data today).** Per symbol and exchange, causally:

- A locked day whose move matches a candidate band b ∈ {2, 5, 10, 20} within the slack sets the believed band to b.
- A later day ranging beyond b + slack resets the belief to unknown.
- The band applied to session t is the belief formed from sessions ≤ t−1, except that a locked day at t may reveal a *tighter* band on its own close (this uses bar-t data at bar-t close, so it is not look-ahead).
- Output `band_est_next` is the band believed for the next session. This is what intraday uses.

### 3.2 Upper/Lower Circuit — `compute_circuit_hit_flag`

- **Slack (tick-aware).** `slack% = tick_size / prev_close × 100 + tol × 100`, with tick_size = 0.05 by default. NSE floors limits to the tick, and Final_Data confirms it: GTLINFRA frozen days at +2.6 / 2.9 / 3.4 % and INDOTHAI at +4.76 % are all 5 % bands floored to ₹0.05.
- **Lock mode.**
  - `close_locked` (default): close = high for upper, close = low for lower.
  - `strict`: O = H = L = C.
  - Evidence for the default: INDOTHAI 20-Dec-2021 → 10-Jan-2022 had about 15 consecutive +5 % closes at the high, but only 11 were strict, so strict splits the ladder.
- **`tick_degenerate`.** When the band spans fewer than `min_band_ticks` (2) ticks — for example a ₹1.05 stock, where 5 % = 1 tick — every one-tick close at the high "hits" the band. Such hits are reported, but they do not feed Staircase or Chronic.
  - The effective tick is inferred causally: ₹0.01 once recent closes leave the ₹0.05 grid.
  - Evidence: GTLINFRA at ₹0.6–2 traded 10–150 M shares/day while "hitting" 5 % every day.
- **EOD columns:**
  - `frozen`, `band_hit_dir` (close at the boundary), `circuit_locked_dir` (hit and locked), `upside_locked`, `single_price` (frozen but not at a band)
  - `open_at_upper` / `open_at_lower` (for the simulator)
  - `band_breach`, `data_unknown` (gap-filled row or exchange switch)
  - `band_source`, `band_est_next`, `effective_tick`
- **INTRADAY columns.** Per bar: `pinned`, and `pinned_run_len`, which **resets every session**.
  - `intraday_freeze` = run ≥ `intraday_min_pinned_bars` (3). The thin-volume requirement is optional.
  - `locked_since_open_dir`.
  - The session band comes from the given columns or from EOD inference over **completed** sessions only.
  - Session prev_close is the EOD close of the previous day when merged in (recommended); otherwise the previous session's last bar close.

### 3.3 MWCB — `compute_mwcb_flag`, `aggregate_mwcb_by_date`, `apply_mwcb_windows`

- **Trigger.** Use the index's **intraday extreme vs previous close** (day high/low in EOD, bar high/low in INTRADAY). The close alone misses real halts: 13-Mar-2020 hit −10.8 % at the low but closed +3.8 %.
- **Threshold basis.** Points = pct × reference close. `auto` = the previous calendar quarter's last close before `quarterly_basis_before` (default 2013-07-01), and the previous day's close after it. The NIFTY history supports this:
  - 17-Oct-2007 (−9.9 % vs prev close) and 18-May-2009 reaching 20 % are reproduced only on the quarterly basis.
  - 13-Mar-2020 is reproduced only on the prev-close basis.
  - **The exact cut-over date must be verified against the SEBI circular.**
- **Detected days (NIFTY 50, 2000–2026).**

  | Date | Level | Event |
  |---|---|---|
  | 2004-05-17 | 15 % | |
  | 2006-05-22 | 10 % | |
  | 2007-10-17 | 10 % | |
  | 2008-01-21 | 10 % | ⚠ verify |
  | 2008-01-22 | 10 % | |
  | 2008-10-24 | 10 % | ⚠ verify |
  | 2009-05-18 | 20 % up | |
  | 2012-10-05 | 15 % | freak-trade day |
  | 2020-03-13 | 10 % | |
  | 2020-03-23 | 10 % | |

  **v1's "only 10 % trigger was 23-Mar-2020" was wrong.**
- **Halt table.** Current SEBI regime, configurable via `halt_rules`:

  | Move | Before 13:00 | 13:00–14:00 | 14:00–14:30 | After 14:30 |
  |---|---|---|---|---|
  | 10 % | 45 min | 15 min | 15 min | no halt |
  | 15 % | 1 h 45 min | 45 min | rest of day | rest of day |
  | 20 % | rest of day | rest of day | rest of day | rest of day |

  Each halt is followed by a `reopen_auction_minutes` (15) call-auction window. Each level fires at most once per day. Pre-2013 halt durations differed; pass `halt_rules` for older intraday data.
- **Market-wide state.** One row per date or timestamp via `aggregate_mwcb_by_date`: the maximum level across NIFTY and SENSEX, so there is no row duplication. SENSEX is not in Final_Data, so NIFTY alone is used as a stand-in.
- **Stress testing.** Synthetic stress injection is still required: almost any backtest window contains no MWCB (see v1 §3.3).

### 3.4 Staircase — `compute_staircase_flag` (causal)

**Day classes** (per EOD session):

| Class | Condition |
|---|---|
| LADDER(dir) | `circuit_locked_dir` set, not `tick_degenerate`, not upside-locked, not unknown (plus thin volume only if `vol_frac` is set) |
| NORMAL | not locked, not single-price, volume ≥ `normal_vol_frac` (0.5) × baseline — "volumes are there". **v2.4.2:** "volume" = the trailing `vol_avg_days` (3) average of REAL volume; if the day's volume is MISSING (or no baseline yet), OHLC only (`missing_volume_fallback`), with a warning |
| UNKNOWN | gap-filled row, exchange switch, missing data → **holds the state unchanged** |
| OTHER | everything else (thin day, single-price day, …) |

The volume baseline is the median of the last `volume_lookback` (20) clean **observations**. It excludes circuit days, restarts on an exchange change (NSE and BSE volumes differ in scale; same-exchange vendor switches do not, per the full run), and uses only sessions ≤ t−1.

**State machine** (tagged = CONFIRMED or COOLING):

```
DORMANT   --LADDER-->               BUILDING(run=1)
BUILDING  --same-dir LADDER-->      run+1; at run = S -> CONFIRMED (tag from this close)
BUILDING  --opposite LADDER-->      BUILDING(new dir, run=1)
BUILDING  --NORMAL/OTHER-->         DORMANT
CONFIRMED/COOLING --LADDER same-->  CONFIRMED, run+1, normal=0
CONFIRMED/COOLING --LADDER flip-->  CONFIRMED, new dir, run=1, new event id (stays tagged)
CONFIRMED/COOLING --NORMAL-->       COOLING, normal+1; normal = E -> DORMANT (untag from this close)
CONFIRMED/COOLING --OTHER-->        normal = 0 (stays tagged)
any       --UNKNOWN-->              no change
```

Defaults: S = 5, E = 3.

**v2.4.2 volume gate on the tag.** At run ≥ S the tag is confirmed only if the trailing `vol_avg_days` (3) average of REAL volume < `tag_vol_frac` (0.5) × baseline; otherwise the state stays BUILDING (`staircase_vol_warn = LADDER_HIGH_VOL`) and the test is repeated on every further ladder day. If the day's volume is MISSING (or there is no baseline yet), the tag is confirmed on OHLC alone (`TAGGED_NO_VOL`). Untag on OHLC alone is marked `NORMAL_NO_VOL` / `UNTAGGED_NO_VOL`.

**v2.4.2 volume_status** (circuit step, causal): REAL (> 0); ZERO (0 and O = H = L = C = previous close: no trade); MISSING (blank / negative / infinite; 0 while the price moved; or the `zero_run_missing`-th (20) consecutive zero/blank day so far); GAP (gap-filled).

**INTRADAY.** Every bar inherits the tag as of the previous session's close. **Early block:** if yesterday closed at run = S−1 and every bar today so far is pinned at the band in that direction (≥ 3 bars), the bar is provisionally tagged. Untagging never happens intraday.

**Output:** `day_class`, `staircase_state`, `staircase`, `staircase_dir`, `ladder_run_len`, `normal_day_count`, `staircase_event_id`, `staircase_early_block_dir`, `vol_baseline`, `thin_vol`, `ladder_day`; v2.4.2 adds `vol_avg_real`, `staircase_vol_basis` (VOLUME / OHLC), `staircase_vol_warn`.

### 3.5 Chronic illiquidity (new) — `compute_chronic_illiquidity_flag`

Trailing window of 60 trading sessions (minimum 20) with hysteresis:

| Metric | Tag when ≥ | Untag when all < |
|---|---|---|
| single-price days | 20 % | 10 % |
| no-trade days (volume 0, gap-filled, or a calendar session missing from the symbol's rows; v2.4.2: a MISSING `volume_status` is not a no-trade day unless `missing_volume_as_no_trade`) | 20 % | 10 % |
| circuit-locked days (non-degenerate) | 30 % | 15 % |

The calendar is the NIFTY trading dates. Evidence: INDOTHAI printed 201 single-price 0 % days in 2012–2016.

---

### 3.6 STEP staircase (v2.4.3; calibrated in v2.4.4) — inside `compute_staircase_flag` / the tracker (causal)
An illiquid "flat, then jump" pattern, for stocks and ETFs. No exchange band is needed: ETFs never stay at a band, so 3.4 cannot fire on them.

- **STALE bar**
  - The close equals the previous close (relative tolerance `step_price_eq_rel_tol`).
  - **and** there was no real trading: volume ZERO, or REAL volume < `step_stale_vol_frac` × baseline, or a single-price bar.
- ZERO volume qualifies as no real trading. MISSING volume alone does not qualify; a single-price session still qualifies from OHLC.
- **STEP event:** the first non-stale bar after ≥ `step_min_stale` stale bars whose move is ≥ `step_jump_pct` % (direction-specific values allowed).
- **TAG:** `step_tag_stale_run` stale bars in a row, or a step event making ≥ `step_events_to_tag` events within `step_window` bars.
- **UNTAG:** `step_end_confirm_days` NORMAL bars: the price moved, not a step, and the average real volume is ≥ `normal_vol_frac` × baseline.
- **Gate:** `TRADE_BLOCKED` reason `STEP_STAIRCASE`, same trading rule as 2.2.

**v2.4.4 calibration:** `step_stale_vol_frac` is 0.20 for stocks and 0.10 for ETFs. The shipped stock profile tags after 3 consecutive stale sessions or on the second qualifying flat-then-jump event (absolute move >=2%) within 40 sessions; it releases after 2 normal sessions. Circuit staircase release is 3 normal sessions.

**ETF absolute traded-value floor (v2.4.4):** effective from 2020-01-01. Median of the trailing 20 real-volume close × volume observations below ₹250,000 activates `low_traded_value`; it clears at ₹375,000. Valid observations before the effective date warm the median but cannot activate the floor. This rule is disabled for stocks.

### 3.7 Rule sets per asset class and per direction (v2.4.3)
- **Asset class:** `asset_class` / `product_class` column → STOCK or ETF. The ETF rule set = the stock rule set + the `*_etf` overrides (`Params.for_class`).
- **Direction:** `StaircaseParams.dir_value(name, direction)`. The `_climbing` / `_falling` values override S, E, the tag volume test, the break tolerance and the STEP jump.
- **Volume (owner rule, 18-Oct-2026):** decisions use REAL volume. ZERO / MISSING volume, or an unreliable volume stretch (< `vol_reliability_min` real-volume share in `vol_reliability_window`), switches the decision to OHLC with a warning (`staircase_vol_reason`).
- **Corporate actions:** |move| > `ca_jump_pct` and not at a matched band → `ca_suspect`. Staircase and STEP hold their state; the band inference ignores the day.

## 4. EOD vs INTRADAY applicability

| Flag | EOD | INTRADAY |
|---|---|---|
| Price band | input / inferred | session band from EOD `band_est_next` |
| Circuit | per session | per bar, own computation (runs reset each session) |
| MWCB | day flag (high/low) | halt + reopen-auction windows by timestamp |
| Staircase | computed here | inherited from previous close + early block |
| Chronic | computed here | inherited from previous close |

---

## 5. Execution model integration

- **Decision bar t:** if `trade_blocked` → no order, and no exit (§2.2).
- **Fill bar t+1** (simulator only):
  - a buy fails if `buy_fill_feasible_at_open` is False (open locked at the upper band, or MWCB halt/auction);
  - a sell fails if `sell_fill_feasible_at_open` is False.
  - The order stays pending, per the engine's order policy.
- **MWCB:** fills are deferred to the first bar after the reopen auction.

---

## 6. Output — universe exclusion table (`build_universe_exclusion_table`)

The SPEC v1 columns, plus:

```
trade_blocked | block_reason (staircase|chronic|mwcb_day|mwcb_halt) |
exclude_from_backtest_EOD | exclude_from_backtest_INTRADAY |
buy_fill_feasible_at_open | sell_fill_feasible_at_open
```

- **EOD:** blocked = staircase OR chronic OR (MWCB day, when `block_on_mwcb_day`).
- **INTRADAY:** blocked = staircase_intraday OR chronic (previous close) OR MWCB halt/auction window.

---

## 7. Parameters (defaults; tune with the full-universe run)

| Parameter | Default | Where |
|---|---|---|
| S / E | 5 / 2 | `StaircaseParams` |
| vol_frac (thin ladder) | None | `StaircaseParams` |
| normal_vol_frac | 0.5 | `StaircaseParams` |
| vol_avg_days / tag_vol_frac / missing_volume_fallback (v2.4.2) | 3 / 0.5 / True | `StaircaseParams` |
| volume_quality / zero_run_missing (v2.4.2) | True / 20 | circuit |
| missing_volume_as_no_trade (v2.4.2) | False | `ChronicParams` |
| volume_lookback / min obs | 20 / 5 | `StaircaseParams` |
| lock_mode | close_locked | circuit |
| tick_size / fine tick / min_band_ticks | 0.05 / 0.01 / 2 | circuit |
| offgrid_max_slack_pct | 0.5 | circuit |
| intraday_candidate_mode | False | circuit |
| staircase segment_cols | ("exchange",) | staircase |
| intraday_min_pinned_bars | 3 | circuit |
| intraday_require_thin_vol | False | circuit |
| chronic window / thresholds | 60 / see §3.5 | `ChronicParams` |
| MWCB basis / cut-over | auto / 2013-07-01 (verify) | mwcb |

---

## 8. Known edge cases and data notes (Final_Data, 2026-09-26)

- **Back-adjusted prices** (RELIANCE shows no bonus gaps). Ratios are preserved, but prices are off the tick grid, so the slack is deliberately generous.
- **Rows stitched monthly across vendor and exchange:** handled by UNKNOWN on exchange switch and by the baseline reset.
- **Rows with blank `symbol`/`source`/`exchange`** but filled `_source`/`_exchange` (10 in INDOTHAI): the runner fills them; the module refuses null keys.
- **Date parsing:** pandas `dayfirst=True` swaps day and month on ISO strings. `parse_dates()` splits ISO from dd-mm-yyyy.
- **Penny stocks:** `tick_degenerate` (see §3.2).
- **Intraday sample:** the 10 intraday symbols are large caps, so there are no circuits to validate against. Illiquid small-cap intraday samples are pending from the owner.
- **Upside-locked (upper = 0):** handled only when band data is supplied. Inference cannot see it.

---

## 9. Implementation map

- `circuit_liquidity_flags.py` — the v1 public names are kept; new functions `compute_chronic_illiquidity_flag`, `aggregate_mwcb_by_date`, `apply_mwcb_windows`, `build_universe_exclusion_table`, `parse_dates`, and the class `CircuitLiquidityTracker` (streaming: `update_eod`, `update_intraday`, `set_eod_state`).
- **Performance:** about 15–40 µs per bar per step. For per-bar engines, use `CircuitLiquidityTracker`. Re-running the batch functions on an expanding window at every bar gives the same values but is O(n²).
- `test_circuit_liquidity_flags.py` — 21 tests; set `QBEAST_DATA` to include the real-data checks.
- `run_four_flags.py` — parallel full-universe run with self-checks on real data.
