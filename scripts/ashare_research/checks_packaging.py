import gzip,lzma,tempfile,unittest
from pathlib import Path
from pack_evidence import compact

class PackagingTests(unittest.TestCase):
    def test_lossless_no_record_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'trades.csv.gz';raw=b'a,b,c\n'+b'1,2,3\n'*20000
            with gzip.open(p,'wb') as f:f.write(raw)
            out=compact(Path(d))
            self.assertEqual(len(out),1)
            target=Path(d)/out[0]['output']
            actual=lzma.open(target,'rb').read() if target.suffix=='.xz' else gzip.open(target,'rb').read()
            self.assertEqual(raw,actual)
            self.assertTrue(out[0]['decoded_bytes_verified'])

    def test_non_csv_evidence_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.md';p.write_text('keep')
            self.assertEqual(compact(Path(d)),[])
            self.assertEqual(p.read_text(),'keep')
