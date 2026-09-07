import unittest
import numpy as np
from batch_account_study import elapsed_years
class DateCompatibilityTests(unittest.TestCase):
 def test_numpy_and_python_dates_match(self):
  self.assertAlmostEqual(elapsed_years(np.str_('2021-01-04'),np.str_('2026-09-04')),elapsed_years('2021-01-04','2026-09-04'))
 def test_exact_known_interval(self):
  self.assertAlmostEqual(elapsed_years('2020-01-01','2021-01-01'),366/365.25)
if __name__=='__main__':unittest.main()
