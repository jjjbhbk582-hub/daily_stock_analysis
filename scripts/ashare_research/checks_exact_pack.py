import csv,io,lzma,tempfile,unittest
from pathlib import Path
import numpy as np
from pack_exact import pack,restore,HEADER
class ExactPackTests(unittest.TestCase):
 def test_float64_bits_and_original_csv_are_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);s=io.StringIO(newline='');w=csv.writer(s);w.writerow(HEADER)
   bp=float(np.float32(.314159));sp=float(np.float32(.1234));u=1.2345678901234567
   w.writerow(['p','r','base','SH600000','2015-01-01','2015-01-02','2015-01-03','2015-01-04',bp,sp,u,u*bp*1.0013])
   w.writerow(['p','r','double_cost','SZ000001','2015-01-01','2015-01-02','2015-01-03','2015-01-04','1.000000',sp,u,1.2])
   b=s.getvalue().encode();(p/'t.xz').write_bytes(lzma.compress(b));pack(p/'t.xz',p/'t.zip');restore(p/'t.zip',p/'r.csv');self.assertEqual(b,(p/'r.csv').read_bytes())
 def test_non_float32_price_uses_float64(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);s=io.StringIO(newline='');w=csv.writer(s);w.writerow(HEADER)
   w.writerow(['p','r','base','SH600000','a','b','c','d',1.1234567890123457,2.,3.,4.])
   b=s.getvalue().encode();(p/'t.xz').write_bytes(lzma.compress(b));pack(p/'t.xz',p/'t.zip');restore(p/'t.zip',p/'r.csv');self.assertEqual(b,(p/'r.csv').read_bytes())
if __name__=='__main__':unittest.main()
