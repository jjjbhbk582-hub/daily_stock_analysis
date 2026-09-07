"""Synthetic tests only; not evidence of investment profitability."""
import unittest
import numpy as np
import pandas as pd
from formula_study import signals, simulate


class FormulaStudyTests(unittest.TestCase):
    def bars(self, n=8):
        return np.column_stack([np.full(n,10.), np.full(n,11.),
                                np.full(n,9.), np.full(n,10.), np.ones(n)])

    def run_case(self, b=None, buy=None, sell=None, **kw):
        b = self.bars() if b is None else b
        n=len(b)
        buy=np.array([False]*n) if buy is None else np.array(buy,dtype=bool)
        sell=np.array([False]*n) if sell is None else np.array(sell,dtype=bool)
        return simulate(b,buy,sell,np.full(n,.0018),0,**kw)

    def test_no_signal_means_cash(self):
        r=self.run_case()
        np.testing.assert_array_equal(r['nav'],np.ones(8))
        self.assertEqual(r['trades'],[])

    def test_execution_after_signal_and_tplus1(self):
        r=self.run_case(buy=[1,0,0,0,0,0,0,0],sell=[0,1,0,0,0,0,0,0])
        t=r['trades'][0]
        self.assertEqual(tuple(t[:4]),(0,1,1,2))
        expected=10*(1-.0018)/(10*(1+.0013))-1
        self.assertAlmostEqual(t[9],expected)

    def test_last_signal_not_filled(self):
        r=self.run_case(buy=[0,0,0,0,0,0,0,1])
        self.assertEqual(r['entries'],0)

    def test_missing_buy_day_cancels(self):
        b=self.bars();b[1,:]=np.nan
        r=self.run_case(b=b,buy=[1,0,0,0,0,0,0,0])
        self.assertEqual(r['entries'],0)
        self.assertEqual(r['cancelled'],1)

    def test_sell_persists_across_missing_day(self):
        b=self.bars();b[2,:]=np.nan
        r=self.run_case(b=b,buy=[1,0,0,0,0,0,0,0],sell=[0,1,0,0,0,0,0,0])
        self.assertEqual(tuple(r['trades'][0][:4]),(0,1,1,3))

    def test_limit_rejects_chase(self):
        b=self.bars();b[1,0]=10.31;b[1,1]=11.
        r=self.run_case(b=b,buy=[1,0,0,0,0,0,0,0])
        self.assertEqual(r['entries'],0)

    def test_quantity_fixed_before_lower_open(self):
        b=self.bars();b[1,0]=9.
        r=self.run_case(b=b,buy=[1,0,0,0,0,0,0,0])
        self.assertAlmostEqual(r['units'],1/(10.3*1.0013))
        self.assertGreater(r['cash'],0)

    def test_gap_block_retains_original_sell_signal(self):
        b=self.bars(); b[2]=[9.,10.,8.,9.,1.]
        r=self.run_case(b=b,buy=[1,0,0,0,0,0,0,0],sell=[0,1,0,0,0,0,0,0])
        self.assertEqual(tuple(r['trades'][0][:4]),(0,1,1,3))
        self.assertEqual(r['blocked_sells'],1)

    def test_delay_two_is_not_next_valid_quote(self):
        r=self.run_case(buy=[1,0,0,0,0,0,0,0],sell=[0,0,1,0,0,0,0,0],delay=2)
        self.assertEqual(tuple(r['trades'][0][:4]),(0,2,2,4))

    def test_cost_scenario_same_plan_not_guaranteed_same_path(self):
        r=self.run_case(buy=[1,0,0,0,0,0,0,0],sell=[0,1,0,0,0,0,0,0],cost_multiple=2.)
        self.assertAlmostEqual(r['trades'][0][9],10*(1-.0036)/(10*1.0026)-1)

    def test_mark_open_position_no_fake_exit(self):
        r=self.run_case(buy=[1,0,0,0,0,0,0,0])
        self.assertEqual(len(r['trades']),0)
        self.assertGreater(r['units'],0)
        self.assertAlmostEqual(r['nav'][-1],r['cash']+10*r['units'])

    def test_prefix_execution(self):
        b=self.bars(15);buy=np.ones(15,dtype=bool);sell=np.arange(15)%3==0
        a=self.run_case(b=b,buy=buy,sell=sell)
        z=self.run_case(b=b[:8],buy=buy[:8],sell=sell[:8])
        np.testing.assert_array_equal(a['nav'][:8],z['nav'])
        self.assertEqual([t for t in a['trades'] if t[3]<8],z['trades'])

    def test_formula_history_only_and_warmup(self):
        rng=np.random.default_rng(20260907)
        c=np.exp(np.cumsum(rng.normal(0,.02,350)))
        df=pd.DataFrame({'open':c,'high':c*1.01,'low':c*.99,'close':c,'volume':1.})
        full=signals(df);small=signals(df.iloc[:250])
        for k in full:
            np.testing.assert_array_equal(full[k][:250],small[k])
            self.assertFalse(full[k][:120].any())

    def test_breakout_excludes_current_bar_in_previous_high(self):
        c=np.linspace(10,15,125)
        d=pd.DataFrame({'open':c,'high':c+.1,'low':c-.1,'close':c,'volume':1.})
        self.assertTrue(signals(d)['BREAKOUT20'][-1])

    def test_no_same_close_roundtrip(self):
        r=self.run_case(buy=np.ones(8,dtype=bool),sell=np.ones(8,dtype=bool))
        self.assertTrue(all(t[3]>t[1] for t in r['trades']))


if __name__=='__main__':
    unittest.main()
