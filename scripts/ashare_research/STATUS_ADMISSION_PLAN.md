# Historical-status admission diagnostic V1

Approved continuation: independent public research branch only. No main changes, schedules, brokerage, order submission or paid large runners.

## Fixed question
Does excluding securities whose signal-day historical status is ST improve the existing RSI rules? Distinguish that effect from missing data. Do not change indicator parameters or exits, do not use current security names or final delisting outcomes to remove past trades.

## Frozen scope and methods
- Qlib archive and SHA-256 are inherited unchanged from source.json. Inventory is the same 3,485 historical mainboard codes; it is not certified as the official historical market denominator.
- Periods: 2001-2008, 2009-2014, 2015-2020, 2021-2026-09-04. All have already been observed; this is not a new holdout.
- BaoStock 0.9.3 query_history_k_data_plus requests date,code,tradestatus,isST, adjustment flag 3, on every inventory code from the archive calendar start through cutoff.
- Two independent sessions only; per-query timeout 25 seconds, per-worker budget 600 seconds, three consecutive errors trip a circuit breaker. Deterministic SHA-256 stock ordering prevents incomplete execution from simply selecting low codes. Every attempted, empty, failed or unattempted code is recorded.
- Preserve exact provider field values in compressed CSV plus aligned int8 matrices. Missing values stay unknown; no forward/back filling. Duplicate, noncanonical or unsorted dates, invalid enums and wrong codes are rejected, not silently repaired.
- Smoke controls on 2024-04-17: SH600766 expected isST=1 (issuer disclosure predates this date); SH600000 expected 0. Failure of either control, or fewer than 100 nonempty histories, blocks all new performance calculations.
- Admit policies: baseline (no status filter); known (signal-day documented isST plus tradestatus=1, ignores ST value); normal (signal-day isST=0 and tradestatus=1). This isolates missingness versus the incremental ST filter. No next-day or eventual-delisting status is used to decide today's signal.
- D0 and D2 unchanged from exit_policy_study.py. For each period run baseline/known/normal under base cost plus normal with doubled hypothetical friction: 32 shadow scenarios total. Sell logic, including the old 4.8% opening-gap proxy, is deliberately unchanged to isolate admission; it is NOT a verified legal limit rule.
- Admission is assessed at signal close only. An ensuing ST change does not retroactively remove the order. Its announcement timestamp and pre-open implementation need separate confirmation. No historical risk/liquidation completeness claim.
- A source-coverage flag requires at least 99% of valid price days to have known status plus both controls. It is not a profitability screen. If coverage is partial, disclose both numerator and denominator; unknown stock sleeves are still in the same period denominator, not dropped.
- Preserve all base scenario trades. Doubled-cost scenarios retain per-stock results and independent cloud ledger audit, not every trade row. Output cap 32MiB, three-day artifact retention; no full archive upload.
- All securities have separate initial capital 1 and fractional adjusted units; cash is not transferred. This is not a real RMB account, and whole-market curve risk is not single-stock risk.

## Evidence limits
Historical isST is an effective-date series retrieved today, not a bitemporal announcement archive. Delisting recovery, actual share/dividend accounting, legal auction queues, independent full-series price checks and native Tonghuashun remain unverified. Excluding ST does not promise profitability. All result versions remain trade_ready=false.

## Checks and implementation
Local tests first: unknown/empty status, invalid flags, duplicates, cross-code contamination, calendar gaps, future-ST backfill, suspension status, deterministic ordering, signal-date versus execution-date causality, and baseline execution equivalence. Reuse the frozen simulator rather than replace its accounting.

Source API example: https://pypi.org/project/baostock/ . Known-risk issuer disclosure: https://paper.cnstock.com/html/2024-04/03/content_1894932.htm .
