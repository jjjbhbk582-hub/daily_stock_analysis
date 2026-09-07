"""Resume only the final 233 statuses; no name-history inference or new strategy."""
import argparse,csv,hashlib,itertools,json,lzma,multiprocessing as mp,time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from historical_status import FIELDS,align_status,deterministic_order
from status_resume_v2 import save_rows,read_rows,worker
from batch_completion import consolidate

def seed_to_checkpoints(seed,out):
 seed=Path(seed);out=Path(out);raw=out/'new_records';raw.mkdir(parents=True,exist_ok=True)
 accepted={r['symbol']:r for r in json.loads((seed/'accepted.json').read_text())}
 with np.load(seed/'states.npz',allow_pickle=False) as z:
  days=list(map(str,z['days']));symbols=list(map(str,z['symbols']));pos={s:i for i,s in enumerate(symbols)}
  matrix_st=z['isST'];matrix_trade=z['tradestatus']
  seen=set()
  with lzma.open(seed/'provider_records.csv.xz','rt',newline='') as f:
   r=csv.reader(f)
   if next(r)!=FIELDS.split(','):raise ValueError('Seed field mismatch')
   for sym,group in itertools.groupby(r,key=lambda row:row[1].replace('.','').upper()):
    if sym not in accepted or sym in seen:raise ValueError('Unexpected or noncontiguous seed code')
    rows=list(group)
    if len(rows)!=accepted[sym]['rows']:raise ValueError('Incomplete seed rows')
    st,tr,_=align_status(rows,days,sym)
    np.testing.assert_array_equal(st,matrix_st[pos[sym]])
    np.testing.assert_array_equal(tr,matrix_trade[pos[sym]])
    save_rows(raw,sym,rows,days);seen.add(sym)
  if seen!=set(accepted):raise ValueError('Missing seed response')
 return days,symbols,sorted(seen)

def main():
 p=argparse.ArgumentParser();p.add_argument('--seed',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 seed=next(a.seed.rglob('accepted.json')).parent
 expected={'states.npz':'b51e98ee1a8313db15d4cd10c0131c4bd617ac67c7e61ca13545e9fc38e1e91a','provider_records.csv.xz':'ae024c3d8fba9c4461515ab2cc42509de03b8be6a1a87044666e7fed763219f8','accepted.json':'55cee66d21e9dc6c4c6e39e2c9245e55d542e76a19942a9fefd93f8f1e8d576e'}
 for k,v in expected.items():
  if hashlib.sha256((seed/k).read_bytes()).hexdigest()!=v:raise ValueError('Unverified prior checkpoint '+k)
 days,symbols,initial=seed_to_checkpoints(seed,a.output)
 if len(initial)!=3252 or len(symbols)!=3485 or days[-1]!='2026-09-04':raise ValueError('Wrong frozen checkpoint')
 todo=[s for s in deterministic_order(symbols) if s not in set(initial)];(a.output/'frozen_pending.json').write_text(json.dumps(todo))
 print('Verified and reused',len(initial),'histories; requesting',len(todo),flush=True)
 ctx=mp.get_context('spawn');jobs=[]
 for j in range(4):
  q=ctx.Process(target=worker,args=(j,todo[j::4],days,str(a.output),300));q.start();jobs.append(q)
 deadline=time.monotonic()+365
 for q in jobs:
  q.join(max(0,deadline-time.monotonic()))
  if q.is_alive():q.kill();q.join()
 result=consolidate(a.output,days,symbols,initial)
 result.update(study='BATCH_STATUS_CLOSEOUT',worker_exit_codes=[q.exitcode for q in jobs],finished_at_utc=datetime.now(timezone.utc).isoformat(),publication_time_verified=False,historical_names_rejected=True,trade_ready=False)
 (a.output/'result.json').write_text(json.dumps(result,indent=2))
 for f in (a.output/'new_records').glob('*.csv.gz'):f.unlink()
 print(json.dumps(result),flush=True)
if __name__=='__main__':main()
