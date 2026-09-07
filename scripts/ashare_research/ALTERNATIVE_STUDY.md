# Fixed alternative mechanisms, V1

This is an authorized, isolated continuation of the A-share indicator study. No main-branch changes, schedules, brokerage access, secrets, paid model calls, or larger runners.

## Rules frozen before new performance calculations

All rules have 120 prior valid quoted bars of warmup, use only the individual stock's quoted OHLCV history, have no cross-sectional ranking, and run through the existing formula_study.simulate execution engine.

1. BREAKOUT20 control: C > MA60; MA60 > REF(MA60,5); C > REF(HHV(C,20),1). Sell C < REF(LLV(C,10),1).
2. SLOW120: MA20 > MA120 and C > MA120. Sell when MA20 < MA120. This tests longer trend retention instead of the shared EXIT10 stop.
3. RSI6_RECOVERY: RSI6 = 100*SMA(max(change,0),6,1)/SMA(abs(change),6,1). Previous RSI6 < 20, current RSI6 increasing, and C > previous C. Sell RSI6 >= 60 OR EXIT10. Recursive averages start at zero; a zero denominator produces RSI=50.
4. BAND_RECOVERY: lower band = MA20 minus two population standard deviations of the last20 closes. Previous close below previous lower band, current close above current lower band, and close increasing. Sell C >= MA20 OR EXIT10.

These are hypotheses, not claims that conventional RSI or Bollinger strategies are profitable. Population-standard-deviation and recursive-initialization semantics must not silently change during eventual native porting.

## Evaluation order and prior data exposure

- development: 2015-01-01 through 2020-12-31.
- exposed_recent: 2021-01-01 through 2026-09-04.
- historical_check: 2009-01-01 through 2014-12-31, not previously used for this project's strategy selection.

Each period starts in cash; preceding quotes are used only for warmup. Results cannot be compounded into a continuous account. The historical check is retrospective rather than prospective. The underlying universe is a current-vintage archive, not independently verified point-in-time security membership. All three alternatives are evaluated, and no candidate is redesigned after any new output is seen.

The sole retrospective research-priority gate is: base and doubled-cost NAV gains and mean closed-trade returns must be positive in all three periods, with at least1000 closed trades per period. Passing that gate is NOT statistical proof, a recommendation, or native Tonghuashun certification.

## Execution and account limits

Independent initial capital1 per stock, no transfers between stock sleeves, fractional normalized Qlib units. Buy quantities fixed at signal close against a 3% cap; next market-day open attempts; missing or too-high buys expire; exits persist, except >=4.8% adverse opening gaps defer exits. Cash has no interest. This repeats the frozen research proxy, not the exchange's legal price limit or guaranteed auction execution.

Scenarios: base, hypothetical proportional costs doubled, and one extra calendar trading-day execution delay. Base all-in costs: buy0.13%; sell0.23% before2023-08-28, then0.18%. These are hypothetical research friction assumptions, not a reconstruction of each historical brokerage bill.

Keep all eligible securities including losing/no-trade sleeves, every closed-trade record, per-stock totals, complete period curves, yearly changes, stale-position flags and zero-stale terminal stress. No historical P&L is erased by dropping a still-held delisted or missing quote security; latest marks are explicitly a limitation.

The bounded cloud artifact contains compressed records and source code, not the564MB source archive. Native client compilation, independent prices, raw-share corporate actions, historicalST/delisting status and feasible-account construction remain separate uncompleted tasks.
