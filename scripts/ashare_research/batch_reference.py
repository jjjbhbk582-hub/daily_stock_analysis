"""Same-source index price reference only, never a traded outside-scope asset."""
import argparse,tarfile
from pathlib import Path
import numpy as np
import pandas as pd
from verify_data import safe_name,decode_feature,read_calendar

def rebase_reference(values):
 values=np.asarray(values,float)
 if not len(values) or not np.isfinite(values).all() or (values<=0).any():raise ValueError('Missing price reference')
 return values/values[0]

def main():
 p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('output',type=Path);a=p.parse_args();raw={}
 with tarfile.open(a.archive,'r|gz') as z:
  for m in z:
   name=safe_name(m.name)
   if name=='qlib_bin/calendars/day.txt' or name in ('qlib_bin/features/sh000300/close.day.bin','qlib_bin/features/sh000905/close.day.bin'):
    raw[name]=z.extractfile(m).read()
 days=read_calendar(raw['qlib_bin/calendars/day.txt'],'2026-09-04');result={'date':days}
 for sym in ('sh000300','sh000905'):
  key=f'qlib_bin/features/{sym}/close.day.bin'
  if key not in raw:continue
  start,values=decode_feature(raw[key],len(days));c=np.full(len(days),np.nan);c[start:start+len(values)]=values;result[sym+'_adjusted_price_reference']=c
 pd.DataFrame(result).to_csv(a.output/'index_price_reference.csv',index=False)
if __name__=='__main__':main()
