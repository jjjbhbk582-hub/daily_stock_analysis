import csv,json,lzma,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from batch_closeout import seed_to_checkpoints
class CheckpointCostTests(unittest.TestCase):
 def test_each_compressed_matrix_is_loaded_once(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);seed=p/'seed';seed.mkdir();out=p/'out';out.mkdir();syms=['SH600001','SH600002']
   np.savez(seed/'states.npz',symbols=syms,days=['2020-01-02'],isST=np.zeros((2,1),np.int8),tradestatus=np.ones((2,1),np.int8))
   (seed/'accepted.json').write_text(json.dumps([{'symbol':s,'rows':1} for s in syms]))
   with lzma.open(seed/'provider_records.csv.xz','wt',newline='') as f:
    w=csv.writer(f);w.writerow(['date','code','tradestatus','isST']);w.writerows([['2020-01-02',s[:2].lower()+'.'+s[2:],'1','0'] for s in syms])
   actual=np.load;calls={}
   class Once:
    def __enter__(self):self.z=actual(seed/'states.npz');return self
    def __exit__(self,*args):self.z.close()
    def __getitem__(self,key):
     calls[key]=calls.get(key,0)+1
     if key in ('isST','tradestatus') and calls[key]>1:raise AssertionError('Repeated whole-matrix decompression')
     return self.z[key]
   with patch('batch_closeout.np.load',return_value=Once()):seed_to_checkpoints(seed,out)
if __name__=='__main__':unittest.main()
