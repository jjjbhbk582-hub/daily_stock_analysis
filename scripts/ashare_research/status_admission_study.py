"""Fixed RSI rules, historical-status admission only. No parameter search.
The BaoStock history is a later-retrieved effective-date series, not a proven
point-in-time publication archive. Raw share accounting is unchanged/unverified.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,lzma,shutil
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from formula_study import load_archive,decode_bars,mdd
from exit_policy_study import indicators,simulate_exit,PERIODS
from rsi_factorial import audit_account,TRADE_HEADER
from verify_data import download,verify_identity
from historical_status import fetch_all,admission_masks,source_gate

RULES=('D0','D2')
CONFIGS=(('baseline',1.),('known',1.),('normal',1.),('normal_double',2.))

def main():
    p=argparse.ArgumentParser()
    for name in ('source','work','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(a.source.read_text());plan=Path(__file__).with_name('STATUS_ADMISSION_PLAN.md').read_text()
    (a.output/'plan.md').write_text(plan)
    archive=a.work/'qlib_bin.tar.gz'
    if not archive.exists():download(cfg['archive_url'],archive,cfg['archive_size'],cfg['archive_sha256'])
    verify_identity(archive,cfg['archive_size'],cfg['archive_sha256'])
    days,intervals,raw,decode=load_archive(archive,cfg['requested_end'])
    dates=np.array(days);costs=np.where(dates<'2023-08-28',.0023,.0018)
    states,receipt,fetch_records=fetch_all(sorted(intervals),days,a.output/'status_source')
    pd.DataFrame(fetch_records).to_csv(a.output/'fetch_coverage.csv',index=False)
    # A failed source read is not a valid all-cash strategy result.
    if receipt['received_codes']<100 or not receipt['smoke_ok']:
        reason={'state':'SOURCE_NOT_ACCEPTED_NO_NEW_BACKTEST','acquisition':receipt,
            'native_ths_verified':False,'trade_ready':False}
        (a.output/'result.json').write_text(json.dumps(reason,ensure_ascii=False,indent=2))
        (a.output/'report.md').write_text('# Historical-status source not accepted\n\n'+json.dumps(reason,ensure_ascii=False,indent=2))
        print(json.dumps(reason,ensure_ascii=False),flush=True);return 2
    bounds={k:(int(np.searchsorted(dates,s)),int(np.searchsorted(dates,e,side='right'))) for k,(s,e) in PERIODS.items()}
    counts={p:0 for p in PERIODS};sums={};stats={};coverage=[];stock=[];totals={p:np.zeros(4,dtype=np.int64) for p in PERIODS}
    for per,(l,r) in bounds.items():
        for rule in RULES:
            for config,mul in CONFIGS:
                k=per,rule,config;sums[k]=np.zeros(r-l);stats[k]=[0,0,0.,0.,0.]
    ntr=naud=0;examples=[]
    # All base trades are retained; normal_double keeps per-stock audit only.
    with lzma.open(a.output/'base_trades.csv.xz','wt',preset=6,newline='') as stream:
        w=csv.writer(stream);w.writerow(TRADE_HEADER)
        for num,sym in enumerate(sorted(intervals),1):
            bars=decode_bars(raw[sym],days,intervals[sym],decode)
            valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1);ids=np.flatnonzero(valid)
            flag=indicators(pd.DataFrame(bars[ids],columns=['open','high','low','close','volume']))
            dense=[]
            for j,v in enumerate(flag):
                x=np.full(len(days),np.nan) if j==3 else np.zeros(len(days),bool);x[ids]=v;dense.append(x)
            st,tr=states.get(sym,(np.full(len(days),-1,np.int8),np.full(len(days),-1,np.int8)))
            masks=admission_masks(st,tr)
            # Exact-date lookup; future ST dates cannot change today's admission.
            for cut in ('2008-12-31','2020-12-31'):
                n=int(np.searchsorted(dates,cut,side='right'))
                mm=admission_masks(st[:n],tr[:n])
                for key in mm:assert np.array_equal(mm[key],masks[key][:n])
            for per,(left,right) in bounds.items():
                vi=valid[left:right];ns=int(vi.sum())
                if not ns:continue
                counts[per]+=1
                ss=st[left:right];tt=tr[left:right];bb=dense[0][left:right]
                known=(ss>=0)&(tt>=0)
                cov=[per,sym,ns,int((vi&known).sum()),int((vi&(ss==1)).sum()),
                    int((vi&~known).sum()),int(bb.sum()),int((bb&~masks['known'][left:right]).sum()),
                    int((bb&(ss==1)).sum())]
                coverage.append(cov);totals[per]+=np.array([ns,cov[3],cov[4],cov[5]])
                for rule in RULES:
                    for config,mul in CONFIGS:
                        mask=masks['normal' if config=='normal_double' else config]
                        out=simulate_exit(bars[:right],(dense[0]&mask)[:right],dense[1][:right],dense[2][:right],dense[3][:right],
                            costs[:right],left,rule,mul,1,-.048)
                        err=audit_account(out,bars,costs,mul);naud+=1
                        key=per,rule,config;sums[key]+=out['nav'];stat=stats[key]
                        for x in out['trades']:
                            sig,bi,ssig,si,bp,sp,q,basis,pnl,ret=x
                            stat[0]+=1;stat[1]+=int(ret>0);stat[2]+=ret;stat[3]+=max(pnl,0);stat[4]+=max(-pnl,0)
                            if config!='normal_double':
                                w.writerow([per,rule,config,sym,days[sig],days[bi],days[ssig],days[si],bp,sp,q,basis]);ntr+=1
                            if sym=='SH600766' and '2024-04-01'<=days[sig]<='2024-04-30':
                                examples.append(dict(period=per,rule=rule,config=config,buy_signal=days[sig],buy_date=days[bi],
                                    source_isST=int(st[sig]),source_tradestatus=int(tr[sig]),trade_return=ret))
                            if config=='normal':assert st[sig]==0 and tr[sig]==1
                        stale=bool(out['units'] and right-1-out['last_quote']>=20)
                        stock.append([per,rule,config,sym,float(out['nav'][-1]),out['cash'],out['units'],out['mark'],
                            out['open_entry_cost'],len(out['trades']),out['entries'],out['cancelled'],out['blocked_sells'],
                            out['units']*out['mark'] if stale else 0.,mdd(out['nav']),err])
            if num%500==0:print(f'Admission study: {num}/{len(intervals)}; accounts {naud}',flush=True)
    stockcols=['period','rule','config','symbol','final_nav','cash','units','mark','open_entry_cost','closed_trades',
        'entries','cancelled_buys','blocked_sell_days','stale_value','individual_mdd','audit_error']
    s=pd.DataFrame(stock,columns=stockcols);s.to_csv(a.output/'per_stock.csv.xz',index=False)
    cols=['period','symbol','valid_bars','known_state_bars','st_bars','unknown_bars','buy_flags','unknown_or_halted_flags','st_buy_flags']
    pd.DataFrame(coverage,columns=cols).to_csv(a.output/'coverage.csv.xz',index=False)
    summary=[];yearly=[]
    with lzma.open(a.output/'equity.csv.xz','wt',preset=6,newline='') as f:
        w=csv.writer(f);w.writerow(['period','rule','config','date','nav'])
        for key,values in sums.items():
            per,rule,config=key;l,r=bounds[per];nav=values/counts[per];stat=stats[key]
            sub=s[(s.period==per)&(s.rule==rule)&(s.config==config)]
            summary.append(dict(period=per,rule=rule,config=config,codes=counts[per],return_total=float(nav[-1]-1),max_drawdown=mdd(nav),
                closed_trades=stat[0],win_rate=stat[1]/stat[0] if stat[0] else None,mean_trade_return=stat[2]/stat[0] if stat[0] else None,
                median_sleeve_return=float(sub.final_nav.median()-1),median_individual_mdd=float(sub.individual_mdd.median()),
                stale_zero_return=float(nav[-1]-1-sub.stale_value.sum()/counts[per]),max_audit_error=float(sub.audit_error.max())))
            w.writerows([per,rule,config,d,float(v)] for d,v in zip(days[l:r],nav))
            for yr in sorted(set(d[:4] for d in days[l:r])):
                ii=np.flatnonzero(np.char.startswith(dates[l:r],yr));aa,bb=ii[0],ii[-1];prior=nav[aa-1] if aa else 1.
                yearly.append([per,rule,config,yr,float(nav[bb]/prior-1)])
    pd.DataFrame(summary).to_csv(a.output/'summary.csv',index=False)
    pd.DataFrame(yearly,columns=['period','rule','config','year','return_total']).to_csv(a.output/'yearly.csv',index=False)
    quality={p:dict(zip(['price_bars','known_state_bars','st_bars','unknown_bars'],map(int,v))) for p,v in totals.items()}
    for per,q in quality.items():q['source_gate_99pct']=source_gate(q['known_state_bars'],q['price_bars'],receipt['smoke_ok'])
    result={'study':'STATUS_ADMISSION_V1','source_quality':quality,'codes':counts,'audited_accounts':naud,'saved_base_trades':ntr,
        'source_receipt':receipt,'case_600766':examples,'point_in_time_publication_archive_verified':False,
        'new_strategy_parameters':False,'same_old_execution_limits':True,'native_ths_verified':False,'trade_ready':False,
        'finished_at_utc':datetime.now(timezone.utc).isoformat()}
    (a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    lines=['# Historical-status admission: shadow diagnostic','',
      'Effective-date source; publication timestamps and real-share/auction execution unverified. All previous signal and exit parameters fixed.',
      '|Period|Rule|Admission|Cumulative return|Drawdown|Closes|','|---|---|---|---:|---:|---:|']
    for z in summary:lines.append(f"|{z['period']}|{z['rule']}|{z['config']}|{z['return_total']:.2%}|{z['max_drawdown']:.2%}|{z['closed_trades']}|")
    lines+=['','Source coverage: '+json.dumps(quality),'','No readiness certificate. Unknown dates are not treated as normal; baseline versus known isolates availability effects.']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0
if __name__=='__main__':raise SystemExit(main())
