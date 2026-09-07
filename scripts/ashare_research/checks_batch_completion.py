import csv,json,lzma,tempfile,unittest
from pathlib import Path
import numpy as np
from batch_completion import seed_to_checkpoints,consolidate
from status_resume_v2 import save_rows
class BatchCompletionTests(unittest.TestCase):
 def test_completed_only_and_exact_roundtrip(self):
  days=['2020-01-02','2020-01-03'];syms=['SH600001','SH600002']
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);seed=root/'seed';seed.mkdir();out=root/'out';out.mkdir()
   rows=[['2020-01-02','sh.600001','1','0'],['2020-01-03','sh.600001','1','1']]
   np.savez_compressed(seed/'states.npz',symbols=syms,days=days,isST=np.array([[0,1],[-1,-1]],np.int8),tradestatus=np.array([[1,1],[-1,-1]],np.int8))
   (seed/'accepted.json').write_text(json.dumps([{'symbol':syms[0],'rows':2}]))
   with lzma.open(seed/'provider_records.csv.xz','wt',newline='') as f:
    w=csv.writer(f);w.writerow(['date','code','tradestatus','isST']);w.writerows(rows)
   got=seed_to_checkpoints(seed,out)
   self.assertEqual(got[2],['SH600001']);self.assertFalse((out/'new_records/SH600002.csv.gz').exists())
   receipt=consolidate(out,days,syms,['SH600001'])
   self.assertEqual(receipt['received_codes'],1);self.assertEqual(receipt['provider_rows'],2)
   self.assertEqual(receipt['pending_codes'],1)
   with np.load(out/'merged_status/states.npz') as z:np.testing.assert_array_equal(z['isST'],[[0,1],[-1,-1]])
 def test_new_complete_response_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'new_records').mkdir()
   days=['2020-01-02'];syms=['SH600001','SH600002']
   save_rows(root/'new_records',syms[1],[['2020-01-02','sh.600002','1','0']],days)
   got=consolidate(root,days,syms,[])
   self.assertEqual(got['newly_downloaded'],1)
 def test_empty_response_not_completion(self):
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaises(ValueError):save_rows(Path(tmp),'SH600001',[],['2020-01-02'])
 def test_wrong_seed_row_count_fails(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);seed=root/'s';seed.mkdir();out=root/'o';out.mkdir()
   np.savez_compressed(seed/'states.npz',symbols=['SH600001'],days=['2020-01-02'],isST=np.array([[0]],np.int8),tradestatus=np.array([[1]],np.int8))
   (seed/'accepted.json').write_text(json.dumps([{'symbol':'SH600001','rows':2}]))
   with lzma.open(seed/'provider_records.csv.xz','wt',newline='') as f:
    w=csv.writer(f);w.writerow(['date','code','tradestatus','isST']);w.writerow(['2020-01-02','sh.600001','1','0'])
   with self.assertRaises(ValueError):seed_to_checkpoints(seed,out)
if __name__=='__main__':unittest.main()
