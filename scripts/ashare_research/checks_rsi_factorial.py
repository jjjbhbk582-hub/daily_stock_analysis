"""Controlled-data checks; not market evidence."""
import unittest
import numpy as np
import pandas as pd
from alternative_study import alternative_signals
from formula_study import simulate
from rsi_factorial import factorial_signals, rsi_reference, audit_account, RULES


def frame(seed=17, n=550):
    rng=np.random.default_rng(seed)
    c=30*np.exp(np.cumsum(rng.normal(.0002,.02,n)))
    return pd.DataFrame({'open':c,'high':c*1.01,'low':c*.99,'close':c,'volume':np.ones(n)*100})

class RSIFactorialChecks(unittest.TestCase):
    def test_baseline_unchanged(self):
        f=frame();a=factorial_signals(f);b=alternative_signals(f)
        for side in ('BUY','SELL'):
            np.testing.assert_array_equal(a['R0_'+side],b['RSI6_RECOVERY_'+side])
    def test_filter_is_only_addition(self):
        f=frame();s=factorial_signals(f);flt=(f.close>f.close.rolling(120).mean()).to_numpy()
        np.testing.assert_array_equal(s['R1_BUY'],s['R0_BUY']&flt)
        np.testing.assert_array_equal(s['R1_SELL'],s['R0_SELL'])
    def test_exit_is_only_change(self):
        s=factorial_signals(frame())
        np.testing.assert_array_equal(s['R2_BUY'],s['R0_BUY'])
        self.assertTrue(np.all(~s['R0_SELL']|s['R2_SELL']))
        self.assertTrue(np.any(s['R2_SELL']&~s['R0_SELL']))
    def test_joint_identity(self):
        s=factorial_signals(frame())
        np.testing.assert_array_equal(s['R3_BUY'],s['R1_BUY'])
        np.testing.assert_array_equal(s['R3_SELL'],s['R2_SELL'])
    def test_maturity(self):
        s=factorial_signals(frame())
        for r in RULES:
            self.assertFalse(s[r+'_BUY'][:120].any())
            self.assertFalse(s[r+'_SELL'][:120].any())
    def test_flat_has_no_entry(self):
        f=frame();f[['open','high','low','close']]=1.
        s=factorial_signals(f)
        for r in RULES:self.assertFalse(s[r+'_BUY'].any())
    def test_prefix(self):
        f=frame();a=factorial_signals(f)
        for n in (0,1,119,120,250,481):
            b=factorial_signals(f.iloc[:n])
            for k in a:np.testing.assert_array_equal(a[k][:n],b[k])
    def test_sequential_rsi(self):
        c=frame().close;d=c.diff().fillna(0)
        u=d.clip(lower=0).ewm(alpha=1/6,adjust=False).mean()
        a=d.abs().ewm(alpha=1/6,adjust=False).mean()
        expected=(100*u/a.replace(0,np.nan)).fillna(50).to_numpy()
        np.testing.assert_allclose(rsi_reference(c.to_numpy()),expected,atol=5e-12,rtol=0)
    def test_zero_denominator_reference(self):
        np.testing.assert_array_equal(rsi_reference(np.ones(60)),np.full(60,50.))
    def test_accounts(self):
        f=frame();a=factorial_signals(f);bars=f.to_numpy();costs=np.full(len(f),.0023)
        for r in RULES:
            res=simulate(bars,a[r+'_BUY'],a[r+'_SELL'],costs,120)
            err=audit_account(res,bars,costs,1.)
            self.assertLess(err,1e-9)
    def test_tampered_ledger_rejected(self):
        f=frame();a=factorial_signals(f);bars=f.to_numpy();costs=np.full(len(f),.0023)
        res=simulate(bars,a['R0_BUY'],a['R0_SELL'],costs,120)
        self.assertGreater(len(res['trades']),0)
        res['cash']+=.1
        with self.assertRaises(AssertionError):audit_account(res,bars,costs,1.)

if __name__=='__main__':unittest.main()
