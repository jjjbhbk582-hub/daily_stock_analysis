"""Bounded data-only export for frozen U3 transport. No trading or strategy search."""
from pathlib import Path
import hashlib, importlib.util, json, os, sys

EXPECTED={
 'scripts/ashare_research_T/export_t.py':'c07a8955674f7e393d5f7e46c4c0017ed34305fca69138deb3b0126af240be4f',
 'scripts/ashare_research/verify_data.py':'e113d62c450d77fbfe25feae0dd6a34a64e9e60afafba75b263914fcd8c2dea9',
 'scripts/ashare_research/historical_status.py':'cde372e852582747776a475bdcd6a317720983e1df1522a90c12b118dff54ec5'}
EXPECTED_SELECTION='9e694adab254c188c63709e4cea215bb5cc1ac01ae69837cbb23b4f02706d61f'

def select_new(symbols,excluded,n=256):
    if isinstance(n,bool) or not isinstance(n,int) or n<=0:raise ValueError('n must be a positive integer')
    pool=set(map(str,symbols))-set(map(str,excluded))
    if len(pool)<n:raise ValueError('Insufficient predefined pool')
    return sorted(sorted(pool,key=lambda s:hashlib.sha256(('JZ_V_RAW_SAMPLE_V1|'+s).encode()).hexdigest())[:n])

def self_test():
    s=[f'SH600{i:03d}' for i in range(800)];blocked=s[:128]
    a=select_new(s,blocked);assert len(a)==256 and not set(a)&set(blocked)
    assert a==select_new(s[::-1]+s[:40],blocked) and a==sorted(a)
    for count in [0,-1,3.5,True,1000]:
        try:select_new(s,[],count)
        except ValueError:pass
        else:raise AssertionError('Bad count accepted')
    print('V deterministic selection self checks passed',flush=True)

def main():
    own=Path(__file__).resolve();out=Path(sys.argv[1]).resolve();old=Path(sys.argv[2]).resolve()
    for rel,digest in EXPECTED.items():
        if hashlib.sha256((old/rel).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen dependency mismatch: '+rel)
    spec=importlib.util.spec_from_file_location('frozen_t_export',old/'scripts/ashare_research_T/export_t.py')
    t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t);original_choose=t.choose_symbols
    def choose_v(symbols,old_symbols,n=256):
        original128=original_choose(symbols,old_symbols,128)
        earlier500=sorted(set(symbols),key=lambda s:hashlib.sha256(('PIT_STATUS_V1|'+s).encode()).hexdigest())[:500]
        chosen=select_new(symbols,set(original128)|set(old_symbols)|set(earlier500),n)
        if hashlib.sha256(json.dumps(chosen).encode()).hexdigest()!=EXPECTED_SELECTION:raise ValueError('Predeclared sample mismatch')
        return chosen
    t.choose_symbols=choose_v
    os.chdir(old);sys.argv=[str(own),str(out)];t.main()
    receipt=json.loads((out/'receipt.json').read_text())
    receipt.update(round='V',selected_codes=256,selection='JZ_V_RAW_SAMPLE_V1; exclude original U128, T OLD_SYMBOLS and first500 PIT_STATUS_V1',selection_sha256=EXPECTED_SELECTION,new_clean_holdout=False,reason='New U3 stock cross-section; archived market dates and source have already been studied elsewhere; not a pristine temporal holdout.')
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    (out/'source_export_v.py').write_bytes(own.read_bytes())
    hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name not in ('HASHES.json','run.log')}
    (out/'HASHES.json').write_text(json.dumps(hashes,indent=2))
    print('FINAL V RECEIPT '+json.dumps(receipt),flush=True)

if __name__=='__main__':
    if '--self-test' in sys.argv:self_test()
    else:main()
