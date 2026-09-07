import io,json,tarfile,tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from batch_account_study import read_panel,prepare,independent_audit
from batch_signals import compute_signals
from checks_batch_portfolio import panel
from batch_portfolio import simulate_portfolio
class BatchIntegrationTests(unittest.TestCase):
 def test_whole_archive_offset_status_and_sample(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);days=pd.bdate_range('2020-01-01',periods=300).strftime('%Y-%m-%d').tolist();sym='SH600001'
   with tarfile.open(p/'a.tgz','w:gz') as z:
    def add(name,content):
     m=tarfile.TarInfo('qlib_bin/'+name);m.size=len(content);z.addfile(m,io.BytesIO(content))
    add('calendars/day.txt',('\n'.join(days)+'\n').encode());add('instruments/all.txt',f'{sym}\t{days[0]}\t{days[-1]}\n'.encode())
    for k,v in dict(open=20,high=21,low=19,close=20,volume=100000,factor=2,amount=200000).items():
     add('features/sh600001/'+k+'.day.bin',np.r_[0,np.full(300,v)].astype('<f4').tobytes())
   np.savez(p/'state.npz',symbols=[sym],days=days,isST=np.zeros((1,300),np.int8),tradestatus=np.ones((1,300),np.int8))
   d=read_panel(p/'a.tgz',days[-1]);b,s,n=prepare(d,p/'state.npz',p)
   self.assertEqual(d['raw_volume'][0,-1],20000000);self.assertEqual(d['amount'][0,-1],200000000)
   self.assertEqual(float(d['score'][0,-1]),200000000);self.assertEqual(b.shape,(4,1,300));self.assertFalse(b.any())
   self.assertTrue((p/'same_source_sample.npz').exists())
 def test_confirmed_line_not_backdated(self):
  c=10+np.arange(350)*.03;h=c+.1;h[280]=22;h[300]=21
  d=dict(close=c,high=h,open=c,low=c-.1,volume=c*0+1e6)
  r=compute_signals(d);ids=np.flatnonzero(r['buy'][3]);self.assertTrue(len(ids)>0)
  self.assertGreater(ids[0],303);self.assertFalse(np.isfinite(r['trendline'][302]));self.assertTrue(np.isfinite(r['trendline'][303]))
 def test_tampered_cash_rejected(self):
  d=panel();b=np.zeros((2,8),bool);b[0,0]=True;r=simulate_portfolio(d,b,b*False,0,8)
  independent_audit(r);r['cash'][-1]+=1
  with self.assertRaises(AssertionError):independent_audit(r)
if __name__=='__main__':unittest.main()
