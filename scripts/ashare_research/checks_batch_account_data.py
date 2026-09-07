import unittest
import numpy as np
from batch_account_study import restored_units, eligibility
class AccountDataTests(unittest.TestCase):
 def test_price_hands_and_thousands(self):
  raw,shares,money=restored_units(np.array([6.9059873]),np.array([2375605.8]),np.array([1640078.396]),np.array([1.3154261]))
  self.assertAlmostEqual(float(raw[0]),5.25,2)
  self.assertAlmostEqual(float(shares[0])/100,3124934,0)
  self.assertAlmostEqual(float(money[0]),1640078396,1)
 def test_bad_factor_rejected(self):
  with self.assertRaises(ValueError):restored_units(np.array([1.]),np.array([1.]),np.array([1.]),np.array([0.]))
 def test_delisting_case_causal_and_quarantine(self):
  days=np.array(['2021-04-01','2021-04-06','2021-04-07','2021-04-15'])
  s=np.zeros(4,np.int8);t=np.ones(4,np.int8)
  e=eligibility('SZ002450',days,s,t)
  np.testing.assert_array_equal(e,[True,True,False,False])
  np.testing.assert_array_equal(e[:2],eligibility('SZ002450',days[:2],s[:2],t[:2]))
 def test_unknown_not_normal_and_no_postST_return(self):
  d=np.array(['2020-01-01','2020-01-02','2020-01-03','2020-01-04'])
  np.testing.assert_array_equal(eligibility('SH600001',d,np.array([-1,0,1,0]),np.ones(4)),[False,True,False,False])
if __name__=='__main__':unittest.main()
