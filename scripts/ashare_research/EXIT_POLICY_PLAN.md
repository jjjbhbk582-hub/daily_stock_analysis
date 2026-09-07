# RSI6 fixed entry: exit-policy diagnosis, preregistered before this run

Date 2026-09-07. Existing research branch only. No broker, live trade, paid runner, schedules or main-branch changes.

## Question
Prior outcomes show early losses and many brief losing trades. That is descriptive selection, not proof that holding losers longer helps. Freeze the RSI6 entry, 120 valid-bar warmup and RSI60 rebound target. Diagnose exits rather than add entry filters or optimize parameters.

## Four fixed policies
- D0: identical previous baseline, RSI6 >= 60 OR close below preceding 10 valid closes.
- D1: RSI6 >= 60 OR time limit. No price stop: diagnostic comparator, not eligible for recommendation.
- D2: D1 plus close <= 92% of actual normalized entry open.
- D3: D1 plus close <= entry open minus twice simple 14-valid-bar ATR known on the original buy-signal date. Line never widened.
- Time limit: request exit at the close of the 10th market session counting entry day as 1. If no quote then, the time request still latches; filling must wait. Not a guarantee of liquidation within 10 days.
- All price and target decisions at close; earliest execution next market open. D2's 8% and D3's 2ATR are diagnostic presets, not optimal parameters and not maximum possible loss guarantees. No averaging down or added risk.
- Preserve pending exit date and all simultaneously true reason bits: 1 RSI target, 2 new-low exit, 4 time limit, 8 fixed-percent stop, 16 ATR stop.

## Unchanged inputs and execution, four scenarios
Fixed archive 2026-09-06 / SHA256 482e0575669a11a7d34585cca77912baf7e367962570bdf9c19017c356ffd222. Mainboard periods independently start flat: 2001-2008, 2009-2014, 2015-2020, 2021-2026-09-04. ALL periods have already been observed; none are clean holdouts. No threshold search and no new securities claim.
Same precommitted fractional adjusted units, next-market-day buy attempt and 3% price cap, missing buys cancelled, missing sells pending. Base buy friction 0.13%; sell 0.23% before 2023-08-28 and 0.18% after. Cash stays in each single-stock sleeve.
Scenarios: base; doubled assumed proportional friction; one extra market day delay; removing the old 4.8% negative-opening-gap sell block as an execution-sensitivity diagnostic, NOT a claim of guaranteed fills or legal limits.

## Outputs and safeguards
Record 64 full summary groups, all per-stock outcomes, coverage, daily aggregate NAV, annual changes and baseline reason groups. Preserve ALL base-scenario trades and one exact reason byte per corresponding CSV row; pressure scenarios save outcomes and in-cloud independent account reconciliation, not full trade files. Original CSV bytes must roundtrip through exact packing. No deletion of losing trades or rounding for file size. Output <=32 MiB, retention 3 days; large archive remains transient. A failure to meet delivery size is not a success claim.
Regression: reproduce D0 against old engine and all 12 previous baseline groups after download. Test time counting, quote gaps, loss beyond stop, signal-day ATR, original pending signal and history prefixes. Independently rebuild cash events and reason aggregates from saved base trades after downloading.
Existing heuristic research screen: all four periods positive cumulative and mean net trade return under base and doubled friction, >=1000 closed trades per period, positive after zeroing stale terminal holdings. This is not a statistical significance test; no iteration until passed. Even a passing D2/D3 remains retrospective research, not verified native Tonghuashun or actual cash-share trading.

## Scope and unresolved risks
Equal-initial-capital independent sleeves, fractional normalized units, no share lots, no cross-stock allocation. Official historical universe, ST/delisting, corporate-action cash flows, auction queue, actual raw-price execution and native Tonghuashun remain unverified. Results cannot be applied to a simplified chart indicator that omits position-dependent exits. This run is a controlled exit comparison, not financial advice or a perfect strategy claim.
