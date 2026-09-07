# Consolidated A-share research batch — 2026-09-08

User authorizes continued, larger-batch work, only on this independent research branch. Do not modify main or existing daily review workflows; no brokerage, real orders, schedules, paid large runners or paid model calls.

## Deliverables and fixed boundaries
1. Reuse the 1,649 accepted full status histories from artifact 10021194677, run 34126772439. Request only remaining codes. At most four provider sessions and 1,500 seconds per worker; bounded retry and checkpoint per completed response. Preserve missing/error/empty distinctions, exact provider fields and source records. A complete response is not official point-in-time certification.
2. Probe eight historical all-stock snapshots to test whether the provider actually returns historical names around known delisting phases. Failure must not be silently turned into ordinary-listing evidence.
3. Independently audit the lifecycle exclusion and finite-capital execution question. Only mainboard non-ST, reject unknown status, preserve pre-ST holdings and forced-exit losses. A permanent quarantine after a historically observed ST event is permitted only as a separately labeled conservative research restriction, not as proof of every listing phase. Never delete all past observations of companies that later delisted.
4. Compare at most four predeclared single-stock signal hypotheses, with a single 100,000 RMB research account, no leverage, at most five concurrent positions, no reinvestment of same-open sale proceeds, next-session planned orders, 100-share entry lots, commission minimums, and sensitivity to costs and execution. Any approximate corporate-action accounting or price-limit assumptions must be explicit. Do not conflate fractional adjusted units with raw RMB shares.
5. Keep the fixed quote cutoff 2026-09-04. Earlier historical dates and stock data have already been inspected: these are retrospective diagnostics, not pristine holdouts. Report individual-position and finite-account risk, not just averages of thousands of independent sleeves.
6. Save a single consolidated report, source, raw status evidence and reproducible checks; no native Tonghuashun compilation or profitable-strategy certification unless actually established.

## Acquisition component
New code: batch_completion.py, checks_batch_completion.py and one isolated acquisition workflow. Source seed is checked against its actual matrix and accepted row counts; incomplete matrices are not complete histories. The full archive or duplicate per-security checkpoints are not uploaded; bounded artifacts retained three days. Exact raw consolidated status records are preserved. Neither a green Actions job nor unit-test count is a trading result.

## Portfolio component
The exact hypotheses, financial assumptions and scenario limits must be written before retrieving their performance. A limited baseline/variants/scenarios matrix replaces open-ended parameter search. Reporting must disclose failed variants and cannot retrospectively pick a favorable security subset. Any failed data or listing validation remains a certification blocker.
