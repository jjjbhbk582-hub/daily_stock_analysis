"""Frozen three-rule historical diagnostic; no broker access or optimization.

Prices are Qlib adjusted/normalized units, NOT raw RMB. Each security has
its own initial unit of capital. This is NOT a feasible multi-stock account.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import tarfile
from datetime import datetime, timezone
import numpy as np
import pandas as pd

RULES = ('BREAKOUT20', 'MA20_RECLAIM', 'BREAKOUT_RETEST5')
SCENARIOS = {'base': (1., 1), 'double_cost': (2., 1), 'delay2': (1., 2)}
START = '2015-01-01'
END = '2026-09-04'


def signals(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Formula windows use valid quoted bars, not filled suspension days."""
    c,h,l=df['close'],df['high'],df['low']
    ma20=c.rolling(20).mean();ma60=c.rolling(60).mean()
    mature=pd.Series(np.arange(len(c))>=120,index=c.index)
    trend=mature & (c>ma60) & (ma60>ma60.shift(5))
    level=c.rolling(20).max().shift(6)
    result={
        'BREAKOUT20': trend & (c>c.rolling(20).max().shift(1)),
        'MA20_RECLAIM': trend & (c.shift(1)<=ma20.shift(1)) & (c>ma20) & (c>h.shift(1)),
        'BREAKOUT_RETEST5': trend & (c.shift(5)>level)
            & (c.rolling(4).min().shift(1)>=level)
            & (l<=level*1.02) & (c>=level) & (c>h.shift(1)),
        'EXIT10': mature & (c<c.rolling(10).min().shift(1)),
        'ELIGIBLE': mature,
    }
    return {k:v.fillna(False).to_numpy(dtype=bool) for k,v in result.items()}


def simulate(bars: np.ndarray, buy: np.ndarray, sell: np.ndarray,
             sell_cost: np.ndarray, start: int, cost_multiple: float=1.,
             delay: int=1) -> dict:
    """Precommitted normalized units, 3% buy cap, next-market-day attempts.

A buy expires if its scheduled date has no quote. Exits remain pending.
A >=4.8% negative opening gap blocks a sale as an explicit stress proxy,
NOT an assertion that this is the security's legal limit-down percentage.
"""
    n=len(bars)
    if bars.shape!=(n,5) or len(buy)!=n or len(sell)!=n or len(sell_cost)!=n:
        raise ValueError('Input shapes differ')
    if delay not in (1,2) or not 0<=start<n or cost_multiple<=0:
        raise ValueError('Invalid simulation settings')
    valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1)
    o,c=bars[:,0],bars[:,3]
    previous=np.flatnonzero(valid[:start])
    mark=float(c[previous[-1]]) if len(previous) else math.nan
    last_quote=int(previous[-1]) if len(previous) else -1
    cash=1.;units=0.;buy_fee=.0013*cost_multiple
    pending_buy=None;pending_sell=None;entry=None
    nav=np.empty(n-start);exposure=np.empty(n-start)
    trades=[];entries=0;cancelled=0;blocked_sells=0
    for i in range(start,n):
        if valid[i]:
            if units>0 and pending_sell is not None and i>=pending_sell[0]:
                if o[i]/mark-1<=-.048:
                    blocked_sells+=1
                else:
                    fee=float(sell_cost[i])*cost_multiple
                    proceeds=units*o[i]*(1-fee)
                    basis=entry[3]
                    trades.append((entry[0],entry[1],pending_sell[1],i,
                                   entry[2],float(o[i]),units,basis,
                                   proceeds-basis,proceeds/basis-1))
                    cash+=proceeds;units=0.;pending_sell=None;entry=None
            if pending_buy is not None and pending_buy[0]==i:
                _,limit,quantity,signal_idx=pending_buy
                spend=quantity*o[i]*(1+buy_fee)
                if o[i]<=limit and spend<=cash+1e-12 and units==0:
                    cash-=spend;units=quantity;entries+=1
                    entry=(signal_idx,i,float(o[i]),spend)
                else:
                    cancelled+=1
                pending_buy=None
            mark=float(c[i]);last_quote=i
        elif pending_buy is not None and pending_buy[0]==i:
            cancelled+=1;pending_buy=None
        value=units*mark if units else 0.
        nav[i-start]=cash+value
        exposure[i-start]=value/nav[i-start]
        if valid[i]:
            if units>0 and sell[i] and pending_sell is None:
                pending_sell=(i+delay,i)
            elif units==0 and pending_buy is None and buy[i]:
                limit=mark*1.03
                quantity=cash/(limit*(1+buy_fee))
                pending_buy=(i+delay,limit,quantity,i)
        if cash < -1e-10:
            raise AssertionError('Negative cash')
    return {'nav':nav,'exposure':exposure,'trades':trades,'cash':cash,
            'units':units,'mark':mark,'last_quote':last_quote,
            'entries':entries,'cancelled':cancelled,'blocked_sells':blocked_sells,
            'open_entry_cost':entry[3] if entry else 0.,
            'open_entry_price':entry[2] if entry else 0.,
            'open_entry_index':entry[1] if entry else -1}


