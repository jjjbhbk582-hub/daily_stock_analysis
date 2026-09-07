"""Read dated BaoStock status records; never infer past ST from current names.
Unknown values stay unknown. This is an effective-date data check, not an
announcement-timestamp/bitemporal certification. No brokerage operations.
"""
from __future__ import annotations
import csv
import hashlib
import json
import lzma
import multiprocessing as mp
import signal
import socket
import time
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np

FIELDS='date,code,tradestatus,isST'


def deterministic_order(symbols):
    return sorted(set(symbols),key=lambda s:hashlib.sha256(('PIT_STATUS_V1|'+s).encode()).hexdigest())


def align_status(rows,days,symbol):
    index={d:i for i,d in enumerate(days)}
    st=np.full(len(days),-1,np.int8);trade=st.copy()
    meta=dict(rows=0,unknown_st_rows=0,unknown_trade_rows=0,outside_calendar_rows=0)
    previous=''
    for r in rows:
        if len(r)!=4:raise ValueError('Status schema mismatch')
        d,code,t,s=r
        if date.fromisoformat(d).isoformat()!=d or d<=previous:
            raise ValueError('Duplicate, unsorted or invalid date')
        previous=d
        if code.replace('.','').upper()!=symbol:raise ValueError('Cross-security status')
        if s not in ('0','1','') or t not in ('0','1',''):
            raise ValueError('Undocumented status enum')
        meta['rows']+=1;meta['unknown_st_rows']+=int(s=='');meta['unknown_trade_rows']+=int(t=='')
        if d not in index:meta['outside_calendar_rows']+=1;continue
        i=index[d];st[i]=int(s) if s else -1;trade[i]=int(t) if t else -1
    return st,trade,meta


def admission_masks(st,trade):
    if st.shape!=trade.shape:raise ValueError('Status arrays differ')
    return {'baseline':np.ones(st.shape,bool),
            'known':(st>=0)&(trade==1),
            'normal':(st==0)&(trade==1)}


def source_gate(known,total,smoke_ok):
    return bool(total>0 and known/total>=.99 and smoke_ok)


def _alarm(signum,frame):
    raise TimeoutError('Per-request status deadline')


def _query(bs,symbol,start,end):
    signal.alarm(25)
    try:
        response=bs.query_history_k_data_plus(symbol[:2].lower()+'.'+symbol[2:],FIELDS,
            start_date=start,end_date=end,frequency='d',adjustflag='3')
        if response.error_code!='0':raise RuntimeError(response.error_code+':'+response.error_msg)
        if list(response.fields)!=FIELDS.split(','):raise ValueError('Provider fields differ')
        rows=[]
        while response.error_code=='0' and response.next():
            rows.append(response.get_row_data())
            if len(rows)>10000:raise ValueError('Unexpected row count')
        if response.error_code!='0':raise RuntimeError('Partial query: '+response.error_msg)
        return rows
    finally:signal.alarm(0)


def _login(bs):
    signal.alarm(25)
    try:
        result=bs.login()
        if result.error_code!='0':raise RuntimeError('login:'+result.error_msg)
    finally:signal.alarm(0)


