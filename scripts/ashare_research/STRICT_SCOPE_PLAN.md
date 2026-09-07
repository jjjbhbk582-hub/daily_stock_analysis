# Mainboard non-ST hard scope — frozen study V1

User-approved continuation, 2026-09-07. Authoritative scope: Shanghai/Shenzhen mainboard A-shares only; no ST/*ST entry, ChiNext, STAR, Beijing, B-shares, funds, or indexes. The allowlist is applied to every simulator call, not merely to the headline report.

## Fixed experiment
Use the 1,649 accepted historical status responses from artifact 10021194677 (run 34126772439), not 3,485 preallocated unknown matrices. No new status download or parameter search in this experiment. At each historical period use the identical covered-stock cohort for comparisons. Do not drop stocks because they later become ST or delist. The 1,836 unavailable histories remain an explicit coverage gap; do not present this as the entire historical market.

Four previously observed periods: 2001-2008, 2009-2014, 2015-2020, and 2021-2026-09-04, separately started in cash. Original D0 and D2 indicators, fees, warmup, 3% entry cap and 4.8% negative-opening-gap sell proxy are unchanged. Only the user's mandatory eligibility handling changes. Neither strategy is promoted or tuned here.

Compare: previous signal-day-only non-ST filter (historical reproducibility reference, not a deployable setting); strict full-lifecycle policy; strict with doubled hypothetical friction; strict with one extra market-day execution delay. Two rules x four periods x four settings = 32 diagnostics. All 32 reported; every base trade retained, pressure scenarios retain per-stock outcome and independent cloud cash audit only.

## Strict decision timing
1. At signal close require mainboard symbol, that date's known isST=0, tradestatus=1, valid quote and unchanged strategy signal. Unknown is never normal. Quantity and price cap fixed then.
2. At scheduled entry attempt recheck that day's effective-dated status. ST, unknown, or nontrading cancels the existing order, without deleting or moving the earlier signal. No resubmission unless a new eligible signal occurs. Current-date status is evaluated inside the chronological loop, not shifted backwards into yesterday's signal.
3. If an existing holding has isST=1 at a later market-day close, latch an exit request, even when its quote is missing. Request execution from the next market day (plus the fixed delay stress, when applicable); do not reset or cancel it if ST later disappears. Preserve existing earlier sell requests. Nontrading days cannot fill a sale. Selling an already-held ST position is risk reduction, not a new ST investment.
4. Never force a fictitious fill or erase the loss. Existing gap proxy, missing quotes and trade state can delay liquidation; report outstanding risk exits and ST holding days.

Important limitation: vendor histories are effective-date records retrieved later, not timestamped public notices. Execution-day status recheck is an effective-date proxy; intraday/publication availability and actual tradability remain unverified. It does not certify a fully point-in-time trading simulation.

## Verification and output
Synthetic scope tests first fail against the legacy-only implementation, then pass against the scope wrapper. Verify normal-state exact parity, ST changes between signal and entry, missing status, suspension with quoted prices, ST during suspended holdings, irreversible risk-exit latch, last-bar pending orders, T+1 and prefixes. Recompute all old normal-eligibility results on the same covered cohorts as exact controls. Inspect every strict base entry (including entries still open at cutoff), all strict base orders, and risk-event history. Save explicit violations if any; do not label unverified checks passed.

Each security has separate initial capital 1, fractional adjusted units, no transfer between securities and no cash interest. Summed/averaged curve drawdown is NOT a one-stock/five-stock account drawdown. No raw-RMB lot/minimum-fee/corporate-action/auction certification; no native Tonghuashun certification. These are the remaining substantive limits even if the scope tests pass.

Independent research branch only. New dedicated explicit trigger, no main or existing file edits, no schedule, no brokerage, no orders, no paid large runner. Standard Ubuntu job <=15 minutes; evidence <=32MiB, retention 3 days; source data not committed. Preserve actual run and commit identifiers. Actual performance and scope compliance are separate conclusions.
