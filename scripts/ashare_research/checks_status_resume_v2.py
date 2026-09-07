"""Synthetic resumability checks; no market-performance claims."""
import csv, gzip, json, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from status_resume_v2 import retry_query, save_rows, read_rows, merge_rows, remaining, load_saved, seed_history

DAYS=['2024-04-16','2024-04-17','2024-04-18']
ROWS=[['2024-04-16','sh.600000','1','0'],['2024-04-17','sh.600000','1','0']]
class ResumeTests(unittest.TestCase):
    def test_retry_reconnects_before_repeat(self):
        events=[]
        def q():
            events.append('query')
            if len(events)==1:raise ConnectionError('offline')
            return ROWS
        out,n=retry_query(q,lambda:events.append('login'),lambda n:None)
        self.assertEqual(out,ROWS);self.assertEqual(n,2)
        self.assertEqual(events,['query','login','query'])
    def test_retry_is_bounded(self):
        q=Mock(side_effect=TimeoutError('timeout'));login=Mock()
        with self.assertRaises(TimeoutError):retry_query(q,login,lambda n:None)
        self.assertEqual(q.call_count,2);self.assertEqual(login.call_count,1)
    def test_failure_is_not_empty_success(self):
        with self.assertRaises(RuntimeError):retry_query(Mock(side_effect=RuntimeError('bad')),lambda:None,lambda n:None)
    def test_success_never_reconnects(self):
        login=Mock();out,n=retry_query(lambda:ROWS,login,lambda n:None)
        self.assertEqual(n,1);login.assert_not_called()
    def test_saved_rows_are_exact_and_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p=save_rows(Path(d),'SH600000',ROWS,DAYS)
            self.assertEqual(read_rows(p),ROWS)
            self.assertFalse(list(Path(d).glob('*.partial')))
    def test_invalid_partial_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):save_rows(Path(d),'SH600000',ROWS+ROWS,DAYS)
            self.assertFalse(list(Path(d).glob('*.csv.gz')))
    def test_cross_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):save_rows(Path(d),'SH600001',ROWS,DAYS)
    def test_unknown_fields_are_preserved(self):
        r=[['2024-04-17','sh.600000','','']]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(read_rows(save_rows(Path(d),'SH600000',r,DAYS)),r)
    def test_conflicting_seed_is_rejected(self):
        dst={};merge_rows(dst,'SH600000',ROWS)
        with self.assertRaises(ValueError):merge_rows(dst,'SH600000',[['2024-04-16','sh.600000','1','1']])
    def test_identical_duplicate_seed_is_not_counted_twice(self):
        dst={};merge_rows(dst,'SH600000',ROWS);merge_rows(dst,'SH600000',ROWS)
        self.assertEqual(len(dst),1)
    def test_skip_completed_only(self):
        x=['SH600000','SH600001','SH600002'];got={'SH600000':ROWS}
        self.assertEqual(set(remaining(x,got)),set(x[1:]))
        self.assertEqual(remaining(x,got),remaining(x[::-1],got))
    def test_partials_ignored_after_crash(self):
        with tempfile.TemporaryDirectory() as d:
            save_rows(Path(d),'SH600000',ROWS,DAYS)
            (Path(d)/'SH600001.csv.gz.partial').write_bytes(b'broken')
            self.assertEqual(set(load_saved(Path(d),DAYS)),{'SH600000'})
    def test_seed_rejects_missing_accepted_raw(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);np.savez_compressed(p/'status_0.npz',symbols=['SH600000'],days=DAYS,isST=[[-1,-1,-1]],tradestatus=[[-1,-1,-1]])
            (p/'fetch_0.json').write_text(json.dumps([{'symbol':'SH600000','status':'received','rows':2}]))
            with self.assertRaises((ValueError,FileNotFoundError)):seed_history(p,DAYS)

class MergedCheckpointTests(unittest.TestCase):
    def test_merged_roundtrip_then_skip(self):
        from status_resume_v2 import load_merged
        import lzma
        from historical_status import align_status
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);st,tr,meta=align_status(ROWS,DAYS,'SH600000')
            np.savez_compressed(p/'states.npz',symbols=['SH600000'],days=DAYS,isST=[st],tradestatus=[tr])
            (p/'accepted.json').write_text(json.dumps([dict(symbol='SH600000',status='received',**meta)]))
            with lzma.open(p/'provider_records.csv.xz','wt',newline='') as f:
                w=csv.writer(f);w.writerow(['date','code','tradestatus','isST']);w.writerows(ROWS)
            got=load_merged(p,DAYS)
            self.assertEqual(got,{'SH600000':ROWS});self.assertEqual(remaining(['SH600000'],got),[])
    def test_saved_payload_corruption_rejected(self):
        from status_resume_v2 import verify_seed_hashes
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data';p.mkdir();(p/'file.txt').write_bytes(b'x')
            with self.assertRaises(ValueError):verify_seed_hashes(Path(d),{'data/file.txt':hashlib.sha256(b'y').hexdigest()})

if __name__=='__main__':unittest.main()