def fetch_worker(number,symbols,days,root,budget=600):
    """At most two isolated sessions, with bounded calls and explicit missingness."""
    signal.signal(signal.SIGALRM,_alarm);socket.setdefaulttimeout(15)
    import baostock as bs
    root=Path(root);deadline=time.monotonic()+budget;failures=0;results=[]
    status=np.full((len(symbols),len(days)),-1,np.int8);trade=status.copy()
    smoke=[];connected=False
    try:
        _login(bs);connected=True
        # Different controls; no performance selection. Same-date status, not today's name.
        if number==0:
            for sym in ('SH600766','SH600000'):
                try:
                    rr=_query(bs,sym,'2024-04-01','2024-04-30')
                    with (root/f'smoke_{sym}.csv').open('w',newline='') as f:
                        w=csv.writer(f);w.writerow(FIELDS.split(','));w.writerows(rr)
                    exact=[x for x in rr if x[0]=='2024-04-17']
                    expected='1' if sym=='SH600766' else '0'
                    smoke.append({'symbol':sym,'rows':len(rr),'date':'2024-04-17',
                        'expected_isST':expected,'actual':exact,'passed':bool(exact and exact[0][3]==expected)})
                except Exception as e:smoke.append({'symbol':sym,'error':str(e),'passed':False})
        with lzma.open(root/f'provider_records_{number}.csv.xz','wt',preset=6,newline='') as f:
            writer=csv.writer(f);writer.writerow(FIELDS.split(','))
            for j,sym in enumerate(symbols):
                if time.monotonic()>deadline or failures>=3:
                    results.append(dict(symbol=sym,status='not_attempted',reason='deadline_or_circuit'))
                    continue
                try:
                    rr=_query(bs,sym,days[0],days[-1])
                    writer.writerows(rr)
                    s,t,meta=align_status(rr,days,sym)
                    status[j]=s;trade[j]=t
                    results.append(dict(symbol=sym,status='received' if rr else 'empty',**meta))
                    failures=0
                except Exception as e:
                    failures+=1;results.append(dict(symbol=sym,status='error',reason=f'{type(e).__name__}:{e}'))
                    # Do not splice partial responses or pretend errors are non-ST.
                if (j+1)%100==0:print(f'Status worker {number}: {j+1}/{len(symbols)}',flush=True)
                time.sleep(.05)
    except Exception as e:
        results=[dict(symbol=s,status='not_attempted',reason=f'login_failure:{e}') for s in symbols]
    finally:
        signal.alarm(0)
        if connected:
            try:
                signal.alarm(5);bs.logout()
            except Exception:pass
            finally:signal.alarm(0)
        np.savez_compressed(root/f'status_{number}.npz',symbols=np.array(symbols),days=np.array(days),isST=status,tradestatus=trade)
        (root/f'fetch_{number}.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        (root/f'smoke_{number}.json').write_text(json.dumps(smoke,ensure_ascii=False,indent=2))


def fetch_all(symbols,days,root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    order=deterministic_order(symbols);ctx=mp.get_context('spawn');workers=[]
    for j in range(2):
        worker=ctx.Process(target=fetch_worker,args=(j,order[j::2],days,str(root)))
        worker.start();workers.append(worker)
    deadline=time.monotonic()+660
    for worker in workers:
        worker.join(max(0,deadline-time.monotonic()))
        if worker.is_alive():worker.kill();worker.join()
    states={};results=[];smoke=[]
    for j in range(2):
        path=root/f'status_{j}.npz'
        if path.exists():
            with np.load(path,allow_pickle=False) as z:
                if list(z['days'])!=days:raise ValueError('Status calendar mismatch')
                for i,s in enumerate(z['symbols']):states[str(s)]=(z['isST'][i].copy(),z['tradestatus'][i].copy())
            results+=json.loads((root/f'fetch_{j}.json').read_text())
            smoke+=json.loads((root/f'smoke_{j}.json').read_text())
        else:
            results += [dict(symbol=s,status='worker_failed',reason='no_final_matrix') for s in order[j::2]]
    receipt={'source':'BaoStock 0.9.3 query_history_k_data_plus','fields':FIELDS,
       'requested_codes':len(order),'returned_matrices':len(states),
       'received_codes':sum(r['status']=='received' for r in results),
       'worker_exit_codes':[w.exitcode for w in workers],
       'smoke_controls':smoke,'smoke_ok':len(smoke)==2 and all(s['passed'] for s in smoke),
       'as_of_utc':datetime.now(timezone.utc).isoformat(),
       'effective_date_only':True,'historical_publication_timestamps_verified':False}
    (root/'acquisition.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    return states,receipt,results
