"""Bounded data completion, not a trading task. Reuse each accepted history.
No current-name backfill, no broker, no paid model, no scheduled repetitions.
"""
from __future__ import annotations
import argparse,csv,hashlib,itertools,json,lzma,multiprocessing as mp,signal,socket,time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from historical_status import FIELDS,align_status,deterministic_order,_alarm,_login
from status_resume_v2 import save_rows,read_rows,worker

def seed_to_checkpoints(seed,out):
 seed=Path(seed);out=Path(out);raw=out/'new_records';raw.mkdir(parents=True,exist_ok=True)
 accepted={r['symbol']:r for r in json.loads((seed/'accepted.json').read_text())}
 with np.load(seed/'states.npz',allow_pickle=False) as z:
  days=list(map(str,z['days']));symbols=list(map(str,z['symbols']));pos={s:i for i,s in enumerate(symbols)}
  seen=set()
  with lzma.open(seed/'provider_records.csv.xz','rt',newline='') as f:
   r=csv.reader(f)
   if next(r)!=FIELDS.split(','):raise ValueError('Seed field mismatch')
   for sym,group in itertools.groupby(r,key=lambda row:row[1].replace('.','').upper()):
    if sym not in accepted or sym in seen:raise ValueError('Unexpected or noncontiguous seed code')
    rows=list(group)
    if len(rows)!=accepted[sym]['rows']:raise ValueError('Incomplete seed rows')
    st,tr,_=align_status(rows,days,sym)
    np.testing.assert_array_equal(st,z['isST'][pos[sym]])
    np.testing.assert_array_equal(tr,z['tradestatus'][pos[sym]])
    save_rows(raw,sym,rows,days);seen.add(sym)
  if seen!=set(accepted):raise ValueError('Missing seed response')
 return days,symbols,sorted(seen)

def consolidate(out,days,symbols,initial):
 out=Path(out);root=out/'merged_status';root.mkdir(exist_ok=True)
 st=np.full((len(symbols),len(days)),-1,np.int8);tr=st.copy();accepted=[];count=0;present=[]
 with lzma.open(root/'provider_records.csv.xz','wt',newline='') as f:
  w=csv.writer(f);w.writerow(FIELDS.split(','))
  for i,sym in enumerate(symbols):
   path=out/'new_records'/(sym+'.csv.gz')
   if not path.exists():continue
   rows=read_rows(path);x,y,meta=align_status(rows,days,sym)
   if not rows:raise ValueError('Empty completed history')
   st[i]=x;tr[i]=y;w.writerows(rows);count+=len(rows);present.append(sym)
   accepted.append(dict(symbol=sym,status='received',**meta))
 np.savez_compressed(root/'states.npz',symbols=np.array(symbols),days=np.array(days),isST=st,tradestatus=tr)
 (root/'accepted.json').write_text(json.dumps(accepted))
 pending=[s for s in deterministic_order(symbols) if s not in set(present)]
 (root/'remaining.json').write_text(json.dumps(pending))
 if not set(initial).issubset(present):raise ValueError('Lost previous successes')
 checked=0
 with lzma.open(root/'provider_records.csv.xz','rt',newline='') as f:
  r=csv.reader(f);next(r)
  for sym in present:
   for row in read_rows(out/'new_records'/(sym+'.csv.gz')):
    if next(r)!=row:raise ValueError('Changed source text')
    checked+=1
  if next(r,None) is not None or checked!=count:raise ValueError('Unexpected consolidated rows')
 return dict(initial_histories=len(initial),received_codes=len(present),newly_downloaded=len(present)-len(initial),pending_codes=len(pending),provider_rows=count,lossless_rows_checked=checked)

def name_probe(out):
 """Only eight dated controls; do not certify a name-history API on syntax alone."""
 signal.signal(signal.SIGALRM,_alarm);socket.setdefaulttimeout(15)
 import baostock as bs
 root=Path(out)/'name_controls';root.mkdir(exist_ok=True);receipt=[]
 controls=[('2021-04-08','sz.002450'),('2021-04-14','sz.002450'),('2021-05-28','sz.002450'),('2021-06-01','sh.600614'),('2021-06-02','sh.600614'),('2024-04-17','sh.600766'),('2010-01-04','sh.600000'),('2026-09-04','sh.600000')]
 try:
  _login(bs)
  for day,code in controls:
   signal.alarm(25)
   try:
    r=bs.query_all_stock(day=day);rows=[]
    while r.error_code=='0' and r.next():rows.append(r.get_row_data())
    if r.error_code!='0':raise RuntimeError(r.error_msg)
    with (root/(day+'.csv')).open('w',newline='') as f:
     w=csv.writer(f);w.writerow(r.fields);w.writerows(rows)
    hit=[x for x in rows if x[0]==code]
    receipt.append(dict(day=day,code=code,fields=list(r.fields),rows=len(rows),observed=hit))
   except Exception as e:receipt.append(dict(day=day,code=code,error=repr(e)))
   finally:signal.alarm(0)
 except Exception as e:receipt.append({'login_error':repr(e)})
 finally:
  try:signal.alarm(5);bs.logout()
  except Exception:pass
  signal.alarm(0)
 (root/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))

def main():
 p=argparse.ArgumentParser();p.add_argument('--seed',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=1500)
 a=p.parse_args()
 if not 0<=a.seconds<=1500:raise ValueError('Collection budget exceeded')
 a.output.mkdir(parents=True,exist_ok=True)
 seed=next(a.seed.rglob('accepted.json')).parent
 days,symbols,initial=seed_to_checkpoints(seed,a.output)
 if len(initial)!=1649 or len(symbols)!=3485 or days[-1]!='2026-09-04':raise ValueError('Wrong frozen seed')
 pending=[s for s in deterministic_order(symbols) if s not in set(initial)]
 (a.output/'frozen_pending.json').write_text(json.dumps(pending));print(f'Reused {len(initial)}, pending {len(pending)}',flush=True)
 ctx=mp.get_context('spawn');jobs=[]
 for j in range(4):
  q=ctx.Process(target=worker,args=(j,pending[j::4],days,str(a.output),a.seconds));q.start();jobs.append(q)
 deadline=time.monotonic()+a.seconds+65
 for q in jobs:
  q.join(max(0,deadline-time.monotonic()))
  if q.is_alive():q.kill();q.join()
 result=consolidate(a.output,days,symbols,initial)
 result.update(study='BATCH_COMPLETION_V3',worker_exit_codes=[q.exitcode for q in jobs],finished_at_utc=datetime.now(timezone.utc).isoformat(),publication_time_verified=False,trade_ready=False)
 (a.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 for f in (a.output/'new_records').glob('*.csv.gz'):f.unlink()
 name_probe(a.output)
 (a.output/'HASHES.json').write_text(json.dumps({str(f.relative_to(a.output)):hashlib.sha256(f.read_bytes()).hexdigest() for f in a.output.rglob('*') if f.is_file() and f.name not in ('run.log','HASHES.json')},indent=2))
if __name__=='__main__':main()
