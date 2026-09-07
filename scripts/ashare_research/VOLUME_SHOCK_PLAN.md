# Volume-shock study V1 — frozen before market outcomes

## Question and permission
Continue the authorized mainboard/non-ST indicator research on the existing public isolated branch only. New mechanisms are tested, not recommended. No main changes, scheduled tasks, brokers, orders, paid models, or larger runners.

## Fixed sample and provenance
Reuse the 1,649 accepted complete BaoStock histories from run 34126772439 / artifact 10021194677. The aligned state matrix SHA-256 is 1fb6fb4d270b9c490c17524d49fca86e8b981333dce7017ccd066d8274b83906. Its effective dates are not verified publication timestamps; it covers only part of the historical mainboard. Do not default missing state to normal or remove later losers.
Prices are the unchanged 2026-09-06 Qlib archive with SHA-256 482e0575669a11a7d34585cca77912baf7e367962570bdf9c19017c356ffd222. Adjustment units are not a real cash/share account.
Periods independently start flat: 2001-2008, 2009-2014, 2015-2020, 2021-2026-09-04. ALL these dates and codes have been observed previously. No new clean holdout is claimed.

## Frozen four rules
D0: unchanged strict RSI6 baseline, only a reproduction reference.
Let TR=max(H-L,abs(H-previous C),abs(L-previous C)). ATRprev is the mean of the PREVIOUS 14 TR values, excluding the signal day. Vmeanprev is the mean of the PREVIOUS 20 volumes.
V0: C <= previous C - 1.5*ATRprev AND C < minimum of previous 5 closes AND ATRprev>0. No volume restriction.
VH: V0 AND V >= 1.5*Vmeanprev.
VL: V0 AND V <= Vmeanprev.
Require 120 earlier valid price rows and positive Vmeanprev. High and low volume subsets do not overlap. V0 retains middle-volume signals too. No threshold sweep or optimization is allowed after results.
For V0/VH/VL, exits are: close>=current MA5 OR the tenth market session since filled entry (entry=1) OR close<=92% of filled entry open. These three share identical exits and execution; D0 does not. An MA5 exit may still be a loss. Neither the 8% trigger nor ten-session deadline guarantees execution or a maximum loss.

## Execution and hard scope
Reuse strict_mainboard_scope.simulate_scope unchanged: only allowed Shanghai/Shenzhen mainboard codes, signal-day and execution-day known non-ST, known trade status=1. Later ST triggers a retained exit request, not retrospective deletion. No averaging into a position. Orders fix fractional adjusted units and a 3% price cap at signal close, with next-market-day open proxy; unfilled buys expire. No same-day resale. Existing 4.8% negative opening-gap sell block remains a research proxy, not a legal price-limit model.
Scenarios for all four rules: base; doubled assumed total friction; extra one-session execution delay; no 4.8% gap proxy (not assumed tradable). Buy friction=.13%, sell=.23% before 2023-08-28 and .18% later; these are model assumptions, not a historical broker fee reconstruction.
Independent initial unit per stock, no transfers or cash interest. Equal initial sleeves; report median individual drawdown as well as average-curve drawdown and exposure. Compare every rule within the same covered population. No cash placeholders for unacquired histories.

## Validation and decision rules
Before any market run: synthetic tests cover previous-window exclusion, high/low subsets, constant-series edge cases, scale invariance, prefix causality, no same-day exit, status changes, and inherited D0.
Every simulated account is checked from cash records without reusing the simulation path. All base trades and their reasons, entries, and state audit are saved. Stress scenarios retain per-stock outcome/audit, not every trade file. Include closed-trade rates, mean returns, median sleeve results, stale-value write-down, year-by-year path, entry counts and exposure.
Same-source offline quote samples are chosen by a fixed code hash, not returns, to allow independent signal and path recreation. Saved sample is not independent market evidence.
Screen to continue research, not certify trading: each of four base AND doubled-cost period results must have positive final mean NAV growth, positive mean net trade return, positive stale-zero result and >=1000 closes. Keep the earlier gate even when the outcome is disappointing. Do not promote a low-exposure curve on drawdown alone.
Add 1,000 moving-block bootstrap draws of 20 market sessions to the base daily aggregate log-return series, and paired filtered-minus-V0 series. These conditional intervals account for clustered daily market moves, not adaptive historical selection, provider bias, or all multiple testing. Do not label them proof of future profits.

## Evidence and limits
One bounded cloud run (25-minute job cap), 32MiB output cap, three-day artifact retention. No full price archive upload. Save the plan and code before run; do not delete loss rows to fit output. Native Tonghuashun compilation, point-in-time announcements, raw RMB round lots/minimum fees, cash dividends/share counts, auction order queues and full historical state coverage remain unverified.
Motivation only (NOT reproduction or proof): the primary literature distinguishes short-term reversal from simple daily bid-ask bounce and suggests volume/timing matter in China: https://doi.org/10.1016/j.frl.2022.103220 ; https://www.sciencedirect.com/science/article/abs/pii/S0264999326003123 . The latter uses market indices and next-day intraday returns; this stock-level, T+1-respecting multi-day test is different.
Tonghuashun MA/REF/LLV definitions: https://www.10jqka.com.cn/ad_mar/man/f5-6-5.htm . Mathematical expression is not native-client certification.