def load_archive(path: Path, cutoff: str):
    # Reuse the already tested archive safety and float-offset parser.
    from verify_data import safe_name, FEATURE, is_mainboard, decode_feature, read_calendar
    raw={};calendar_raw=None;instrument_raw=None;seen=set();expanded=0
    wanted={'open','high','low','close','volume'}
    with tarfile.open(path,'r|gz') as archive:
        for item in archive:
            name=safe_name(item.name)
            if name in seen or len(seen)>200000 or not (item.isfile() or item.isdir()):
                raise ValueError('Unsafe or duplicate archive member')
            seen.add(name);expanded+=item.size
            if item.size>8*1024**2 or expanded>10*1024**3:
                raise ValueError('Archive size limit')
            match=FEATURE.fullmatch(name)
            take=match and is_mainboard(match[1]) and match[2] in wanted
            if name not in ('qlib_bin/calendars/day.txt','qlib_bin/instruments/all.txt') and not take:
                continue
            handle=archive.extractfile(item)
            if handle is None: raise ValueError('Missing member')
            payload=handle.read()
            if len(payload)!=item.size: raise ValueError('Truncated member')
            if name.endswith('/calendars/day.txt'): calendar_raw=payload
            elif name.endswith('/instruments/all.txt'): instrument_raw=payload
            else: raw.setdefault(match[1].upper(),{})[match[2]]=payload
    if calendar_raw is None or instrument_raw is None: raise ValueError('Missing index')
    days=read_calendar(calendar_raw,cutoff)
    if days[-1]!=cutoff: raise ValueError('Cutoff mismatch')
    intervals={}
    for line in instrument_raw.decode().splitlines():
        symbol,first,last=line.split('\t')
        if is_mainboard(symbol): intervals.setdefault(symbol,[]).append((first,last))
    return days,intervals,raw,decode_feature


def decode_bars(fields, days, ranges, decode):
    n=len(days);bars=np.full((n,5),np.nan)
    for j,key in enumerate(('open','high','low','close','volume')):
        offset,values=decode(fields[key],n)
        bars[offset:offset+len(values),j]=values
    active=np.zeros(n,dtype=bool);dates=np.array(days)
    for first,last in ranges: active|=(dates>=first)&(dates<=last)
    prices=bars[:,:4]
    any_price=np.isfinite(prices).any(axis=1)
    complete=np.isfinite(prices).all(axis=1)&(prices>0).all(axis=1)
    malformed=any_price & (~complete | ~np.isfinite(bars[:,4]) | (bars[:,4]<0))
    malformed|=complete & ((prices[:,2]>prices[:,0]+1e-6)
        |(prices[:,2]>prices[:,3]+1e-6)|(prices[:,1]+1e-6<prices[:,0])
        |(prices[:,1]+1e-6<prices[:,3])|(prices[:,1]<prices[:,2]))
    if malformed.any(): raise ValueError(f'{int(malformed.sum())} invalid quote rows')
    bars[~active]=np.nan
    return bars


def mdd(nav):
    high=np.maximum.accumulate(np.r_[1.,nav])[1:]
    return float(np.max(1-nav/high))


