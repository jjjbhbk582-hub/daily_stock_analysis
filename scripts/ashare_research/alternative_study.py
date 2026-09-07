"""Finite alternative-signal experiment. No optimization, broker, or native-THS claim.
Reuses the frozen normalized-unit execution engine; not a real cash-share account.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import lzma
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from formula_study import load_archive, decode_bars, simulate, mdd
from verify_data import download, verify_identity

RULES=('BREAKOUT20','SLOW120','RSI6_RECOVERY','BAND_RECOVERY')
PERIODS={'development':('2015-01-01','2020-12-31'),
         'exposed_recent':('2021-01-01','2026-09-04'),
         'historical_check':('2009-01-01','2014-12-31')}
SCENARIOS={'base':(1.,1),'double_cost':(2.,1),'delay2':(1.,2)}
COLUMNS=['open','high','low','close','volume']


def alternative_signals(df):
    c=df['close'];m20=c.rolling(20).mean();m60=c.rolling(60).mean()
    m120=c.rolling(120).mean();m10=c.rolling(10).mean()
    ready=pd.Series(np.arange(len(c))>=120,index=c.index)
    exit10=c<c.rolling(10).min().shift(1)
    delta=c.diff().fillna(0.)
    up=delta.clip(lower=0).ewm(alpha=1/6,adjust=False).mean()
    distance=delta.abs().ewm(alpha=1/6,adjust=False).mean()
    rsi=(100*up/distance.replace(0,np.nan)).fillna(50.)
    lower=m20-2*c.rolling(20).std(ddof=0)
    flags={
      'BREAKOUT20_BUY':(c>m60)&(m60>m60.shift(5))&(c>c.rolling(20).max().shift(1)),
      'BREAKOUT20_SELL':exit10,
      'SLOW120_BUY':(m20>m120)&(c>m120),
      'SLOW120_SELL':m20<m120,
      'RSI6_RECOVERY_BUY':(rsi.shift(1)<20)&(rsi>rsi.shift(1))&(c>c.shift(1)),
      'RSI6_RECOVERY_SELL':(rsi>=60)|exit10,
      'BAND_RECOVERY_BUY':(c.shift(1)<lower.shift(1))&(c>lower)&(c>c.shift(1)),
      'BAND_RECOVERY_SELL':(c>=m20)|exit10,
      'ELIGIBLE':ready}
    return {k:(v & ready).fillna(False).to_numpy(bool) for k,v in flags.items()}


def audit_result(res,bars,costs,multiple):
    """Rebuild final cash from immutable trade records, without simulate()."""
    cash=1.;buyfee=.0013*multiple
    for sig,entry,ssig,exit,bp,sp,q,basis,pnl,ret in res['trades']:
        assert sig<entry<=ssig<exit
        np.testing.assert_allclose([bp,sp],[bars[entry,0],bars[exit,0]],rtol=1e-12)
        np.testing.assert_allclose(basis,q*bp*(1+buyfee),rtol=1e-12)
        proceeds=q*sp*(1-costs[exit]*multiple)
        np.testing.assert_allclose([pnl,ret],[proceeds-basis,proceeds/basis-1],atol=1e-11)
        cash+=pnl
    cash-=res['open_entry_cost']
    np.testing.assert_allclose(cash,res['cash'],atol=1e-10)
    final=cash+(res['units']*res['mark'] if res['units'] else 0.)
    np.testing.assert_allclose(final,res['nav'][-1],atol=1e-10)
    assert cash>=-1e-10


def plan():
    return {'id':'ALTERNATIVE_SIGNALS_4_V1','rules':RULES,'period_order':list(PERIODS),
      'periods':PERIODS,'scenarios':SCENARIOS,'warmup':120,
      'BREAKOUT20':'C>MA60 and MA60>REF(MA60,5) and C>REF(HHV(C,20),1); exit C<REF(LLV(C,10),1)',
      'SLOW120':'MA20>MA120 and C>MA120; exit MA20<MA120 (no EXIT10)',
      'RSI6_RECOVERY':'RSI=100*SMA(MAX(C-REF(C,1),0),6,1)/SMA(ABS(C-REF(C,1)),6,1); previous RSI<20, RSI rising, C>previous C; exit RSI>=60 or EXIT10. Recursion starts at zero; zero/zero becomes 50.',
      'BAND_RECOVERY':'LOWER=MA(C,20)-2*population_STD(C,20); previous C<previous LOWER, C>LOWER, C>previous C; exit C>=MA20 or EXIT10.',
      'execution':'unchanged formula_study.simulate: precommitted fractional adjusted units, 3% entry cap, next-calendar-day attempt; missing buy expires; pending exit persists; opening decline at least4.8% blocks exit.',
      'account':'independent initial unit per security; equal initial capital, no cross-stock transfers, no interest, each period starts flat; terminal missing quotes marked stale, not called executed liquidations.',
      'cost':'hypothetical all-in buy .13%; sell .23% before2023-08-28, .18% after; double scenario doubles the hypothetical totals.',
      'screen':'research-priority only: base and double_cost positive NAV return AND positive mean trade return in ALL THREE separate periods, >=1000 closes per period. Not statistical proof, native certification or an executable account.',
      'holdout_boundary':'2009-2014 has not been used for project strategy selection; it is retrospective, not prospective, and dataset universe selection/historical corporate state biases remain. 2015-2026 was already observed.',
      'not_verified':['official historical denominator','PIT ST/delisting','raw RMB lots/dividends','real auction fills','independent entire price source','native Tonghuashun'],
      'trade_ready':False,'no_optimization':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.work.mkdir(parents=True,exist_ok=True);args.output.mkdir(parents=True,exist_ok=True)
    config=json.loads(args.source.read_text());frozen=plan();frozen['source']=config
    (args.output/'plan.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2))
    archive=args.work/'qlib_bin.tar.gz'
    if not archive.exists():download(config['archive_url'],archive,config['archive_size'],config['archive_sha256'])
    verify_identity(archive,config['archive_size'],config['archive_sha256'])
    days,intervals,raw,decode=load_archive(archive,config['requested_end'])
    dates=np.array(days);costs=np.where(dates<'2023-08-28',.0023,.0018)
    specs=[(r,s) for r in RULES for s in SCENARIOS]+[('BUY_HOLD','base')]
    sums={};exp={};count={};stats={};coverage=[];stocks=[];annual=[];summaries=[]
    prefixes=0;audits=0;trade_count=0;errors=[]
    with lzma.open(args.output/'trades.csv.xz','wt',preset=3,newline='') as tf:
        tw=csv.writer(tf);tw.writerow(['period','rule','scenario','symbol','buy_signal','buy_date','sell_signal','sell_date','buy_price','sell_price','units','entry_cost'])
        for period,(begin,end) in PERIODS.items():
            left=int(np.searchsorted(dates,begin));right=int(np.searchsorted(dates,end,side='right'))
            outdays=dates[left:right];count[period]=0
            for r,s in specs:
                key=(period,r,s);sums[key]=np.zeros(right-left);exp[key]=np.zeros(right-left)
                stats[key]=[0,0,0.,0.,0.,0.,0.,0]
            for idx,symbol in enumerate(sorted(intervals)):
                bars=decode_bars(raw[symbol],days,intervals[symbol],decode)[:right]
                valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1)
                ids=np.flatnonzero(valid);within=ids[ids>=left]
                coverage.append([period,symbol,len(within),days[within[0]] if len(within) else '',days[within[-1]] if len(within) else '',int(((np.arange(len(ids))>=120)&(ids>=left)).sum())])
                if not len(within):continue
                count[period]+=1
                frame=pd.DataFrame(bars[ids],columns=COLUMNS);features=alternative_signals(frame)
                shortlen=max(0,len(frame)-73);short=alternative_signals(frame.iloc[:shortlen])
                for k in features:assert np.array_equal(features[k][:shortlen],short[k]),'Future-sensitive signals'
                prefixes+=1
                dense={k:np.zeros(right,bool) for k in features}
                for k in dense:dense[k][ids]=features[k]
                for r,s in specs:
                    key=(period,r,s);mul,delay=SCENARIOS[s]
                    buy=dense['ELIGIBLE'] if r=='BUY_HOLD' else dense[r+'_BUY']
                    sell=np.zeros(right,bool) if r=='BUY_HOLD' else dense[r+'_SELL']
                    res=simulate(bars,buy,sell,costs[:right],left,mul,delay)
                    cash=1.;maxerr=0.
                    for sig,bi,ss,si,bp,sp,q,basis,pnl,ret in res['trades']:
                        assert sig<bi<=ss<si
                        proceeds=q*sp*(1-costs[si]*mul)
                        maxerr=max(maxerr,abs(basis-q*bp*(1+.0013*mul)),abs(pnl-(proceeds-basis)),abs(ret-(proceeds/basis-1)))
                        cash+=pnl
                        tw.writerow([period,r,s,symbol,days[sig],days[bi],days[ss],days[si],bp,sp,q,basis])
                        a=stats[key];a[0]+=1;a[1]+=int(ret>0);a[2]+=ret
                        a[3]+=max(pnl,0.);a[4]+=max(-pnl,0.)
                        trade_count+=1
                    cash-=res['open_entry_cost']
                    maxerr=max(maxerr,abs(cash-res['cash']),abs(cash+(res['units']*res['mark'] if res['units'] else 0.)-res['nav'][-1]))
                    assert maxerr<1e-8,'Ledger reconciliation failed'
                    audits+=1
                    sums[key]+=res['nav'];exp[key]+=res['exposure']
                    stale_days=right-1-res['last_quote'];stale=bool(res['units'] and stale_days>=20)
                    if stale:
                        stats[key][5]+=res['units']*res['mark'];stats[key][6]=max(stats[key][6],stale_days);stats[key][7]+=1
                    stocks.append([period,r,s,symbol,float(res['nav'][-1]),mdd(res['nav']),len(res['trades']),res['cash'],res['units'],res['mark'],res['open_entry_cost'],res['last_quote'],res['entries'],res['cancelled'],maxerr])
                if idx%500==0:print(period,idx,'codes processed; retained trades',trade_count,flush=True)
    with lzma.open(args.output/'equity.csv.xz','wt',preset=3,newline='') as ef:
        ew=csv.writer(ef);ew.writerow(['period','rule','scenario','date','nav','mean_sleeve_exposure'])
        for period,(begin,end) in PERIODS.items():
            left=int(np.searchsorted(dates,begin));right=int(np.searchsorted(dates,end,side='right'));outdays=dates[left:right]
            if count[period]==0:raise ValueError('Empty period')
            for r,s in specs:
                key=(period,r,s);nav=sums[key]/count[period];ex=exp[key]/count[period];st=stats[key]
                rows=[x for x in stocks if x[0:3]==[period,r,s]];rets=np.array([x[4]-1 for x in rows])
                summary={'period':period,'rule':r,'scenario':s,'stocks':count[period],
                  'return':float(nav[-1]-1),'mdd':mdd(nav),'trades':st[0],
                  'win_rate':st[1]/st[0] if st[0] else None,'mean_trade_return':st[2]/st[0] if st[0] else None,
                  'profit_factor_pnl':st[3]/st[4] if st[4] else None,
                  'mean_sleeve_exposure':float(ex.mean()),'median_stock_return':float(np.median(rets)),
                  'profitable_stocks':int((rets>0).sum()),'stale_positions':st[7],
                  'zero_stale_return':float(nav[-1]-1-st[5]/count[period]),'first_day':outdays[0],'last_day':outdays[-1]}
                summaries.append(summary)
                for d,v,e in zip(outdays,nav,ex):ew.writerow([period,r,s,d,v,e])
                prior=1.
                for year in sorted(set(d[:4] for d in outdays)):
                    yy=nav[np.array([d.startswith(year) for d in outdays])]
                    annual.append([period,r,s,year,float(yy[-1]/prior-1),float(np.max(1-yy/np.maximum.accumulate(np.r_[prior,yy])[1:]))]);prior=float(yy[-1])
    pd.DataFrame(coverage,columns=['period','symbol','valid_bars','first','last','mature_bars']).to_csv(args.output/'coverage.csv.xz',index=False)
    pd.DataFrame(stocks,columns=['period','rule','scenario','symbol','final_nav','mdd','trades','cash','units','mark','open_entry_cost','last_quote_index','entries','cancelled','audit_error']).to_csv(args.output/'per_stock.csv.xz',index=False)
    pd.DataFrame(annual,columns=['period','rule','scenario','year','return','mdd_within_year']).to_csv(args.output/'yearly.csv',index=False)
    pd.DataFrame(summaries).to_csv(args.output/'summary.csv',index=False)
    priority=[]
    for r in RULES:
        v=[x for x in summaries if x['rule']==r and x['scenario'] in ('base','double_cost')]
        if len(v)==6 and all(x['return']>0 and (x['mean_trade_return'] or 0)>0 and x['trades']>=1000 for x in v):priority.append(r)
    result={'finished_at':datetime.now(timezone.utc).isoformat(),'period_code_counts':count,'signal_prefix_checks':prefixes,
      'audited_accounts':audits,'retained_trade_rows':trade_count,'research_priority':priority,
      'native_ths_verified':False,'official_historical_market_coverage':None,'trade_ready':False}
    (args.output/'result.json').write_text(json.dumps(result,indent=2))
    text='# Fixed alternatives: retrospective diagnostic\n\nNot an executable real account or native Tonghuashun validation.\n\n'
    text+='|Period|Rule|Return|MDD|Trades|Mean trade|Double-cost return|\n|---|---|---:|---:|---:|---:|---:|\n'
    for x in summaries:
        if x['scenario']!='base' or x['rule']=='BUY_HOLD':continue
        d=next(q for q in summaries if (q['period'],q['rule'],q['scenario'])==(x['period'],x['rule'],'double_cost'))
        text+=f"|{x['period']}|{x['rule']}|{x['return']:.4%}|{x['mdd']:.4%}|{x['trades']}|{x['mean_trade_return']:.4%}|{d['return']:.4%}|\n"
    text+='\nResearch priority only: '+str(priority)+'\n\n2009-2014 is a retrospective, previously untuned period, not prospective evidence. Each period restarts cash. Current-vintage universe, normalized prices, stale marks and hypothetical costs remain limitations.\n'
    (args.output/'report.md').write_text(text)
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()
