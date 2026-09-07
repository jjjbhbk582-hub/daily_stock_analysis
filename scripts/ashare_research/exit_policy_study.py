"""Fixed-entry exit-policy diagnostic. Research units, not native THS or live trades."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import lzma
import math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from formula_study import load_archive, decode_bars, simulate, mdd
from rsi_factorial import audit_account, TRADE_HEADER
from verify_data import download, verify_identity

RULES=('D0','D1','D2','D3')
PERIODS={'older_transfer':('2001-01-01','2008-12-31'),
         'early':('2009-01-01','2014-12-31'),
         'middle':('2015-01-01','2020-12-31'),
         'recent':('2021-01-01','2026-09-04')}
SCENARIOS={'base':(1.,1,-.048),'double_cost':(2.,1,-.048),
           'delay2':(1.,2,-.048),'gap_unblocked':(1.,1,-math.inf)}


def indicators(frame):
    c=frame.close;d=c.diff().fillna(0.)
    u=d.clip(lower=0).ewm(alpha=1/6,adjust=False).mean()
    v=d.abs().ewm(alpha=1/6,adjust=False).mean()
    r=(100*u/v.replace(0,np.nan)).fillna(50.)
    ready=np.arange(len(c))>=120
    buy=((r.shift(1)<20)&(r>r.shift(1))&(c>c.shift(1))).to_numpy()&ready
    profit=(r>=60).to_numpy()&ready
    low=(c<c.rolling(10).min().shift(1)).to_numpy()&ready
    tr=pd.concat([frame.high-frame.low,(frame.high-c.shift(1)).abs(),
                  (frame.low-c.shift(1)).abs()],axis=1).max(axis=1)
    return buy,profit,low,tr.rolling(14).mean().to_numpy()


def simulate_exit(bars,buy,profit,low,atr,costs,start,rule,multiple=1.,delay=1,gap=-.048):
    n=len(bars)
    if rule not in RULES or delay not in (1,2) or not 0<=start<n or multiple<=0:
        raise ValueError('Invalid fixed experiment setting')
    if bars.shape!=(n,5) or any(len(x)!=n for x in (buy,profit,low,atr,costs)):
        raise ValueError('Input shapes differ')
    valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1)
    o,c=bars[:,0],bars[:,3];previous=np.flatnonzero(valid[:start])
    mark=float(c[previous[-1]]) if len(previous) else math.nan
    last_quote=int(previous[-1]) if len(previous) else -1
    cash=1.;units=0.;buyfee=.0013*multiple
    pending_buy=pending_sell=entry=None
    stop=0.;mae=0.;trades=[];details=[]
    entries=cancelled=blocked=0
    nav=np.empty(n-start);exposure=np.empty(n-start)
    for i in range(start,n):
        if valid[i]:
            if units>0 and pending_sell is not None and i>=pending_sell[0]:
                if o[i]/mark-1<=gap:
                    blocked+=1
                else:
                    proceeds=units*o[i]*(1-float(costs[i])*multiple);basis=entry[3]
                    trades.append((entry[0],entry[1],pending_sell[1],i,entry[2],float(o[i]),
                                   units,basis,proceeds-basis,proceeds/basis-1))
                    details.append((pending_sell[2],i-entry[1],mae,pending_sell[3],stop))
                    cash+=proceeds;units=0.;entry=None;pending_sell=None
            if pending_buy is not None and pending_buy[0]==i:
                _,limit,q,sig=pending_buy;spend=q*o[i]*(1+buyfee)
                if o[i]<=limit and spend<=cash+1e-12 and units==0:
                    cash-=spend;units=q;entries+=1;entry=(sig,i,float(o[i]),spend)
                    stop=float(o[i])*.92 if rule=='D2' else (
                        max(0.,float(o[i])-2*float(atr[sig])) if rule=='D3' else 0.)
                    mae=0.
                else:cancelled+=1
                pending_buy=None
            mark=float(c[i]);last_quote=i
            if units:mae=min(mae,mark/entry[2]-1)
        elif pending_buy is not None and pending_buy[0]==i:
            cancelled+=1;pending_buy=None
        value=units*mark if units else 0.
        nav[i-start]=cash+value;exposure[i-start]=value/nav[i-start]
        if units>0 and pending_sell is None:
            reason=int(valid[i] and profit[i])
            if rule=='D0':reason|=2*int(valid[i] and low[i])
            else:
                reason|=4*int(i-entry[1]+1>=10)
                if rule=='D2':reason|=8*int(valid[i] and mark<=stop)
                if rule=='D3':reason|=16*int(valid[i] and mark<=stop)
            if reason:
                pending_sell=(i+delay,i,reason,mark/entry[2]-1 if valid[i] else math.nan)
        elif units==0 and pending_buy is None and valid[i] and buy[i]:
            if rule=='D3' and not (np.isfinite(atr[i]) and atr[i]>=0):
                raise ValueError('Signal-day ATR unavailable')
            limit=mark*1.03;quantity=cash/(limit*(1+buyfee))
            pending_buy=(i+delay,limit,quantity,i)
        if cash < -1e-10:raise AssertionError('Negative cash')
    return dict(nav=nav,exposure=exposure,trades=trades,details=details,cash=cash,
        units=units,mark=mark,last_quote=last_quote,entries=entries,cancelled=cancelled,
        blocked_sells=blocked,open_entry_cost=entry[3] if entry else 0.,
        open_entry_price=entry[2] if entry else 0.,open_entry_index=entry[1] if entry else -1)


def main():
    p=argparse.ArgumentParser()
    for name in ('source','work','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    config=json.loads(a.source.read_text());plan=Path(__file__).with_name('EXIT_POLICY_PLAN.md').read_text()
    (a.output/'plan.md').write_text(plan)
    archive=a.work/'qlib_bin.tar.gz'
    if not archive.exists():download(config['archive_url'],archive,config['archive_size'],config['archive_sha256'])
    verify_identity(archive,config['archive_size'],config['archive_sha256'])
    days,intervals,raw,decode=load_archive(archive,config['requested_end'])
    dates=np.array(days);costs=np.where(dates<'2023-08-28',.0023,.0018)
    bounds={k:(int(np.searchsorted(dates,s)),int(np.searchsorted(dates,e,side='right'))) for k,(s,e) in PERIODS.items()}
    sums={};exposure={};stats={};counts={k:0 for k in PERIODS}
    for period,(left,right) in bounds.items():
        for rule in RULES:
            for scenario in SCENARIOS:
                key=(period,rule,scenario);sums[key]=np.zeros(right-left);exposure[key]=np.zeros(right-left)
                stats[key]=[0,0,0.,0.,0.,0.,0.]
    stocks=[];coverage=[];reasonstats={};prefixes=accounts=total=base_rows=legacy_checks=0
    with lzma.open(a.output/'base_trades.csv.xz','wt',preset=6,newline='') as ts,\
         lzma.open(a.output/'base_exit_masks.bin.xz','wb',preset=6) as es:
        tw=csv.writer(ts);tw.writerow(TRADE_HEADER)
        for num,symbol in enumerate(sorted(intervals),1):
            b=decode_bars(raw[symbol],days,intervals[symbol],decode)
            valid=np.isfinite(b).all(axis=1)&(b>0).all(axis=1);ids=np.flatnonzero(valid)
            f=pd.DataFrame(b[ids],columns=['open','high','low','close','volume'])
            flags=indicators(f)
            for cutoff in ('2008-12-31','2014-12-31','2020-12-31'):
                n=int(np.searchsorted(dates[ids],cutoff,side='right'));short=indicators(f.iloc[:n])
                for x,y in zip(flags,short):np.testing.assert_array_equal(x[:n],y)
                prefixes+=1
            dense=[]
            for j,x in enumerate(flags):
                v=np.full(len(days),np.nan) if j==3 else np.zeros(len(days),bool)
                v[ids]=x;dense.append(v)
            for period,(left,right) in bounds.items():
                inside=(ids>=left)&(ids<right);n=int(inside.sum())
                coverage.append([period,symbol,n,int((inside&(np.arange(len(ids))>=120)).sum())])
                if not n:continue
                counts[period]+=1
                for rule in RULES:
                    for scenario,(mul,delay,gap) in SCENARIOS.items():
                        key=(period,rule,scenario)
                        res=simulate_exit(b[:right],*(x[:right] for x in dense),costs[:right],left,rule,mul,delay,gap)
                        err=audit_account(res,b,costs,mul);accounts+=1
                        if rule=='D0' and scenario!='gap_unblocked' and num%113==0:
                            old=simulate(b[:right],dense[0][:right],(dense[1]|dense[2])[:right],costs[:right],left,mul,delay)
                            np.testing.assert_array_equal(res['nav'],old['nav'])
                            assert res['trades']==old['trades'];legacy_checks+=1
                        sums[key]+=res['nav'];exposure[key]+=res['exposure'];st=stats[key]
                        for tr,detail in zip(res['trades'],res['details']):
                            sig,bi,ss,si,bp,sp,q,basis,pnl,ret=tr;mask,held,mae,sigr,stop=detail
                            st[0]+=1;st[1]+=int(ret>0);st[2]+=ret;st[3]+=max(pnl,0.);st[4]+=max(-pnl,0.)
                            st[5]+=held;st[6]=min(st[6],ret);total+=1
                            if scenario=='base':
                                tw.writerow([period,rule,scenario,symbol,days[sig],days[bi],days[ss],days[si],bp,sp,q,basis])
                                es.write(bytes([mask]));base_rows+=1
                                rr=reasonstats.setdefault((period,rule,mask),[0,0,0.,0.,0.,0.])
                                rr[0]+=1;rr[1]+=int(ret>0);rr[2]+=ret;rr[3]+=pnl;rr[4]+=held;rr[5]+=mae
                        stale=bool(res['units'] and right-1-res['last_quote']>=20)
                        stocks.append([period,rule,scenario,symbol,float(res['nav'][-1]),res['cash'],res['units'],res['mark'],
                            res['open_entry_cost'],len(res['trades']),res['entries'],res['cancelled'],res['blocked_sells'],
                            res['units']*res['mark'] if stale else 0.,err,mdd(res['nav'])])
            if num%500==0:print(f'Processed {num}/{len(intervals)}; accounts {accounts}; saved base trades {base_rows}',flush=True)
    cols=['period','rule','scenario','symbol','final_nav','cash','units','mark','open_entry_cost','closed_trades','entries',
          'cancelled_buys','blocked_sell_days','stale_value','audit_error','sleeve_max_drawdown']
    sdf=pd.DataFrame(stocks,columns=cols);sdf.to_csv(a.output/'per_stock.csv.xz',index=False)
    pd.DataFrame(coverage,columns=['period','symbol','valid_bars','mature_bars']).to_csv(a.output/'coverage.csv.xz',index=False)
    summary=[];years=[]
    with lzma.open(a.output/'equity.csv.xz','wt',preset=6,newline='') as out:
        w=csv.writer(out);w.writerow(['period','rule','scenario','date','nav','mean_sleeve_exposure'])
        for key,values in sums.items():
            period,rule,scenario=key;left,right=bounds[period];nav=values/counts[period];ex=exposure[key]/counts[period];st=stats[key]
            sub=sdf[sdf.period.eq(period)&sdf.rule.eq(rule)&sdf.scenario.eq(scenario)]
            for day,n,e in zip(dates[left:right],nav,ex):w.writerow([period,rule,scenario,day,n,e])
            summary.append(dict(period=period,rule=rule,scenario=scenario,codes=counts[period],return_total=float(nav[-1]-1),
                max_drawdown=mdd(nav),closed_trades=int(st[0]),win_rate=st[1]/st[0] if st[0] else None,
                mean_trade_return=st[2]/st[0] if st[0] else None,profit_factor=st[3]/st[4] if st[4] else None,
                mean_hold_sessions=st[5]/st[0] if st[0] else None,worst_trade_return=st[6],mean_sleeve_exposure=float(ex.mean()),
                median_sleeve_return=float(sub.final_nav.median()-1),profitable_fraction=float((sub.final_nav>1).mean()),
                stale_zero_return=float(nav[-1]-1-sub.stale_value.sum()/counts[period]),max_audit_error=float(sub.audit_error.max()),
                median_sleeve_drawdown=float(sub.sleeve_max_drawdown.median())))
            for year in sorted(set(d[:4] for d in days[left:right])):
                ii=np.flatnonzero(np.char.startswith(dates[left:right],year));first,last=ii[0],ii[-1]
                before=nav[first-1] if first else 1.
                years.append([period,rule,scenario,year,float(nav[last]/before-1)])
    table=pd.DataFrame(summary);table.to_csv(a.output/'summary.csv',index=False)
    pd.DataFrame(years,columns=['period','rule','scenario','year','return_total']).to_csv(a.output/'yearly.csv',index=False)
    rr=[]
    for (period,rule,mask),st in reasonstats.items():
        rr.append([period,rule,mask,st[0],st[1]/st[0],st[2]/st[0],st[3],st[4]/st[0],st[5]/st[0]])
    pd.DataFrame(rr,columns=['period','rule','reason_mask','trades','win_rate','mean_net_return','net_pnl_units','mean_held_sessions','mean_worst_close_return']).to_csv(a.output/'exit_reasons.csv',index=False)
    gates={}
    for rule in RULES:
        rows=table[table.rule.eq(rule)&table.scenario.isin(['base','double_cost'])]
        gates[rule]=bool(len(rows)==8 and ((rows.return_total>0)&(rows.stale_zero_return>0)&(rows.mean_trade_return>0)&(rows.closed_trades>=1000)).all())
    result=dict(study='RSI6_EXIT_POLICY_V1',finished_at_utc=datetime.now(timezone.utc).isoformat(),counts=counts,
        quote_rows=int(sum(x[2] for x in coverage)),unique_codes=len({x[1] for x in coverage if x[2]}),
        audited_accounts=accounts,all_scenario_trades=total,saved_base_trades=base_rows,pressure_trade_files_saved=False,
        signal_prefix_checks=prefixes,legacy_exact_checks=legacy_checks,gates=gates,
        gate_is_heuristic=True,D1_diagnostic_only=True,all_periods_previously_exposed=True,native_ths_verified=False,trade_ready=False,
        source=config,plan_sha256=hashlib.sha256(plan.encode()).hexdigest())
    (a.output/'result.json').write_text(json.dumps(result,indent=2))
    lines=['# Fixed RSI6 entry, four exit policies','', 'Research units only; all periods were previously inspected. No native or trading certification.','',
           '|Period|Policy|Scenario|Cumulative return|Drawdown|Win rate|Trades|','|---|---|---|---:|---:|---:|---:|']
    for r in summary:lines.append(f"|{r['period']}|{r['rule']}|{r['scenario']}|{r['return_total']:.2%}|{r['max_drawdown']:.2%}|{r['win_rate']:.2%}|{r['closed_trades']}|")
    lines+=['','Heuristic screens: '+json.dumps(gates),'D1 has no price stop; diagnostic only. Stop levels do not guarantee fills or bound losses.']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
