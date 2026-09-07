import unittest
import numpy as np
import pandas as pd
from alternative_study import alternative_signals, audit_result
from formula_study import simulate


def frame(c):
    c=np.asarray(c,dtype=float)
    return pd.DataFrame({'open':c,'high':c*1.01,'low':c*.99,'close':c,'volume':100.})

class AlternativeTests(unittest.TestCase):
    def test_flat_market_no_artificial_signal(self):
        x=alternative_signals(frame([10]*200))
        for k,v in x.items():
            if k.endswith('_BUY'): self.assertFalse(v.any(),k)
    def test_all_rules_share_maturity(self):
        x=alternative_signals(frame(np.arange(1,201)))
        for v in x.values(): self.assertFalse(v[:120].any())
        self.assertTrue(x['ELIGIBLE'][120:].all())
    def test_slow_trend_entry(self):
        x=alternative_signals(frame(np.linspace(10,30,200)))
        self.assertTrue(x['SLOW120_BUY'][-1]);self.assertFalse(x['SLOW120_SELL'][-1])
    def test_slow_trend_does_not_use_exit10(self):
        c=list(np.linspace(10,20,180))+[18.]
        x=alternative_signals(frame(c))
        self.assertTrue(x['BREAKOUT20_SELL'][-1]);self.assertFalse(x['SLOW120_SELL'][-1])
    def test_rsi_rebound_requires_previous_oversold(self):
        x=alternative_signals(frame([10]*130+[9,8,7,6,5,5.5]))
        self.assertTrue(x['RSI6_RECOVERY_BUY'][-1])
        self.assertFalse(x['RSI6_RECOVERY_BUY'][-2])
    def test_band_reentry_after_lower_band_breach(self):
        x=alternative_signals(frame([10]*130+[9,8,7,6,5,6.]))
        self.assertTrue(x['BAND_RECOVERY_BUY'][-1])
    def test_future_data_cannot_change_signals(self):
        df=frame(20+np.sin(np.arange(350)*.33)+np.arange(350)*.001)
        full=alternative_signals(df)
        for cut in [0,30,120,170,249,310]:
            short=alternative_signals(df.iloc[:cut])
            for k in full: np.testing.assert_array_equal(short[k],full[k][:cut])
    def test_rsi_definition_matches_sequential_smoothing(self):
        c=20+np.sin(np.arange(320)*.7)*4
        x=alternative_signals(frame(c));u=d=0.;r=[50.]
        for delta in np.diff(c):
            u=(5*u+max(delta,0))/6;d=(5*d+abs(delta))/6
            r.append(100*u/d if d else 50.)
        r=np.asarray(r)
        expected=np.r_[False,(r[:-1]<20)&(r[1:]>r[:-1])&(np.diff(c)>0)]
        expected[:120]=False
        np.testing.assert_array_equal(expected,x['RSI6_RECOVERY_BUY'])
    def test_independent_ledger_check(self):
        a=frame([10,10.2,10.4,10.6,10.8]).to_numpy()
        buy=np.array([1,0,0,0,0],bool);sell=np.array([0,0,0,1,0],bool)
        res=simulate(a,buy,sell,np.full(5,.0023),0)
        audit_result(res,a,np.full(5,.0023),1.)
        broken=dict(res);broken['cash']=res['cash']+.1
        with self.assertRaises(AssertionError): audit_result(broken,a,np.full(5,.0023),1.)

if __name__=='__main__': unittest.main()
