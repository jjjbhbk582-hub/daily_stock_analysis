"""Exact CSV trade compression: dictionary text, shuffled numeric bytes, cost XOR.
A full original-byte roundtrip must pass before an input may be removed.
"""
import argparse,csv,hashlib,json,lzma,tempfile,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
HEADER=['period','rule','scenario','symbol','buy_signal','buy_date','sell_signal','sell_date','buy_price','sell_price','units','entry_cost']

def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def restore(source,target):
 with zipfile.ZipFile(source) as z:
  m=json.loads(z.read('metadata.json'));n=m['rows'];arrays=[];numeric=[]
  for j,spec in enumerate(m['fields']):
   dt=np.dtype(spec['dtype']);b=lzma.decompress(z.read(f'{j}.xz'))
   a=np.frombuffer(b,np.uint8).reshape(dt.itemsize,n).T.copy().ravel().view(dt)
   if j<8:arrays.append(np.asarray(spec['values'],dtype=object)[a])
   else:numeric.append(a.astype(np.float64) if j<11 else a)
  mul=np.where(arrays[2]=='double_cost',2.,1.)
  predicted=numeric[2]*numeric[0]*(1+.0013*mul)
  actual=(predicted.view(np.uint64)^numeric[3]).view(np.float64)
  numeric[3]=actual
  patches={int(k):{int(i):v for i,v in vals.items()} for k,vals in m['patches'].items()}
  with open(target,'w',encoding='utf-8',newline='') as out:
   w=csv.writer(out);w.writerow(HEADER)
   for i in range(n):
    row=[a[i] for a in arrays]
    row.extend(patches.get(j,{}).get(i,repr(float(numeric[j-8][i]))) for j in range(8,12))
    w.writerow(row)
 if digest(target)!=m['original_csv_sha256']:raise ValueError('Exact original-byte verification failed')
 return m

def pack(source,target):
 source=Path(source);target=Path(target)
 with tempfile.TemporaryDirectory() as td:
  raw=Path(td)/'input.csv'
  with lzma.open(source,'rb') as inp,raw.open('wb') as out:
   for b in iter(lambda:inp.read(1<<20),b''):out.write(b)
  df=pd.read_csv(raw,dtype=str,keep_default_na=False)
  if list(df)!=HEADER:raise ValueError('Unexpected trade CSV schema')
  numbers=[df[c].to_numpy().astype(np.float64) for c in HEADER[8:]]
  if not all(np.isfinite(a).all() for a in numbers):raise ValueError('Nonfinite trade values')
  mul=np.where(df.scenario=='double_cost',2.,1.)
  predicted=numbers[2]*numbers[0]*(1+.0013*mul)
  residual=numbers[3].view(np.uint64)^predicted.view(np.uint64)
  m={'format':'exact-trade-csv-v1','rows':len(df),'fields':[],'patches':{},'original_csv_sha256':digest(raw),'original_xz_sha256':digest(source)}
  with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED) as z:
   for j,c in enumerate(HEADER):
    spec={}
    if j<8:
     a,values=pd.factorize(df[c],sort=False);a=a.astype('<u2' if len(values)<65536 else '<u4');spec['values']=values.tolist()
    else:
     f=numbers[j-8]
     patches={i:s for i,s in enumerate(df[c]) if repr(float(f[i]))!=s}
     if patches:m['patches'][str(j)]=patches
     if j==11:a=residual.astype('<u8')
     elif j in (8,9) and np.array_equal(f.astype(np.float32).astype(np.float64),f):a=f.astype('<f4')
     else:a=f.astype('<f8')
    spec['dtype']=a.dtype.str;m['fields'].append(spec)
    shuffled=a.view(np.uint8).reshape(len(a),a.dtype.itemsize).T.copy().tobytes()
    z.writestr(f'{j}.xz',lzma.compress(shuffled,preset=7))
   z.writestr('metadata.json',json.dumps(m,ensure_ascii=False))
  restore(target,Path(td)/'restored.csv')
  return {'original_bytes':source.stat().st_size,'packed_bytes':target.stat().st_size,'rows':len(df),'exact_original_bytes_verified':True,'patches':sum(len(x) for x in m['patches'].values())}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['pack','restore']);p.add_argument('source',type=Path);p.add_argument('target',type=Path);a=p.parse_args();print(json.dumps(pack(a.source,a.target) if a.mode=='pack' else restore(a.source,a.target)))
