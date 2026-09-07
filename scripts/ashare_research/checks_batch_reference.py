import unittest
import numpy as np
from batch_reference import rebase_reference
class ReferenceTests(unittest.TestCase):
 def test_missing_start_not_invented(self):
  with self.assertRaises(ValueError):rebase_reference(np.array([np.nan,2.,3.]))
 def test_normalized_index_just_price_reference(self):
  np.testing.assert_array_equal(rebase_reference(np.array([2.,3.,2.])),[1.,1.5,1.])
if __name__=='__main__':unittest.main()
