"""Frozen RSI6 2x2 diagnostic. Fractional adjusted units, never native/real-account certification."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import lzma
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from alternative_study import alternative_signals
from formula_study import load_archive, decode_bars, simulate, mdd
from verify_data import download, verify_identity

RULES = ('R0', 'R1', 'R2', 'R3')
PERIODS = {'early': ('2009-01-01', '2014-12-31'),
           'middle': ('2015-01-01', '2020-12-31'),
           'recent': ('2021-01-01', '2026-09-04'),
           'older_transfer': ('2001-01-01', '2008-12-31')}
SCENARIOS = {'base': (1., 1), 'double_cost': (2., 1), 'delay2': (1., 2)}
COLUMNS = ['open', 'high', 'low', 'close', 'volume']
TRADE_HEADER = ['period', 'rule', 'scenario', 'symbol', 'buy_signal', 'buy_date',
                'sell_signal', 'sell_date', 'buy_price', 'sell_price', 'units', 'entry_cost']


def rsi_reference(close):
    """Independent SMA recurrence with the same zero seed, without pandas ewm."""
    result = np.full(len(close), 50.)
    up = distance = 0.
    for i in range(1, len(close)):
        delta = float(close[i] - close[i-1])
        up = (5*up + max(delta, 0.))/6
        distance = (5*distance + abs(delta))/6
        result[i] = 100*up/distance if distance else 50.
    return result


def factorial_signals(frame):
    original = alternative_signals(frame)
    c = frame.close
    delta = c.diff().fillna(0.)
    up = delta.clip(lower=0).ewm(alpha=1/6, adjust=False).mean()
    distance = delta.abs().ewm(alpha=1/6, adjust=False).mean()
    rsi = (100*up/distance.replace(0, np.nan)).fillna(50.)
    ready = original['ELIGIBLE']
    buy = original['RSI6_RECOVERY_BUY']
    sell = original['RSI6_RECOVERY_SELL']
    filtered = buy & (c > c.rolling(120).mean()).to_numpy()
    fast = (((rsi >= 50) | (c < c.rolling(10).min().shift(1))).to_numpy() & ready)
    return {'R0_BUY': buy, 'R0_SELL': sell,
            'R1_BUY': filtered, 'R1_SELL': sell,
            'R2_BUY': buy, 'R2_SELL': fast,
            'R3_BUY': filtered, 'R3_SELL': fast}


def audit_account(res, bars, costs, multiple):
    """Reconcile immutable cash events without calling the simulator."""
    cash = 1.
    maxerr = 0.
    last_exit = -1
    for sig, bi, ss, si, bp, sp, q, basis, pnl, ret in res['trades']:
        assert last_exit < bi and sig < bi <= ss < si
        assert bp == bars[bi, 0] and sp == bars[si, 0]
        expected = q*bp*(1+.0013*multiple)
        proceeds = q*sp*(1-costs[si]*multiple)
        maxerr = max(maxerr, abs(basis-expected), abs(pnl-(proceeds-basis)), abs(ret-(proceeds/basis-1)))
        cash += pnl
        last_exit = si
    cash -= res['open_entry_cost']
    value = res['units']*res['mark'] if res['units'] else 0.
    maxerr = max(maxerr, abs(cash-res['cash']), abs(cash+value-res['nav'][-1]))
    assert maxerr < 1e-8 and cash >= -1e-10
    return maxerr


def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'work', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.source.read_text())
    plan = Path(__file__).with_name('RSI_FACTORIAL_PLAN.md').read_text()
    (args.output/'plan.md').write_text(plan)
    archive = args.work/'qlib_bin.tar.gz'
    if not archive.exists():
        download(config['archive_url'], archive, config['archive_size'], config['archive_sha256'])
    verify_identity(archive, config['archive_size'], config['archive_sha256'])
    days, intervals, raw, decode = load_archive(archive, config['requested_end'])
    dates = np.asarray(days)
    costs = np.where(dates < '2023-08-28', .0023, .0018)
    bounds = {p: (int(np.searchsorted(dates, a)), int(np.searchsorted(dates, b, side='right')))
              for p, (a, b) in PERIODS.items()}
    sums = {}; exposure = {}; stats = {}; counts = {p: 0 for p in PERIODS}
    for period, (left, right) in bounds.items():
        for rule in RULES:
            for scenario in SCENARIOS:
                key = (period, rule, scenario)
                sums[key] = np.zeros(right-left); exposure[key] = np.zeros(right-left)
                stats[key] = [0, 0, 0., 0., 0.]
    stocks = []; coverage = []; parity_examples = []
    audit_count = total_trades = saved_trades = prefixes = parity_tests = parity_mismatches = 0
    max_rsi_difference = 0.
    with lzma.open(args.output/'base_trades.csv.xz', 'wt', preset=6, newline='') as stream:
        writer = csv.writer(stream); writer.writerow(TRADE_HEADER)
        for num, symbol in enumerate(sorted(intervals), 1):
            bars = decode_bars(raw[symbol], days, intervals[symbol], decode)
            valid = np.isfinite(bars).all(axis=1) & (bars > 0).all(axis=1)
            ids = np.flatnonzero(valid)
            frame = pd.DataFrame(bars[ids], columns=COLUMNS)
            flags = factorial_signals(frame)
            for cutoff in ('2008-12-31', '2014-12-31', '2020-12-31'):
                n = int(np.searchsorted(dates[ids], cutoff, side='right'))
                short = factorial_signals(frame.iloc[:n])
                for key in flags:
                    assert np.array_equal(flags[key][:n], short[key]), 'Future-sensitive signal'
                prefixes += 1
            if len(ids):
                rsi = rsi_reference(frame.close.to_numpy())
                c = frame.close; d = c.diff().fillna(0.)
                u = d.clip(lower=0).ewm(alpha=1/6, adjust=False).mean()
                v = d.abs().ewm(alpha=1/6, adjust=False).mean()
                vector_rsi = (100*u/v.replace(0, np.nan)).fillna(50.).to_numpy()
                max_rsi_difference = max(max_rsi_difference, float(np.max(np.abs(rsi-vector_rsi))))
                previous = np.r_[50., rsi[:-1]]
                ready = np.arange(len(ids)) >= 120
                ref_buy = (previous < 20) & (rsi > previous) & (c.to_numpy() > c.shift(1).to_numpy()) & ready
                exit10 = (c < c.rolling(10).min().shift(1)).to_numpy()
                for key, ref in (('R0_BUY', ref_buy), ('R0_SELL', ((rsi >= 60) | exit10) & ready),
                                 ('R2_SELL', ((rsi >= 50) | exit10) & ready)):
                    mismatch = np.flatnonzero(ref != flags[key])
                    parity_tests += len(ids); parity_mismatches += len(mismatch)
                    for j in mismatch[:max(0, 100-len(parity_examples))]:
                        parity_examples.append([symbol, days[ids[j]], key, float(rsi[j]), float(vector_rsi[j])])
            dense = {k: np.zeros(len(days), dtype=bool) for k in flags}
            for key in flags: dense[key][ids] = flags[key]
            for period, (left, right) in bounds.items():
                within = ids[(ids >= left) & (ids < right)]
                mature = int(((ids >= left) & (ids < right) & (np.arange(len(ids)) >= 120)).sum())
                coverage.append([period, symbol, len(within), mature])
                if not len(within): continue
                counts[period] += 1
                for rule in RULES:
                    for scenario, (multiple, delay) in SCENARIOS.items():
                        key = period, rule, scenario
                        res = simulate(bars[:right], dense[rule+'_BUY'][:right], dense[rule+'_SELL'][:right],
                                       costs[:right], left, multiple, delay)
                        err = audit_account(res, bars, costs, multiple); audit_count += 1
                        sums[key] += res['nav']; exposure[key] += res['exposure']
                        st = stats[key]
                        for sig, bi, ss, si, bp, sp, q, basis, pnl, ret in res['trades']:
                            st[0] += 1; st[1] += int(ret > 0); st[2] += ret
                            st[3] += max(pnl, 0.); st[4] += max(-pnl, 0.)
                            total_trades += 1
                            if scenario == 'base':
                                writer.writerow([period, rule, scenario, symbol, days[sig], days[bi],
                                                 days[ss], days[si], bp, sp, q, basis])
                                saved_trades += 1
                        stale = bool(res['units'] and right-1-res['last_quote'] >= 20)
                        stocks.append([period, rule, scenario, symbol, float(res['nav'][-1]), res['cash'],
                                       res['units'], res['mark'], res['open_entry_cost'], len(res['trades']),
                                       res['entries'], res['cancelled'], res['blocked_sells'],
                                       res['units']*res['mark'] if stale else 0., err])
            if num % 500 == 0:
                print(f'Processed {num}/{len(intervals)}; audited {audit_count}; baseline trades {saved_trades}', flush=True)
    stockcols = ['period','rule','scenario','symbol','final_nav','cash','units','mark','open_entry_cost',
                 'closed_trades','entries','cancelled_buys','blocked_sell_days','stale_value','audit_error']
    stockdf = pd.DataFrame(stocks, columns=stockcols)
    stockdf.to_csv(args.output/'per_stock.csv.xz', index=False)
    pd.DataFrame(coverage, columns=['period','symbol','valid_bars','mature_bars']).to_csv(args.output/'coverage.csv.xz', index=False)
    summary = []; annual = []
    with lzma.open(args.output/'equity.csv.xz', 'wt', preset=6, newline='') as stream:
        writer = csv.writer(stream); writer.writerow(['period','rule','scenario','date','nav','mean_sleeve_exposure'])
        for key, values in sums.items():
            period, rule, scenario = key; left, right = bounds[period]
            if counts[period] == 0: raise ValueError('Empty requested period')
            nav = values/counts[period]; exp = exposure[key]/counts[period]; st = stats[key]
            sub = stockdf[(stockdf.period == period) & (stockdf.rule == rule) & (stockdf.scenario == scenario)]
            for day, n, e in zip(dates[left:right], nav, exp): writer.writerow([period,rule,scenario,day,n,e])
            row = dict(period=period,rule=rule,scenario=scenario,codes=counts[period],
                       return_total=float(nav[-1]-1),max_drawdown=mdd(nav),closed_trades=int(st[0]),
                       win_rate=st[1]/st[0] if st[0] else None,mean_trade_return=st[2]/st[0] if st[0] else None,
                       profit_factor=st[3]/st[4] if st[4] else None,mean_sleeve_exposure=float(exp.mean()),
                       median_sleeve_return=float(sub.final_nav.median()-1),profitable_fraction=float((sub.final_nav>1).mean()),
                       stale_zero_return=float(nav[-1]-1-sub.stale_value.sum()/counts[period]),
                       max_audit_error=float(sub.audit_error.max()))
            summary.append(row)
            for year in sorted(set(d[:4] for d in days[left:right])):
                ii=np.flatnonzero(np.char.startswith(dates[left:right], year));a,b=ii[0],ii[-1]
                before=nav[a-1] if a else 1.
                annual.append([period,rule,scenario,year,float(nav[b]/before-1),mdd(nav[a:b+1]/before),len(ii)])
    table = pd.DataFrame(summary); table.to_csv(args.output/'summary.csv',index=False)
    pd.DataFrame(annual,columns=['period','rule','scenario','year','return_total','max_drawdown','days']).to_csv(args.output/'yearly.csv',index=False)
    gates = {}
    for rule in RULES:
        gates[rule] = {}
        for group, periods in [('exposed_three', ('early','middle','recent')), ('older_transfer', ('older_transfer',))]:
            rows = table[(table.rule==rule)&table.period.isin(periods)&table.scenario.isin(['base','double_cost'])]
            gates[rule][group] = bool(((rows.return_total>0)&(rows.mean_trade_return>0)&(rows.closed_trades>=1000)).all())
    result = {'study':'RSI6_FACTORIAL_V1','finished_at_utc':datetime.now(timezone.utc).isoformat(),
              'counts':counts,'independent_codes':int(pd.DataFrame(coverage)[pd.DataFrame(coverage)[2]>0][1].nunique()),
              'quote_rows':int(sum(x[2] for x in coverage)),'audited_accounts':audit_count,
              'transient_all_scenario_trades':total_trades,'saved_base_trades':saved_trades,
              'pressure_trade_files_saved':False,'signal_prefix_checks':prefixes,
              'rsi_reference_boolean_comparisons':parity_tests,'rsi_reference_mismatches':parity_mismatches,
              'max_rsi_difference':max_rsi_difference,'parity_examples':parity_examples,'gates':gates,
              'native_ths_verified':False,'real_account_verified':False,'trade_ready':False,
              'source':config,'plan_sha256':hashlib.sha256(plan.encode()).hexdigest()}
    (args.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    lines=['# RSI6 factorial diagnostic','', 'Fractional adjusted-unit sleeves, not a real account or native Tonghuashun certification.', '',
           '|Period|Rule|Scenario|Cumulative return|Drawdown|Closes|Mean trade|','|---|---|---|---:|---:|---:|---:|']
    for row in summary:
        mt='n/a' if row['mean_trade_return'] is None else f"{row['mean_trade_return']:.3%}"
        lines.append(f"|{row['period']}|{row['rule']}|{row['scenario']}|{row['return_total']:.2%}|{row['max_drawdown']:.2%}|{row['closed_trades']}|{mt}|")
    lines+=['', 'Screen results, not certificates: '+json.dumps(gates), '',
            'All base trades retained. Pressure scenarios retain per-stock outcomes and independent audit, not individual trade files.',
            'Historical universe, ST/delisting, actual shares/dividends, native SMA initialization, legal limits and auction fills remain unverified.']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__ == '__main__': main()
