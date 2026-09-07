"""208 frozen finite-account diagnostics. No native or real-share certification.
Source volume is hands; amount is thousands RMB. No parameter optimization.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,lzma,tarfile
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from verify_data import safe_name,FEATURE,is_mainboard,read_calendar,decode_feature,download,verify_identity
from batch_signals import RULES,compute_signals,quarantine_mask
from batch_portfolio import simulate_portfolio
PERIODS={'older':('2001-01-01','2008-12-31'),'early':('2009-01-01','2014-12-31'),'middle':('2015-01-01','2020-12-31'),'recent':('2021-01-01','2026-09-04')}
FIELDS=('open','high','low','close','volume','factor','amount')
BLOCKS={'SZ002450':'2021-04-07','SH600614':'2021-05-26'}

def elapsed_years(first,last):
 return (pd.Timestamp(str(last))-pd.Timestamp(str(first))).days/365.25

def restored_units(price,volume,amount,factor):
 if np.any(~np.isfinite(factor)) or np.any(factor<=0):raise ValueError('Invalid factor')
 return price/factor,volume*factor*100.,amount*1000.

def eligibility(symbol,days,st,trade):
 if not is_mainboard(symbol):raise ValueError('Outside mainboard')
 ok=(st==0)&(trade==1)&~quarantine_mask(st)
 if symbol in BLOCKS:ok=ok&(days<BLOCKS[symbol])
 return ok

def read_panel(path,cutoff):
 raw={};cal=None;inst=None;seen=set();expanded=0
 with tarfile.open(path,'r|gz') as z:
  for m in z:
   name=safe_name(m.name)
   if name in seen or len(seen)>=200000 or not (m.isfile() or m.isdir()) or getattr(m,'sparse',None):raise ValueError('Unsafe archive')
   seen.add(name);expanded+=m.size
   if m.size>8*1024**2 or expanded>10*1024**3:raise ValueError('Archive too large')
   match=FEATURE.fullmatch(name)
   want=match and is_mainboard(match[1]) and match[2] in FIELDS
   if not want and name not in ('qlib_bin/calendars/day.txt','qlib_bin/instruments/all.txt'):continue
   f=z.extractfile(m)
   if f is None:raise ValueError('Missing stream')
   content=f.read()
   if len(content)!=m.size:raise ValueError('Truncated stream')
   if name.endswith('/calendars/day.txt'):cal=content
   elif name.endswith('/instruments/all.txt'):inst=content
   else:raw.setdefault(match[1].upper(),{})[match[2]]=content
 if cal is None or inst is None:raise ValueError('Missing calendar/instruments')
 days=np.array(read_calendar(cal,cutoff));intervals={}
 for row in inst.decode().splitlines():
  s,a,b=row.split('\t')
  if is_mainboard(s):intervals.setdefault(s,[]).append((a,b))
 syms=sorted(intervals);shape=(len(syms),len(days));d={k:np.full(shape,np.nan,np.float32) for k in FIELDS}
 for j,s in enumerate(syms):
  active=np.zeros(len(days),bool)
  for a,b in intervals[s]:active|=(days>=a)&(days<=b)
  for k in FIELDS:
   if k not in raw.get(s,{}):raise ValueError(f'Missing {s}:{k}')
   offset,val=decode_feature(raw[s][k],len(days));d[k][j,offset:offset+len(val)]=val;d[k][j,~active]=np.nan
 d['symbols']=np.array(syms);d['days']=days
 return d

def prepare(d,status_path,out):
 syms=list(d['symbols']);days=d['days'];shape=d['close'].shape
 with np.load(status_path,allow_pickle=False) as z:
  if list(z['days'])!=list(days):raise ValueError('Status calendar differs')
  if list(z['symbols'])!=syms:raise ValueError('Status inventory differs')
  d['st']=z['isST'].copy();d['trade']=z['tradestatus'].copy()
 prices=np.stack([d[k] for k in ('open','high','low','close')]);anyprice=np.isfinite(prices).any(axis=0)
 valid=np.isfinite(prices).all(axis=0)&(prices>0).all(axis=0)&np.isfinite(d['volume'])&(d['volume']>0)&np.isfinite(d['factor'])&(d['factor']>0)
 malformed=anyprice & ~(np.isfinite(prices).all(axis=0)&(prices>0).all(axis=0)&np.isfinite(d['volume'])&(d['volume']>=0)&np.isfinite(d['factor'])&(d['factor']>0))
 malformed|=valid&((d['high']+1e-6<d['open'])|(d['high']+1e-6<d['close'])|(d['low']>d['open']+1e-6)|(d['low']>d['close']+1e-6))
 if malformed.any():raise ValueError('Malformed source quote rows')
 d['valid']=valid;d['eligible']=np.zeros(shape,bool);d['score']=np.full(shape,np.nan,np.float32)
 # Source vol is hands, source amount thousand RMB. Do not infer units from labels.
 d['raw_volume']=d['volume']*d['factor']*100.;d['amount']=d['amount']*1000.
 buy=np.zeros((len(RULES),*shape),bool);sell=buy.copy();coverage=[];prefix=0
 sampleids=sorted(range(len(syms)),key=lambda j:hashlib.sha256(('BATCH_20260908_SAMPLE|'+syms[j]).encode()).hexdigest())[:16]
 diagnostics={k:[] for k in ('rsi6','rsi2','trendline')}
 for j,s in enumerate(syms):
  ids=np.flatnonzero(valid[j]);x={k:d[k][j,ids] for k in ('open','high','low','close','volume')};flag=compute_signals(x)
  buy[:,j,ids]=flag['buy'];sell[:,j,ids]=flag['sell']
  d['eligible'][j]=eligibility(s,days,d['st'][j],d['trade'][j])
  d['score'][j,ids]=pd.Series(d['amount'][j,ids]).rolling(20).mean().shift(1).to_numpy()
  for cutoff in ('2008-12-31','2014-12-31','2020-12-31'):
   n=int(np.searchsorted(days[ids],cutoff,side='right'));f=compute_signals({k:v[:n] for k,v in x.items()})
   for key in ('buy','sell'):np.testing.assert_array_equal(f[key],flag[key][:,:n])
   prefix+=1
  for per,(a,b) in PERIODS.items():
   mask=(days>=a)&(days<=b);v=valid[j]&mask;known=(d['st'][j]>=0)&(d['trade'][j]>=0)
   coverage.append([per,s,int(v.sum()),int((v&known).sum()),int((v&d['eligible'][j]).sum()),int((v&quarantine_mask(d['st'][j])).sum())])
  if (j+1)%500==0:print('Prepared',j+1,'stocks',flush=True)
 pd.DataFrame(coverage,columns=['period','symbol','quoted_days','known_status_days','provisional_eligible_days','post_ST_quarantine_days']).to_csv(out/'coverage.csv.xz',index=False)
 sample={k:(v[sampleids] if isinstance(v,np.ndarray) and v.shape==shape else v) for k,v in d.items() if k not in ('symbols',)}
 sample['symbols']=d['symbols'][sampleids];sample['buy']=buy[:,sampleids];sample['sell']=sell[:,sampleids]
 np.savez_compressed(out/'same_source_sample.npz',**sample)
 return buy,sell,prefix

def independent_audit(result):
 events=result['cash_events'];flow=100000.;errors=[]
 for event in events:flow+=event['cash_delta']
 errors.append(abs(flow-result['cash'][-1]))
 for t in result['trades']:
  if not t['signal_index']<t['buy_index']<=t['sell_signal_index']<t['sell_index']:raise AssertionError('Trade chronology')
  if t['shares_entry']%100:raise AssertionError('Entry was not a lot')
  errors.extend([abs(t['entry_cost']-(t['shares_entry']*t['buy_price']+t['buy_fee'])),abs(t['proceeds']-(t['equivalent_shares_exit']*t['sell_price']-t['sell_fee'])),abs(t['pnl']-(t['proceeds']-t['entry_cost']))])
 value=sum(p['economic_units']*p['last_mark'] for p in result['open_positions'])
 errors.append(abs(result['equity'][-1]-flow-value))
 if max(errors,default=0)>1e-5:raise AssertionError('Ledger does not reconcile')
 return max(errors,default=0)

def dump_rows(out,name,rows):
 pd.DataFrame(rows).to_csv(out/(name+'.csv.xz'),index=False)

def main():
 p=argparse.ArgumentParser()
 for key in ('source','status','work','output'):p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
 cfg=json.loads(a.source.read_text());archive=a.work/'qlib_bin.tar.gz'
 if not archive.exists():download(cfg['archive_url'],archive,cfg['archive_size'],cfg['archive_sha256'])
 verify_identity(archive,cfg['archive_size'],cfg['archive_sha256'])
 state=next(a.status.rglob('states.npz'));d=read_panel(archive,cfg['requested_end'])
 buy,sell,prefix=prepare(d,state,a.output);dates=d['days'];results=[];trades=[];buys=[];orders=[];cash=[];opens=[];curves=[]
 settings=[('base',1.,1,None),('double_cost',2.,1,None),('delay2',1.,2,None)]+[(f'random_{seed}',1.,1,seed) for seed in range(10)]
 violations=0;global_error=0.
 for per,(first,last) in PERIODS.items():
  left=int(np.searchsorted(dates,first));right=int(np.searchsorted(dates,last,side='right'))
  for ri,rule in enumerate(RULES):
   for scenario,mul,delay,seed in settings:
    res=simulate_portfolio(d,buy[ri],sell[ri],left,right,multiple=mul,delay=delay,seed=seed,max_hold=40 if rule=='CONFIRMED_TRENDLINE' else 10)
    err=independent_audit(res);global_error=max(global_error,err);tags=dict(period=per,rule=rule,scenario=scenario)
    for event in res['buy_events']:
     j=int(np.searchsorted(d['symbols'],event['symbol']));i=event['index'];si=event['signal']
     if not (d['eligible'][j,i] and d['eligible'][j,si] and d['st'][j,i]==0 and d['st'][j,si]==0):violations+=1
    e=res['equity'];curve=np.r_[100000.,e];dd=float(np.max(1-curve/np.maximum.accumulate(curve)))
    duration=elapsed_years(dates[left],dates[right-1])
    ts=res['trades'];profit=sum(max(t['pnl'],0) for t in ts);loss=sum(max(-t['pnl'],0) for t in ts)
    row=dict(**tags,return_total=float(e[-1]/100000-1),annualized_return=float((e[-1]/100000)**(1/duration)-1),max_drawdown=dd,closed_trades=len(ts),entries=res['entries'],cancelled=res['cancelled'],win_rate=sum(t['pnl']>0 for t in ts)/len(ts) if ts else None,mean_trade_return=float(np.mean([t['net_return'] for t in ts])) if ts else None,profit_factor=profit/loss if loss else None,total_fees=sum(t['buy_fee']+t['sell_fee'] for t in ts)+sum(p['buy_fee'] for p in res['open_positions']),average_exposure=float(np.mean(res['invested']/e)),max_held=int(max(res['nheld'])),stale_zero_return=float((e[-1]-res['stale'][-1])/100000-1),action_affected_trades=sum(t['action_days']>0 for t in ts),open_positions=len(res['open_positions']),ledger_error=err)
    results.append(row)
    for name,rows,target in [('trade',res['trades'],trades),('buy',res['buy_events'],buys),('order',res['orders'],orders),('cash',res['cash_events'],cash),('open',res['open_positions'],opens)]:
     target.extend(dict(**tags,**r) for r in rows)
    curves.extend(dict(**tags,date=str(day),equity=float(eq),cash=float(cc),invested=float(iv),positions=int(hh),stale=float(ss)) for day,eq,cc,iv,hh,ss in zip(dates[left:right],e,res['cash'],res['invested'],res['nheld'],res['stale']))
   print('Finished',per,rule,'13 fixed scenarios',flush=True)
 summary=pd.DataFrame(results);summary.to_csv(a.output/'summary.csv',index=False)
 for name,rows in [('trades',trades),('buy_events',buys),('orders',orders),('cash_events',cash),('open_positions',opens),('equity',curves)]:dump_rows(a.output,name,rows)
 receipt=dict(study='FINITE_ACCOUNT_4X4X13',scenarios=len(results),all_scenario_trades=len(trades),all_scenario_orders=len(orders),signal_prefix_checks=prefix,observed_scope_field_violations=violations,ledger_max_error=global_error,real_share_ledger_verified=False,ordinary_listing_publication_history_verified=False,native_ths_verified=False,trade_ready=False,archive_sha256=cfg['archive_sha256'],status_sha256=hashlib.sha256(state.read_bytes()).hexdigest(),finished_at_utc=datetime.now(timezone.utc).isoformat())
 if violations:raise AssertionError('Scope fields violated')
 (a.output/'result.json').write_text(json.dumps(receipt,indent=2))
 lines=['# Finite-account experiment: retrospective, provisional scope and corporate-action accounting','',str(receipt),'','|Period|Policy|Scenario|Cumulative|Drawdown|Trades|','|---|---|---|---:|---:|---:|']
 for r in results:
  if r['scenario'] in ('base','double_cost','delay2'):lines.append(f"|{r['period']}|{r['rule']}|{r['scenario']}|{r['return_total']:.2%}|{r['max_drawdown']:.2%}|{r['closed_trades']}|")
 (a.output/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(receipt),flush=True)
if __name__=='__main__':main()
