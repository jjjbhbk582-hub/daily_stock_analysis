"""Synthetic checks for the frozen volume shock study; not market evidence."""
import unittest
import numpy as np
import pandas as pd
from volume_shock_signals import volume_signals, independent_flags, block_interval
from strict_mainboard_scope import simulate_scope


def frame(volume=200.):
    n=140
    f=pd.DataFrame(dict(open=np.full(n,100.),high=np.full(n,101.),low=np.full(n,99.),
                        close=np.full(n,100.),volume=np.full(n,100.)))
    f.loc[130,['high','low','close','volume']]=[107.,96.,96.,volume]
    return f

class VolumeTests(unittest.TestCase):
    def test_no_signal_on_flat_prices(self):
        f=frame().iloc[:130]
        self.assertFalse(volume_signals(f)['V0'].any())
    def test_prior_atr_excludes_signal_range(self):
        s=volume_signals(frame())
        self.assertTrue(s['V0'][130]);self.assertEqual(s['ATR_PREV'][130],2.)
    def test_prior_volume_excludes_current(self):
        s=volume_signals(frame(151.))
        self.assertEqual(s['VOL_PREV'][130],100.);self.assertTrue(s['VH'][130])
    def test_low_volume_subset(self):
        s=volume_signals(frame(80.));self.assertTrue(s['VL'][130]);self.assertFalse(s['VH'][130])
    def test_middle_volume_only_unfiltered(self):
        s=volume_signals(frame(125.));self.assertTrue(s['V0'][130]);self.assertFalse(s['VH'][130]|s['VL'][130])
    def test_maturity_gate(self):
        f=frame();f.loc[110]=f.loc[130];s=volume_signals(f)
        self.assertFalse(s['V0'][:120].any())
    def test_constant_scale_invariance(self):
        f=frame();g=f.copy();g.loc[:,['open','high','low','close']]*=7;g.volume*=3
        a,b=volume_signals(f),volume_signals(g)
        for k in ('V0','VH','VL','RECOVER5'):np.testing.assert_array_equal(a[k],b[k])
    def test_future_prefix(self):
        f=frame();a,b=volume_signals(f),volume_signals(f.iloc[:132])
        for k in a:np.testing.assert_allclose(a[k][:132],b[k],equal_nan=True)
    def test_independent_loop(self):
        f=frame();a=volume_signals(f);b=independent_flags(f)
        for k in b:np.testing.assert_array_equal(a[k],b[k])
    def test_invalid_inputs_rejected(self):
        f=frame();f.loc[20,'volume']=0
        with self.assertRaises(ValueError):volume_signals(f)
    def test_empty(self):
        self.assertEqual(len(volume_signals(frame().iloc[:0])['V0']),0)
    def test_bootstrap_zero(self):
        r=block_interval(np.zeros(80));self.assertEqual(r['lower_annual_log'],0.);self.assertEqual(r['upper_annual_log'],0.)
    def test_bootstrap_constant(self):
        r=block_interval(np.full(80,.001))
        self.assertAlmostEqual(r['lower_annual_log'],.252);self.assertAlmostEqual(r['upper_annual_log'],.252)
    def test_bootstrap_deterministic(self):
        x=np.linspace(-.01,.01,80);self.assertEqual(block_interval(x),block_interval(x))
    def test_st_entry_is_rejected(self):
        f=frame();s=volume_signals(f);n=len(f);st=np.zeros(n,dtype=int);st[131]=1
        r=simulate_scope(f.to_numpy(),s['V0'],s['RECOVER5'],np.zeros(n,bool),s['ATR_PREV'],
            np.full(n,.0023),120,'D2',st,np.ones(n,int),'SH600001')
        self.assertEqual(r['entries'],0);self.assertEqual(r['status_cancelled_buys'],1)
    def test_no_same_day_resale(self):
        f=frame();f.loc[131,['open','low']]=[96.,95.];s=volume_signals(f);n=len(f)
        r=simulate_scope(f.to_numpy(),s['V0'],s['RECOVER5'],np.zeros(n,bool),s['ATR_PREV'],
            np.full(n,.0023),120,'D2',np.zeros(n,int),np.ones(n,int),'SH600001')
        self.assertEqual(len(r['trades']),1)
        for t in r['trades']:self.assertLess(t[1],t[3])

if __name__=='__main__':unittest.main()
