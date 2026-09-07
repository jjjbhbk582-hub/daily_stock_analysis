"""One-shot price/status export for an already-authorized research branch.
No strategy is searched here. Public data only; bounded two-worker status reads.
"""
from __future__ import annotations
import hashlib, json, io, csv, sys, tarfile, multiprocessing as mp, time
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

OLD_NUMBERS='1,100,2001,2007,2027,2049,2050,2142,2179,2202,2222,2230,2241,2311,2352,2371,2410,2415,2456,2460,2463,2466,2475,2493,2518,2594,2600,2601,2602,2648,2709,2714,2837,333,338,408,425,538,568,596,600009,600019,600026,600030,600031,600036,600150,600184,600276,600309,600406,600426,600436,600438,600487,600519,600522,600547,600570,600588,600690,600760,600809,600845,600875,600887,600893,600900,600938,601012,601088,601138,601318,601600,601633,601698,601728,601766,601808,601838,601857,601872,601877,601888,601899,601919,601985,603160,603259,603260,603288,603369,603392,603501,603629,603658,603799,603806,603899,603986,603993,63,651,661,725,768,858,895,938,963,977,999,600028,600104'.split(',')
OLD_SYMBOLS=[('SH' if int(x)>=600000 else 'SZ')+x.zfill(6) for x in OLD_NUMBERS]
FIELDS=('open','high','low','close','volume','factor')

def choose_symbols(symbols,old_symbols,n=128):
    ordered=sorted(set(symbols),key=lambda s:hashlib.sha256(('PIT_STATUS_V1|'+s).encode()).hexdigest())
    exclude=set(ordered[:500])|set(old_symbols)
    pool=set(symbols)-exclude
    chosen=sorted(pool,key=lambda s:hashlib.sha256(('JZ_T_RAW_SAMPLE_V1|'+s).encode()).hexdigest())[:n]
    if len(chosen)!=n:raise ValueError('Insufficient predefined pool')
    return sorted(chosen)

def align_feature(raw,total):
    a=np.frombuffer(raw,dtype='<f4')
    if len(a)<2 or not np.isfinite(a[0]) or a[0]<0 or a[0]!=int(a[0]):raise ValueError('Bad offset')
    offset=int(a[0]);end=offset+len(a)-1
    if end>total:raise ValueError('Calendar overflow')
    out=np.full(total,np.nan,np.float32);out[offset:end]=a[1:]
    return out

def self_test():
    s=[f'SH600{i:03d}' for i in range(800)]
    a=choose_symbols(s,s[:112]);assert len(a)==128 and a==choose_symbols(s[::-1],s[:112])
    assert not set(a)&set(s[:112])
    np.testing.assert_allclose(align_feature(np.array([2,1.,2.],dtype='<f4').tobytes(),5),[np.nan,np.nan,1,2,np.nan],equal_nan=True)
    print('export self checks passed',flush=True)

def main():
    sys.path.insert(0,str(Path('scripts/ashare_research').resolve()))
    import verify_data as v
    from historical_status import fetch_worker
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    work=out.parent/'T_input';work.mkdir(exist_ok=True)
    config=json.loads(Path('scripts/ashare_research/source.json').read_text())
    for name in ('archive','manifest'):
        v.download(config[name+'_url'],work/(name+'.bin'),config[name+'_size'],config[name+'_sha256'])
    manifest=json.loads((work/'manifest.bin').read_text())
    cal=None;inst=None
    with tarfile.open(work/'archive.bin','r|gz') as z:
        for m in z:
            name=v.safe_name(m.name)
            if not (m.isfile() or m.isdir()):raise ValueError('Unsupported member')
            if name in ('qlib_bin/calendars/day.txt','qlib_bin/instruments/all.txt'):
                r=z.extractfile(m).read()
                if name.endswith('day.txt'):cal=r
                else:inst=r
    days=v.read_calendar(cal,config['requested_end'])
    if days[-1]!=manifest['target_trade_date']:raise ValueError('Manifest date mismatch')
    universe=sorted({line.split('\t')[0] for line in inst.decode().splitlines() if v.is_mainboard(line.split('\t')[0])})
    symbols=choose_symbols(universe,OLD_SYMBOLS)
    wanted=set(symbols);series={f:np.full((len(symbols),len(days)),np.nan,np.float32) for f in FIELDS};si={s:i for i,s in enumerate(symbols)};seen=set()
    with tarfile.open(work/'archive.bin','r|gz') as z:
        for m in z:
            name=v.safe_name(m.name);match=v.FEATURE.fullmatch(name)
            if match and match[1].upper() in wanted and match[2] in FIELDS:
                if name in seen or m.size>v.MAX_MEMBER_BYTES:raise ValueError('Duplicate or large field')
                seen.add(name);series[match[2]][si[match[1].upper()]]=align_feature(z.extractfile(m).read(),len(days))
    left=int(np.searchsorted(days,'2000-01-01'));days=days[left:]
    for f in FIELDS:series[f]=series[f][:,left:]
    np.savez_compressed(out/'prices_T.npz',symbols=np.array(symbols),days=np.array(days),**series)
    (out/'calendar.txt').write_text('\n'.join(days)+'\n')
    (out/'instruments_all.txt').write_bytes(inst)
    (out/'selected_symbols.json').write_text(json.dumps(symbols))
    (out/'fixed_source.json').write_text(json.dumps(config,indent=2))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    statusdir=out/'status';statusdir.mkdir(exist_ok=True)
    ctx=mp.get_context('spawn');workers=[]
    for j in range(2):
        p=ctx.Process(target=fetch_worker,args=(j,symbols[j::2],days,str(statusdir),360));p.start();workers.append(p)
    deadline=time.monotonic()+420
    for p in workers:
        p.join(max(0,deadline-time.monotonic()))
        if p.is_alive():p.kill();p.join()
    receipt={'utc':datetime.now(timezone.utc).isoformat(),'universe_codes':len(universe),'selected_codes':len(symbols),'selection':'fixed hash order excluding previous 114 codes and first 500 PIT_STATUS_V1 codes','source_identity_verified':True,'fields_read':len(seen),'calendar_start':days[0],'calendar_end':days[-1],'worker_exit_codes':[p.exitcode for p in workers],'status_unknown_is_not_normal':True,'new_clean_holdout':False,'reason':'Archive history has been used by other research; new to this branch only.'}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    for f in [Path(__file__),Path('scripts/ashare_research/verify_data.py'),Path('scripts/ashare_research/historical_status.py')]:
        (out/('source_'+f.name)).write_bytes(f.read_bytes())
    hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    (out/'HASHES.json').write_text(json.dumps(hashes,indent=2));print(json.dumps(receipt),flush=True)

if __name__=='__main__':
    if '--self-test' in sys.argv:self_test()
    else:main()
