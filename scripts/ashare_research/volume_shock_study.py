"""Finite price/volume mechanism comparison. Never a broker or native-THS claim."""
from __future__ import annotations
import argparse,csv,hashlib,json,lzma
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from formula_study import load_archive,decode_bars,mdd
from exit_policy_study import indicators,PERIODS
from rsi_factorial import audit_account,TRADE_HEADER
from strict_mainboard_scope import simulate_scope
from verify_data import download,verify_identity,is_mainboard
from volume_shock_signals import volume_signals,independent_flags,block_interval,FIELDS

RULES=('D0','V0','VH','VL')
SCENARIOS={'base':(1.,1,-.048),'double_cost':(2.,1,-.048),
           'delay2':(1.,2,-.048),'gap_unblocked':(1.,1,-np.inf)}
STATE_SHA='1fb6fb4d270b9c490c17524d49fca86e8b981333dce7017ccd066d8274b83906'

def main():
    p=argparse.ArgumentParser()
    for key in ('seed','source','work','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    plan=Path(__file__).with_name('VOLUME_SHOCK_PLAN.md').read_text()
    (a.output/'plan.md').write_text(plan);cfg=json.loads(a.source.read_text())
    paths=list(a.seed.rglob('merged_status/states.npz'))
    if len(paths)!=1:raise ValueError('Exactly one frozen state matrix required')
    path=paths[0]
    if hashlib.sha256(path.read_bytes()).hexdigest()!=STATE_SHA:raise ValueError('State identity mismatch')
    accepted={x['symbol'] for x in json.loads(path.with_name('accepted.json').read_text()) if x['status']=='received'}
    if len(accepted)!=1649 or not all(map(is_mainboard,accepted)):raise ValueError('Unexpected accepted scope')
    with np.load(path,allow_pickle=False) as z:
        state_days=list(z['days']);state_symbols=list(z['symbols']);sts=z['isST'];trs=z['tradestatus']
    six={str(s):i for i,s in enumerate(state_symbols)}
    archive=a.work/'qlib_bin.tar.gz'
    if not archive.exists():download(cfg['archive_url'],archive,cfg['archive_size'],cfg['archive_sha256'])
    verify_identity(archive,cfg['archive_size'],cfg['archive_sha256'])
    days,intervals,raw,decode=load_archive(archive,cfg['requested_end'])
    if days!=state_days:raise ValueError('State calendar differs')
    dates=np.asarray(days);cost=np.where(dates<'2023-08-28',.0023,.0018)
    bounds={per:(int(np.searchsorted(dates,s)),int(np.searchsorted(dates,e,side='right')))
            for per,(s,e) in PERIODS.items()}
    counts={per:0 for per in PERIODS};sums={};exposures={};stats={};stocks=[];coverage=[]
    samples=set(sorted(accepted,key=lambda s:hashlib.sha256(('VOL_OFFLINE_V1|'+s).encode()).hexdigest())[:12])
    quote_samples={};sample_states={};sample_trade={}
    for per,(l,r) in bounds.items():
        for rule in RULES:
            for scenario in SCENARIOS:
                key=per,rule,scenario;sums[key]=np.zeros(r-l);exposures[key]=np.zeros(r-l);stats[key]=[0,0,0.,0.,0.]
    audits=total_trades=saved=entries=entry_violations=prefixes=signal_tests=signal_mismatches=0
    mismatches=[]
    with lzma.open(a.output/'base_trades.csv.xz','wt',preset=6,newline='') as tf,\
         lzma.open(a.output/'base_events.csv.xz','wt',preset=6,newline='') as ef,\
         lzma.open(a.output/'base_reasons.bin.xz','wb',preset=6) as rf:
        tw=csv.writer(tf);tw.writerow(TRADE_HEADER)
        ew=csv.writer(ef);ew.writerow(['period','rule','symbol','date','event','reference_date','isST','tradestatus','reason_mask'])
        for num,sym in enumerate(sorted(accepted),1):
            bars=decode_bars(raw[sym],days,intervals[sym],decode)
            valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1);ids=np.flatnonzero(valid)
            frame=pd.DataFrame(bars[ids],columns=FIELDS);vs=volume_signals(frame);old=indicators(frame)
            st=sts[six[sym]];tr=trs[six[sym]]
            if sym in samples:
                ref=independent_flags(frame)
                for name,x in ref.items():
                    ii=np.flatnonzero(x!=vs[name]);signal_tests+=len(x);signal_mismatches+=len(ii)
                    for j in ii[:max(0,100-len(mismatches))]:mismatches.append([sym,days[ids[j]],name])
                quote_samples[sym]=bars;sample_states[sym]=st;sample_trade[sym]=tr
            for cutoff in ('2008-12-31','2014-12-31','2020-12-31'):
                n=int(np.searchsorted(dates[ids],cutoff,side='right'));part=volume_signals(frame.iloc[:n])
                for name in ('V0','VH','VL','RECOVER5'):
                    if not np.array_equal(vs[name][:n],part[name]):raise AssertionError('Future-sensitive signal')
                prefixes+=1
            dense={k:np.zeros(len(days),bool) for k in ('D0','D0_TARGET','LOW','V0','VH','VL','RECOVER5')}
            dense['D0'][ids]=old[0];dense['D0_TARGET'][ids]=old[1];dense['LOW'][ids]=old[2]
            atr=np.full(len(days),np.nan);atr[ids]=vs['ATR_PREV']
            for k in ('V0','VH','VL','RECOVER5'):dense[k][ids]=vs[k]
            for per,(l,r) in bounds.items():
                n=int(valid[l:r].sum());coverage.append([per,sym,n,int((valid[l:r]&(st[l:r]>=0)&(tr[l:r]>=0)).sum())])
                if not n:continue
                counts[per]+=1
                for rule in RULES:
                    target=dense['D0_TARGET'] if rule=='D0' else dense['RECOVER5']
                    policy='D0' if rule=='D0' else 'D2'
                    for scenario,(mul,delay,gap) in SCENARIOS.items():
                        key=per,rule,scenario
                        out=simulate_scope(bars[:r],dense[rule][:r],target[:r],dense['LOW'][:r],atr[:r],
                            cost[:r],l,policy,st[:r],tr[:r],sym,'strict',mul,delay,gap)
                        err=audit_account(out,bars,cost,mul);audits+=1
                        sums[key]+=out['nav'];exposures[key]+=out['exposure'];stat=stats[key]
                        for row,detail in zip(out['trades'],out['details']):
                            sig,bi,ss,si,bp,sp,q,basis,pnl,ret=row
                            stat[0]+=1;stat[1]+=int(ret>0);stat[2]+=ret;stat[3]+=max(pnl,0.);stat[4]+=max(-pnl,0.)
                            total_trades+=1
                            if scenario=='base':
                                tw.writerow([per,rule,scenario,sym,days[sig],days[bi],days[ss],days[si],bp,sp,q,basis])
                                rf.write(bytes([detail[0]]));saved+=1
                        for i,event,ref,s,t,reason in out['events']:
                            if event=='buy':
                                entries+=1
                                entry_violations+=int(not(st[ref]==0 and tr[ref]==1 and s==0 and t==1 and is_mainboard(sym)))
                            if scenario=='base':ew.writerow([per,rule,sym,days[i],event,days[ref],s,t,reason])
                        stale=bool(out['units'] and r-1-out['last_quote']>=20)
                        stocks.append([per,rule,scenario,sym,float(out['nav'][-1]),out['cash'],out['units'],out['mark'],
                            out['open_entry_cost'],len(out['trades']),out['entries'],out['cancelled'],out['blocked_sells'],
                            out['units']*out['mark'] if stale else 0.,mdd(out['nav']),err])
            if num%250==0:print(f'Volume study {num}/{len(accepted)}; audited accounts {audits}; saved base trades {saved}',flush=True)
    cols=['period','rule','scenario','symbol','final_nav','cash','units','mark','open_entry_cost','closed_trades',
          'entries','cancelled_buys','blocked_sell_days','stale_value','individual_mdd','audit_error']
    sdf=pd.DataFrame(stocks,columns=cols);sdf.to_csv(a.output/'per_stock.csv.xz',index=False)
    pd.DataFrame(coverage,columns=['period','symbol','valid_bars','known_status_bars']).to_csv(a.output/'coverage.csv',index=False)
    summary=[];annual=[];boot=[]
    with lzma.open(a.output/'equity.csv.xz','wt',preset=6,newline='') as f:
        w=csv.writer(f);w.writerow(['period','rule','scenario','date','nav','mean_sleeve_exposure'])
        for key,values in sums.items():
            per,rule,scenario=key;l,r=bounds[per];nav=values/counts[per];exp=exposures[key]/counts[per];stat=stats[key]
            sub=sdf[(sdf.period==per)&(sdf.rule==rule)&(sdf.scenario==scenario)]
            w.writerows([per,rule,scenario,d,float(v),float(e)] for d,v,e in zip(days[l:r],nav,exp))
            summary.append(dict(period=per,rule=rule,scenario=scenario,codes=counts[per],return_total=float(nav[-1]-1),
                max_drawdown=mdd(nav),closed_trades=stat[0],win_rate=stat[1]/stat[0] if stat[0] else None,
                mean_trade_return=stat[2]/stat[0] if stat[0] else None,profit_factor=stat[3]/stat[4] if stat[4] else None,
                median_sleeve_return=float(sub.final_nav.median()-1),median_individual_mdd=float(sub.individual_mdd.median()),
                profitable_fraction=float((sub.final_nav>1).mean()),mean_sleeve_exposure=float(exp.mean()),
                stale_zero_return=float(nav[-1]-1-sub.stale_value.sum()/counts[per]),max_audit_error=float(sub.audit_error.max())))
            for year in sorted(set(d[:4] for d in days[l:r])):
                ii=np.flatnonzero(np.char.startswith(dates[l:r],year));first,last=ii[0],ii[-1];prior=nav[first-1] if first else 1.
                annual.append([per,rule,scenario,year,float(nav[last]/prior-1)])
            if scenario=='base':
                x=np.diff(np.log(np.r_[1.,nav]));boot.append(dict(period=per,rule=rule,comparison='cash',**block_interval(x)))
                if rule in ('VH','VL'):
                    base=sums[(per,'V0','base')]/counts[per]
                    d=x-np.diff(np.log(np.r_[1.,base]));boot.append(dict(period=per,rule=rule,comparison='V0',**block_interval(d)))
    table=pd.DataFrame(summary);table.to_csv(a.output/'summary.csv',index=False)
    pd.DataFrame(annual,columns=['period','rule','scenario','year','return_total']).to_csv(a.output/'yearly.csv',index=False)
    pd.DataFrame(boot).to_csv(a.output/'bootstrap.csv',index=False)
    gates={}
    for rule in RULES:
        sub=table[(table.rule==rule)&table.scenario.isin(['base','double_cost'])]
        gates[rule]=bool(len(sub)==8 and ((sub.return_total>0)&(sub.mean_trade_return>0)&(sub.stale_zero_return>0)&(sub.closed_trades>=1000)).all())
    keys=sorted(quote_samples)
    np.savez_compressed(a.output/'offline_samples.npz',symbols=np.array(keys),days=dates,
        bars=np.stack([quote_samples[k] for k in keys]),isST=np.stack([sample_states[k] for k in keys]),
        tradestatus=np.stack([sample_trade[k] for k in keys]))
    result=dict(study='VOLUME_SHOCK_3_V1',finished_at_utc=datetime.now(timezone.utc).isoformat(),
        codes=counts,accepted_status_codes=len(accepted),quote_rows=sum(x[2] for x in coverage),
        audited_accounts=audits,all_scenario_trades=total_trades,saved_base_trades=saved,all_scenario_entry_events=entries,
        scope_entry_violations=entry_violations,prefix_checks=prefixes,reference_boolean_checks=signal_tests,
        reference_mismatches=signal_mismatches,mismatch_examples=mismatches,research_gates=gates,
        clean_holdout=False,stress_trade_files_saved=False,native_ths_verified=False,real_account_verified=False,
        trade_ready=False,price_source=cfg,state_sha256=STATE_SHA,plan_sha256=hashlib.sha256(plan.encode()).hexdigest())
    (a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    if entry_violations:raise AssertionError('Entry outside hard scope')
    lines=['# Volume-shock diagnostic — actual fixed-rule results','',
      'Partial historical mainboard coverage, fractional adjusted units, repeated historical research. Not an executable account or native Tonghuashun certification.','',
      '|Period|Rule|Scenario|Cumulative return|Aggregate drawdown|Closes|Mean net trade|',
      '|---|---|---|---:|---:|---:|---:|']
    for row in summary:
        mt='n/a' if row['mean_trade_return'] is None else f"{row['mean_trade_return']:.3%}"
        lines.append(f"|{row['period']}|{row['rule']}|{row['scenario']}|{row['return_total']:.2%}|{row['max_drawdown']:.2%}|{row['closed_trades']}|{mt}|")
    lines+=['','Research gates, not certification: '+json.dumps(gates),
        'All base trades/events retained. Pressure scenarios retain audited per-stock outcomes, not complete trade files.',
        'Bootstrap intervals condition on already-chosen rules/data and do not adjust adaptive research selection.']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
