# Historical status continuation V2

User authorized continuation of the isolated research branch. Main, existing review tasks, broker/order interfaces and schedules are out of scope. This is a data-coverage repair, not a search for better strategy parameters.

## Inputs frozen before collection
- Original status artifact 10014861097, run 34110915846: 290 accepted, nonempty full histories.
- Previously completed T export artifact 10016961250, run 34117138504 attempt 2: 120 accepted histories. Ignore its 8 failed/unattempted codes, its separate short controls, and its price panel when importing full histories.
- The two sets were independently compared with their original matrices and raw rows: 410 distinct histories, 1,610,302 provider rows. Do not repeat these network requests.
- Actual inventory remains 3,485 archive mainboard codes. Request only the remaining 3,075, in the existing deterministic SHA-256 ordering, over the unchanged 2000-01-04 through 2026-09-04 calendar.
- Source payload SHA-256 values in STATUS_RESUME_SEEDS.json must match before any seed is accepted. Completed response counts, fields, dates and matrices must reconcile. Conflicting histories fail closed rather than being silently preferred.

## Recovery and limits
- Four process-isolated BaoStock 0.9.3 sessions; at most 900 seconds of collection per process, with the existing 25-second query/login deadlines. This replaces the earlier two-session collector; no paid or larger compute is used.
- A query can be retried once after a fresh login; repeated failure is recorded. Six consecutive failures stop that worker. Requests are spaced by 0.1 seconds in addition to server response time. Do not repeatedly hammer a failed endpoint.
- Save every complete, validated nonempty response atomically before moving to the next code. A partial request is not a successful empty history. Worker interruption must not invalidate previously saved complete files.
- Consolidate all accepted raw fields losslessly; retain the merged matrix, original records, accepted/remaining lists, seed provenance and attempt journal. The merged checkpoint is itself reloadable and validated before reuse.
- No current-name backfill, no forward/backfill across unknown status days. Unknown remains -1, not normal. Source records are later-retrieved effective-date histories, not a certified announcement-time archive.
- This run uses one standard public Ubuntu runner, no schedules and read-only Actions/contents permissions. Previous immutable artifacts are only read. New artifact cap is 32 MiB, retention 3 days; no raw 564 MB price archive is uploaded.

## Frozen diagnostic
Run the existing status_admission_study with D0/D2 and baseline/known/normal/normal_double unchanged. The only substituted input is the merged historical-state source; price archive, RSI rules, exits, costs, opening-gap proxy, calendars and cash-sleeve assumptions remain unchanged.

The legacy 32-group output still keeps unknown cash sleeves in its denominator. Report exact state coverage and distinguish complete-source subgroup results from those full-denominator outputs. Do not call a lower all-market curve drawdown a trading improvement when caused by missingness.

Retain all base-policy trade rows (baseline/known/normal). The double-cost branch retains per-stock results and cloud audit rather than every trade row, exactly as before. Two historical smoke controls are reused and explicitly labelled reused, not a new independent source validation.

No source-completeness or trading-readiness claim unless supported by completed output. Official historical universe, ST announcements, raw-share/dividend accounting, exchange queues and native Tonghuashun remain unverified. trade_ready stays false.
