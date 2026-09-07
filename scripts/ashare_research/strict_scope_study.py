"""Frozen mainboard/non-ST scope acceptance diagnostic, no parameter selection."""
from __future__ import annotations
import argparse,csv,hashlib,json,lzma
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from formula_study import load_archive,decode_bars,mdd
from exit_policy_study import indicators,simulate_exit,PERIODS
from rsi_factorial import audit_account,TRADE_HEADER
from verify_data import download,verify_identity,is_mainboard
from strict_mainboard_scope import simulate_scope

CONFIGS={'previous_signal_only':('signal_only',1.,1),
         'strict':('strict',1.,1),'strict_double':('strict',2.,1),'strict_delay':('strict',1.,2)}
RULES=('D0','D2')
FIELDS=['open','high','low','close','volume']


def main():
    p=argparse.ArgumentParser()
    for name in ('seed','source','work','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    config=json.loads(a.source.read_text());plan=Path(__file__).with_name('STRICT_SCOPE_PLAN.md').read_text()
    (a.output/'plan.md').write_text(plan)
    seeds=list(a.seed.rglob('merged_status/states.npz'))
    if len(seeds)!=1:raise ValueError('Need exactly one fixed state matrix')
    states_path=seeds[0];seed=states_path.parent.parent
    if hashlib.sha256(states_path.read_bytes()).hexdigest()!='1fb6fb4d270b9c490c17524d49fca86e8b981333dce7017ccd066d8274b83906':
        raise ValueError('Fixed state matrix identity mismatch')
    accepted_records=json.loads((seed/'merged_status/accepted.json').read_text())
    accepted={x['symbol'] for x in accepted_records if x['status']=='received'}
    with np.load(states_path,allow_pickle=False) as z:
        state_days=list(z['days']);symbols=list(z['symbols']);sts=z['isST'];trades=z['tradestatus']
    if len(accepted)!=1649:raise ValueError('Unexpected accepted seed count')
    if any(not is_mainboard(s) for s in accepted):raise ValueError('Excluded board in seed')
    index={s:i for i,s in enumerate(symbols)}
    archive=a.work/'qlib_bin.tar.gz'
    if not archive.exists():download(config['archive_url'],archive,config['archive_size'],config['archive_sha256'])
    verify_identity(archive,config['archive_size'],config['archive_sha256'])
    days,intervals,raw,decode=load_archive(archive,config['requested_end'])
    if state_days!=days:raise ValueError('Status and price calendars differ')
    dates=np.array(days);cost=np.where(dates<'2023-08-28',.0023,.0018)
    bounds={k:(int(np.searchsorted(dates,s)),int(np.searchsorted(dates,e,side='right'))) for k,(s,e) in PERIODS.items()}
    sums={};exp={};stats={};counts={k:0 for k in PERIODS};coverage=[];stocks=[];legacy=prefixes=accounts=saved=0
    for per,(l,r) in bounds.items():
        for rule in RULES:
            for cfg in CONFIGS:
                k=per,rule,cfg;sums[k]=np.zeros(r-l);exp[k]=np.zeros(r-l);stats[k]=[0,0,0.,0.,0.,0,0,0]
    old=pd.read_csv(seed/'diagnostic/per_stock.csv.xz')
    old=old[old.config=='normal'].set_index(['period','rule','symbol'])
    with lzma.open(a.output/'base_trades.csv.xz','wt',preset=6,newline='') as tf,\
         lzma.open(a.output/'strict_events.csv.xz','wt',preset=6,newline='') as ef,\
         lzma.open(a.output/'strict_orders.csv.xz','wt',preset=6,newline='') as of:
        tw=csv.writer(tf);tw.writerow(TRADE_HEADER)
        ew=csv.writer(ef);ew.writerow(['period','rule','symbol','date','event','reference_date','isST','tradestatus','reason_mask'])
        ow=csv.writer(of);ow.writerow(['period','rule','symbol','signal_date','due_date','limit','units','outcome'])
        for num,sym in enumerate(sorted(accepted),1):
            b=decode_bars(raw[sym],days,intervals[sym],decode);valid=np.isfinite(b).all(axis=1)&(b>0).all(axis=1)
            ids=np.flatnonzero(valid);f=pd.DataFrame(b[ids],columns=FIELDS);flags=indicators(f)
            dense=[]
            for j,fl in enumerate(flags):
                x=np.full(len(days),np.nan) if j==3 else np.zeros(len(days),bool);x[ids]=fl;dense.append(x)
            st=sts[index[sym]];tr=trades[index[sym]]
            for per,(l,r) in bounds.items():
                vi=valid[l:r];bars_count=int(vi.sum())
                if not bars_count:continue
                counts[per]+=1;known=(st[l:r]>=0)&(tr[l:r]>=0)
                coverage.append([per,sym,bars_count,int((vi&known).sum()),int((vi&(st[l:r]==1)).sum())])
                for rule in RULES:
                    for cfg,(mode,mul,delay) in CONFIGS.items():
                        out=simulate_scope(b[:r],*(x[:r] for x in dense),cost[:r],l,rule,st[:r],tr[:r],sym,mode,mul,delay)
                        err=audit_account(out,b,cost,mul);accounts+=1
                        if cfg=='previous_signal_only':
                            prev=simulate_exit(b[:r],(dense[0]&(st==0)&(tr==1))[:r],dense[1][:r],dense[2][:r],dense[3][:r],cost[:r],l,rule)
                            np.testing.assert_array_equal(out['nav'],prev['nav']);assert out['trades']==prev['trades'];legacy+=1
                            row=old.loc[(per,rule,sym)];np.testing.assert_allclose(out['nav'][-1],row.final_nav,atol=1e-12)
                        if cfg=='strict':
                            for i,event,ref,s,t,reason in out['events']:
                                if event=='buy':assert s==0 and t==1 and st[ref]==0 and tr[ref]==1
                                ew.writerow([per,rule,sym,days[i],event,days[ref],s,t,reason])
                            for q in out['orders']:
                                due=days[q['due']] if q['due']<len(days) else 'BEYOND_CUTOFF'
                                ow.writerow([per,rule,sym,days[q['signal']],due,q['limit'],q['units'],q['outcome']])
                            if num%97==0 and r-l>100:
                                cut=l+(r-l)//2
                                short=simulate_scope(b[:cut],*(x[:cut] for x in dense),cost[:cut],l,rule,st[:cut],tr[:cut],sym)
                                np.testing.assert_array_equal(short['nav'],out['nav'][:cut-l]);prefixes+=1
                        k=per,rule,cfg;sums[k]+=out['nav'];exp[k]+=out['exposure'];stat=stats[k]
                        for x in out['trades']:
                            sig,bi,ss,si,bp,sp,q,basis,pnl,ret=x
                            stat[0]+=1;stat[1]+=int(ret>0);stat[2]+=ret;stat[3]+=max(pnl,0.);stat[4]+=max(-pnl,0.)
                            if cfg in ('previous_signal_only','strict'):
                                tw.writerow([per,rule,cfg,sym,days[sig],days[bi],days[ss],days[si],bp,sp,q,basis]);saved+=1
                        stat[5]+=out['risk_exit_requests'];stat[6]+=out['status_cancelled_buys'];stat[7]+=out['entries']
                        stale=bool(out['units'] and r-1-out['last_quote']>=20)
                        stocks.append([per,rule,cfg,sym,float(out['nav'][-1]),out['cash'],out['units'],out['mark'],
                            out['open_entry_cost'],len(out['trades']),out['entries'],out['status_cancelled_buys'],
                            out['risk_exit_requests'],out['held_st_days'],out['held_unknown_days'],out['pending_ST_exit'],
                            out['open_ST'],mdd(out['nav']),out['units']*out['mark'] if stale else 0.,err])
            if num%250==0:print(f'Strict scope: {num}/1649; audited accounts {accounts}',flush=True)
    cols=['period','rule','config','symbol','final_nav','cash','units','mark','open_entry_cost','closed_trades','entries',
          'status_cancelled_buys','risk_exit_requests','held_st_days','held_unknown_days','pending_ST_exit','open_ST',
          'individual_mdd','stale_value','audit_error']
    sdf=pd.DataFrame(stocks,columns=cols);sdf.to_csv(a.output/'per_stock.csv.xz',index=False)
    pd.DataFrame(coverage,columns=['period','symbol','valid_bars','known_state_bars','st_bars']).to_csv(a.output/'coverage.csv',index=False)
    summary=[];yearly=[]
    with lzma.open(a.output/'equity.csv.xz','wt',preset=6,newline='') as ef:
        ew=csv.writer(ef);ew.writerow(['period','rule','config','date','nav','mean_sleeve_exposure'])
        for k,values in sums.items():
            per,rule,cfg=k;l,r=bounds[per];nav=values/counts[per];ex=exp[k]/counts[per];stat=stats[k]
            sub=sdf[(sdf.period==per)&(sdf.rule==rule)&(sdf.config==cfg)]
            summary.append(dict(period=per,rule=rule,config=cfg,codes=counts[per],return_total=float(nav[-1]-1),max_drawdown=mdd(nav),
                closed_trades=stat[0],win_rate=stat[1]/stat[0] if stat[0] else None,mean_trade_return=stat[2]/stat[0] if stat[0] else None,
                mean_sleeve_exposure=float(ex.mean()),median_individual_mdd=float(sub.individual_mdd.median()),
                median_sleeve_return=float(sub.final_nav.median()-1),profitable_fraction=float((sub.final_nav>1).mean()),
                risk_exit_requests=stat[5],status_cancelled_buys=stat[6],entries=stat[7],
                open_ST=int(sub.open_ST.sum()),pending_ST_exit=int(sub.pending_ST_exit.sum()),
                stale_zero_return=float(nav[-1]-1-sub.stale_value.sum()/counts[per])))
            ew.writerows([per,rule,cfg,day,float(n),float(e)] for day,n,e in zip(days[l:r],nav,ex))
            for yr in sorted(set(d[:4] for d in days[l:r])):
                ix=np.flatnonzero(np.char.startswith(dates[l:r],yr));aa,bb=ix[0],ix[-1]
                yearly.append([per,rule,cfg,yr,float(nav[bb]/(nav[aa-1] if aa else 1)-1)])
    pd.DataFrame(summary).to_csv(a.output/'summary.csv',index=False)
    pd.DataFrame(yearly,columns=['period','rule','config','year','return_total']).to_csv(a.output/'yearly.csv',index=False)
    result=dict(study='STRICT_MAINBOARD_SCOPE_V1',finished_at_utc=datetime.now(timezone.utc).isoformat(),
        accepted_status_codes=len(accepted),inventory_codes=len(intervals),counts=counts,audited_accounts=accounts,
        saved_base_trades=saved,legacy_account_parity_checks=legacy,prefix_checks=prefixes,
        all_periods_already_observed=True,no_parameter_search=True,new_status_downloads=0,
        native_ths_verified=False,real_account_verified=False,publication_timestamps_verified=False,trade_ready=False,
        source=config,status_seed_run=34126772439,status_seed_artifact=10021194677,
        status_matrix_sha256=hashlib.sha256(states_path.read_bytes()).hexdigest(),plan_sha256=hashlib.sha256(plan.encode()).hexdigest())
    (a.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    lines=['# Strict mainboard / non-ST diagnostic','',
       'Only status-covered identical cohorts. This is not full-market coverage, native software verification, or a real RMB account.','',
       '|Period|Rule|Config|Cumulative return|Close drawdown|Risk requests|Status-cancelled orders|',
       '|---|---|---|---:|---:|---:|---:|']
    for x in summary:lines.append(f"|{x['period']}|{x['rule']}|{x['config']}|{x['return_total']:.3%}|{x['max_drawdown']:.3%}|{x['risk_exit_requests']}|{x['status_cancelled_buys']}|")
    lines+=['','No strategy promotion. The flags are effective-date histories; announcement availability is not proven.',
        'All previous_signal_only/strict base trades, strict base order decisions and events retained. Pressure scenarios retain per-stock outputs and cloud account audit only.',
        'Same legacy 4.8% negative-gap execution proxy; actual legal limits, queueing, capacity, real shares/dividends and minimum commission remain unverified.']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
