# RSI6 factorial experiment and execution plan

Date: 2026-09-07. Research only; no native Tonghuashun acceptance or investment instruction.

Goal: isolate whether a MA120 entry filter and an earlier RSI50 take-profit improve the previously observed RSI6 recovery mechanism after model costs.
Architecture: add one signal/study script and one check file; reuse the unchanged Qlib parser and normalized-unit execution engine. No main-branch changes, no brokerage, no paid model, no schedule, one standard Ubuntu job, 20-minute job timeout, at most 32 MiB evidence for 3 days.

## Frozen 2 x 2 comparison
- R0: exact prior RSI6_RECOVERY entry and exit. Prior RSI6<20, current RSI rising, close rising. Exit RSI6>=60 or close below previous 10 quoted closes.
- R1: R0 entry AND close>MA120; R0 exit.
- R2: R0 entry; exit RSI6>=50 or previous-10-close breakdown.
- R3: R1 entry; R2 exit.
No entry-threshold, lookback, cash, delay or winner-subset search. RSI uses the prior zero seed and zero-denominator=50; readiness remains 120 earlier valid bars. Entry filtering is a joint economic hypothesis, not an assurance that falling assets are excluded.

Periods independently restart from cash: 2009-2014, 2015-2020, 2021-2026-09-04, followed by 2001-2008 historical transfer check. All four rules go through all periods. First three periods already exposed; 2001-2008 has not previously been used by this project but remains retrospective with 2026-vintage universe bias.
Scenarios: unchanged base costs/delay1; doubled assumed costs/delay1; base costs/delay2. No post-result edits.
All security sleeves start with one unit, keep independent cash, allow fractional adjusted units, and use precommitted quantity and 3% buy cap. Pending sells are blocked on >=4.8% negative adjusted opening gaps exactly as before. This proxy is NOT actual exchange limits. Per-period valid-quote stock inventory is not a point-in-time official market universe.

Screen, not profitability certificate: for each rule, positive aggregate and positive equal-trade mean at base AND doubled costs in each of the first 3 periods, >=1000 closes each; historical transfer is separately evaluated with the same screen. Retain full table regardless of outcome. No retroactive choosing of calendar segments. Native compilation, raw-RMB lots, minima, corporate-action cash accounting, and point-in-time ST/delist validity remain unverified.

## Evidence and implementation
1. Write signal and independent-reconciliation tests, observe import failure, then implement.
2. Verify R0 matches existing implementation on controlled series; verify 2x2 identities and no-lookahead truncation. Compare SMA recurrence independently without calling pandas ewm. Numeric parity is not native application parity.
3. Publish this plan and additive code on the authorized research branch before any market run. Keep existing files unchanged.
4. Run all 48 scenario-period combinations on the same pinned archive. Preserve every BASE trade; for pressure scenarios preserve all per-stock account summaries plus independent per-stock ledger audit, NOT full trade files. This bounded-output policy is set before results to avoid exceeding the artifact budget; the frozen reproducer can emit them again. Record transient pressure trade counts explicitly.
5. Download result. Independently rebuild baseline cash, fees, final NAV and grouped summaries. Verify prior R0 values reproduce. Publish findings and limitations, not an unvalidated trading indicator.