def rule_record():
    return {
      'rules':list(RULES),'warmup_quoted_bars':120,
      'trend':'C>MA(C,60) AND MA(C,60)>REF(MA(C,60),5)',
      'BREAKOUT20':'trend AND C>REF(HHV(C,20),1)',
      'MA20_RECLAIM':'trend AND REF(C,1)<=REF(MA(C,20),1) AND C>MA(C,20) AND C>REF(H,1)',
      'BREAKOUT_RETEST5':'level=REF(HHV(C,20),6); trend AND REF(C,5)>level AND REF(LLV(C,4),1)>=level AND L<=level*1.02 AND C>=level AND C>REF(H,1)',
      'exit':'C<REF(LLV(C,10),1)',
      'state':'no pyramiding; only flat sleeves buy; only held sleeves sell',
      'execution':'signal-close fixed units; 3% limit; next calendar session; missing buys expire; exits persist; adjusted opening gap <= -4.8% blocks exit',
      'cost':'buy 0.13%; sell 0.23% before 2023-08-28, then 0.18%; diagnostic all-in proportional assumptions, not actual broker charges',
      'account':'one initial adjusted capital unit per stock; fractions allowed; no cash transfer or cross-sectional ranking',
      'scope':'all mainboard codes with a valid bar in fixed archive and requested period; prior 113 codes separately identified',
      'periods':['2015-2020','2021-2026-09-04'],
      'screen':'RESEARCH_PRIORITY only if new-code both period NAV gains >0 and both mean closed-trade returns >0 under base AND doubled costs, with >=1000 closes in each period. Not an investment validation certificate.',
      'not_verified':['official historical universe','ST/delisting treatment','raw-RMB lot sizes','cash dividends','legal price limits','auction queue','Tonghuashun native compilation'],
      'no_optimization':True,'trade_ready':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);args.work.mkdir(parents=True,exist_ok=True)
    config=json.loads(args.source.read_text());plan=rule_record()
    if (config['requested_start'],config['requested_end'])!=(START,END): raise ValueError('Scope changed')
    plan['source']=config
    (args.output/'frozen_plan.json').write_text(json.dumps(plan,indent=2,ensure_ascii=False))
    from verify_data import download,verify_identity
    archive=args.work/'qlib_bin.tar.gz'
    if not archive.exists(): download(config['archive_url'],archive,config['archive_size'],config['archive_sha256'])
    verify_identity(archive,config['archive_size'],config['archive_sha256'])
    days,intervals,raw,decode=load_archive(archive,END)
    dates=np.array(days);start=int(np.searchsorted(dates,START));outdays=dates[start:]
    prior=set(json.loads((Path(__file__).parent/'prior_codes.json').read_text()))
    costs=np.where(dates<'2023-08-28',.0023,.0018)
    groups=('all','new_codes','prior_codes');specs=[(r,s) for r in RULES for s in SCENARIOS]+[('BUY_HOLD','base')]
    sums={(r,s,g):np.zeros(len(outdays)) for r,s in specs for g in groups}
    exposures={k:np.zeros(len(outdays)) for k in sums}
    counts={g:0 for g in groups};stock_rows=[];coverage=[];trade_stats={k:[[],[]] for k in sums}
    prefix_checks=0;trade_count=0
    with gzip.open(args.output/'trades.csv.gz','wt',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['rule','scenario','symbol','cohort','buy_signal','buy_date','sell_signal','sell_date','buy_price_normalized','sell_price_normalized','units','entry_total_cost','net_pnl_units','net_return'])
        for j,symbol in enumerate(sorted(intervals)):
            bars=decode_bars(raw[symbol],days,intervals[symbol],decode)
            valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1)
            ids=np.flatnonzero(valid);inperiod=ids[ids>=start]
            cohort='prior_codes' if symbol in prior else 'new_codes'
            coverage.append({'symbol':symbol,'cohort':cohort,'valid_bars':len(inperiod),
               'first':days[inperiod[0]] if len(inperiod) else '',
               'last':days[inperiod[-1]] if len(inperiod) else '',
               'mature_bars':int(((np.arange(len(ids))>=120)&(ids>=start)).sum())})
            if not len(inperiod): continue
            counts['all']+=1;counts[cohort]+=1
            df=pd.DataFrame(bars[ids],columns=['open','high','low','close','volume'])
            features=signals(df);dense={k:np.zeros(len(days),dtype=bool) for k in features}
            for k in features: dense[k][ids]=features[k]
            # Each symbol, two fixed calendar truncations; never chosen by profitability.
            for cutoff in ('2020-12-31','2023-12-29'):
                length=int((dates[ids]<=cutoff).sum());short=signals(df.iloc[:length])
                for k in features:
                    if not np.array_equal(features[k][:length],short[k]): raise AssertionError('Future-sensitive signal')
                prefix_checks+=1
            for rule,scenario in specs:
                multiple,delay=SCENARIOS[scenario]
                buy=dense['ELIGIBLE'] if rule=='BUY_HOLD' else dense[rule]
                sell=np.zeros(len(days),dtype=bool) if rule=='BUY_HOLD' else dense['EXIT10']
                res=simulate(bars,buy,sell,costs,start,multiple,delay)
                final=float(res['nav'][-1]);stale=bool(res['units'] and res['last_quote']<len(days)-21)
                stock_rows.append({'rule':rule,'scenario':scenario,'symbol':symbol,'cohort':cohort,
                  'final_nav':final,'max_drawdown':mdd(res['nav']), 'entries':res['entries'],
                  'closed_trades':len(res['trades']),'final_cash':res['cash'],
                  'final_units':res['units'],'final_mark':res['mark'],
                  'open_entry_cost':res['open_entry_cost'],'open_entry_price':res['open_entry_price'],
                  'open_entry_date':days[res['open_entry_index']] if res['open_entry_index']>=0 else '',
                  'stale_open':stale,'stale_value':res['units']*res['mark'] if stale else 0.,
                  'cancelled_buys':res['cancelled'],'blocked_sell_days':res['blocked_sells']})
                for g in ('all',cohort):
                    key=rule,scenario,g;sums[key]+=res['nav'];exposures[key]+=res['exposure']
                for t in res['trades']:
                    writer.writerow([rule,scenario,symbol,cohort]+[days[int(x)] for x in t[:4]]+list(t[4:]))
                    trade_count+=1
                    block=0 if days[t[3]]<'2021-01-01' else 1
                    for g in ('all',cohort): trade_stats[rule,scenario,g][block].append(t[9])
            if (j+1)%250==0: print(f'Computed {j+1}/{len(intervals)} codes; saved {trade_count} completed scenario-trades',flush=True)
    stocks=pd.DataFrame(stock_rows);stocks.to_csv(args.output/'per_stock.csv.gz',index=False,compression='gzip')
    pd.DataFrame(coverage).to_csv(args.output/'coverage.csv',index=False)
    summary=[];years=[]
    cut=int(np.searchsorted(outdays,'2021-01-01'))
    with gzip.open(args.output/'equity.csv.gz','wt',newline='') as file:
        writer=csv.writer(file);writer.writerow(['rule','scenario','cohort','date','nav','mean_sleeve_exposure'])
        for (rule,scenario,g),values in sums.items():
            if not counts[g]: continue
            nav=values/counts[g];exp=exposures[rule,scenario,g]/counts[g]
            for day,v,e in zip(outdays,nav,exp):writer.writerow([rule,scenario,g,day,v,e])
            mask=(stocks.rule==rule)&(stocks.scenario==scenario)
            if g!='all':mask&=stocks.cohort==g
            ss=stocks[mask];stats=trade_stats[rule,scenario,g];all_ret=np.array(stats[0]+stats[1])
            early=np.array(stats[0]);late=np.array(stats[1])
            row={'rule':rule,'scenario':scenario,'cohort':g,'codes':counts[g],
              'return':float(nav[-1]-1),'max_drawdown':mdd(nav),
              'early_return':float(nav[cut-1]-1),'late_return':float(nav[-1]/nav[cut-1]-1),
              'closed_trades':len(all_ret),'win_rate':float((all_ret>0).mean()) if len(all_ret) else None,
              'mean_trade_return':float(all_ret.mean()) if len(all_ret) else None,
              'median_trade_return':float(np.median(all_ret)) if len(all_ret) else None,
              'profit_factor_equal_trade':float(all_ret[all_ret>0].sum()/-all_ret[all_ret<0].sum()) if np.any(all_ret<0) else None,
              'early_closes':len(early),'late_closes':len(late),
              'early_mean_trade':float(early.mean()) if len(early) else None,
              'late_mean_trade':float(late.mean()) if len(late) else None,
              'profitable_sleeve_fraction':float((ss.final_nav>1).mean()),
              'median_sleeve_return':float(ss.final_nav.median()-1),
              'mean_sleeve_exposure':float(exp.mean()),'stale_open_sleeves':int(ss.stale_open.sum()),
              'stale_zero_value_return':float(nav[-1]-ss.stale_value.sum()/counts[g]-1)}
            summary.append(row)
            for year in sorted(set(day[:4] for day in outdays)):
                idx=np.flatnonzero(np.char.startswith(outdays,year));a,b=idx[0],idx[-1]
                before=nav[a-1] if a else 1.
                years.append({'rule':rule,'scenario':scenario,'cohort':g,'year':year,
                    'return':float(nav[b]/before-1),'max_drawdown':mdd(nav[a:b+1]/before),'days':len(idx)})
    pd.DataFrame(years).to_csv(args.output/'yearly.csv',index=False)
    priority=[]
    for rule in RULES:
        ok=True
        for scenario in ('base','double_cost'):
            row=next(r for r in summary if (r['rule'],r['scenario'],r['cohort'])==(rule,scenario,'new_codes'))
            ok &= (row['early_return']>0 and row['late_return']>0
                and row['early_mean_trade'] is not None and row['early_mean_trade']>0
                and row['late_mean_trade'] is not None and row['late_mean_trade']>0
                and row['early_closes']>=1000 and row['late_closes']>=1000)
        if ok:priority.append(rule)
    payload={'finished_at':datetime.now(timezone.utc).isoformat(),'counts':counts,
      'inventory_codes':len(intervals),'period_start':outdays[0],'period_end':outdays[-1],
      'valid_bars':sum(r['valid_bars'] for r in coverage),'signal_prefix_checks':prefix_checks,
      'scenario_trade_rows':trade_count,'summaries':summary,'research_priority':priority,
      'official_market_coverage':None,'native_ths_verified':False,'trade_ready':False,
      'note':'Independent unit-capital sleeves; adjusted units; retained stale marks; not a feasible investment portfolio. Earlier research-exposed dates remain exposed.'}
    (args.output/'summary.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False))
    lines=['# Three frozen entry rules: expanded mainboard diagnostics','',
      f"Actual input: {counts['all']} codes; {counts['new_codes']} outside prior 113; {payload['valid_bars']:,} bars.",
      'Independent initial unit per code; fractional adjusted units. Not a tradable aggregate portfolio.',
      'No optimization. All results below use previously untested codes; dates are retrospective.',
      '', '| Rule | Scenario | Total return | Max drawdown | 2015-2020 | 2021-cutoff | Trades | Win rate |',
      '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        if r['cohort']!='new_codes':continue
        win='n/a' if r['win_rate'] is None else f"{r['win_rate']:.2%}"
        lines.append(f"|{r['rule']}|{r['scenario']}|{r['return']:.2%}|{r['max_drawdown']:.2%}|{r['early_return']:.2%}|{r['late_return']:.2%}|{r['closed_trades']}|{win}|")
    lines+=['',f'Research-priority candidates: {priority}. Trade ready: FALSE.',
      'Limitations: official dynamic universe, ST/delist treatment, raw RMB lot sizes, corporate action cash flows, auction fills and native Tonghuashun compilation remain unverified.',
      'Stale holdings are marked at last quote. A separate complete write-down stress is recorded; no delisting recovery is invented.',
      'Period gains come from one continuous sleeve series, not separately reset accounts. Trades are grouped by exit date; they are not statistically independent.',
      f"Signal-prefix checks: {prefix_checks}; stored scenario-trades: {trade_count} (overlapping across rules/scenarios)."]
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in payload.items() if k!='summaries'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
