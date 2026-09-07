import unittest
import numpy as np
import pandas as pd
from exit_policy_study import simulate_exit, indicators
from formula_study import simulate
from alternative_study import alternative_signals

class ExitPolicyTests(unittest.TestCase):
    def sample(self,n=40):
        b=np.tile([100.,101.,99.,100.,1000.],(n,1))
        buy=np.zeros(n,bool);buy[1]=True
        profit=np.zeros(n,bool);low=np.zeros(n,bool)
        atr=np.full(n,2.)
        costs=np.full(n,.0023)
        return b,buy,profit,low,atr,costs
    def test_legacy_exact(self):
        rng=np.random.default_rng(71);n=240
        c=100*np.exp(np.cumsum(rng.normal(0,.02,n)))
        o=c*np.exp(rng.normal(0,.005,n))
        b=np.column_stack([o,np.maximum(o,c)*1.01,np.minimum(o,c)*.99,c,np.ones(n)])
        buy=rng.random(n)<.16;profit=rng.random(n)<.04;low=rng.random(n)<.05
        b[30:33]=np.nan
        for mul,delay in [(1.,1),(2.,1),(1.,2)]:
            a=simulate(b,buy,profit|low,np.full(n,.0023),5,mul,delay)
            d=simulate_exit(b,buy,profit,low,np.full(n,2.),np.full(n,.0023),5,'D0',mul,delay)
            for k in ('nav','exposure','trades'):
                np.testing.assert_array_equal(a[k],d[k])
            for k in ('cash','units','mark','entries','cancelled','blocked_sells','open_entry_cost'):
                self.assertEqual(a[k],d[k])
    def test_time_ten_sessions(self):
        r=simulate_exit(*self.sample(),0,'D1')
        self.assertEqual(r['trades'][0][1:4],(2,11,12))
        self.assertEqual(r['details'][0][0],4)
    def test_fixed_stop_next_open_not_guaranteed_eight_percent(self):
        b,buy,p,l,a,c=self.sample();b[5]=[100,101,89,90,1000];b[6]=[88,90,87,89,1000]
        r=simulate_exit(b,buy,p,l,a,c,0,'D2')
        self.assertEqual(r['trades'][0][2:4],(5,6))
        self.assertEqual(r['details'][0][0],8)
        self.assertLess(r['trades'][0][-1],-.08)
    def test_atr_fixed_from_signal_day(self):
        b,buy,p,l,a,c=self.sample();a[2:]=30;b[4,3]=95;b[4,2]=94
        r=simulate_exit(b,buy,p,l,a,c,0,'D3')
        self.assertEqual(r['trades'][0][2],4)
        self.assertEqual(r['details'][0][0],16)
        self.assertEqual(r['details'][0][-1],96.)
    def test_no_new_low_exit_in_time_policy(self):
        b,buy,p,l,a,c=self.sample();l[3]=True
        r=simulate_exit(b,buy,p,l,a,c,0,'D1')
        self.assertEqual(r['trades'][0][2],11)
    def test_time_signal_during_missing_quotes(self):
        b,buy,p,l,a,c=self.sample();b[10:15]=np.nan
        r=simulate_exit(b,buy,p,l,a,c,0,'D2')
        self.assertEqual(r['trades'][0][2:4],(11,15))
    def test_gap_exit_persists_original_reason(self):
        b,buy,p,l,a,c=self.sample();p[4]=True;b[5]=[90,92,89,90,1000]
        r=simulate_exit(b,buy,p,l,a,c,0,'D0')
        self.assertEqual(r['trades'][0][2:4],(4,6))
        self.assertEqual(r['details'][0][0],1)
    def test_joint_reason_mask(self):
        b,buy,p,l,a,c=self.sample();p[4]=True;l[4]=True
        r=simulate_exit(b,buy,p,l,a,c,0,'D0')
        self.assertEqual(r['details'][0][0],3)
    def test_no_future_execution_at_end(self):
        b,buy,p,l,a,c=self.sample();buy[:]=False;buy[-1]=True
        r=simulate_exit(b,buy,p,l,a,c,0,'D3')
        self.assertEqual(r['entries'],0)
        self.assertEqual(len(r['trades']),0)
    def test_pending_buy_missing_expires(self):
        b,buy,p,l,a,c=self.sample();b[2]=np.nan
        r=simulate_exit(b,buy,p,l,a,c,0,'D2')
        self.assertEqual(r['cancelled'],1);self.assertEqual(r['entries'],0)
    def test_prefix_portfolio(self):
        args=self.sample();args[2][4]=True;args[1][7]=True
        for rule in ('D0','D1','D2','D3'):
            a=simulate_exit(*args,0,rule)
            b=simulate_exit(*(x[:20] for x in args),0,rule)
            np.testing.assert_array_equal(a['nav'][:20],b['nav'])
            self.assertEqual([x for x in a['trades'] if x[3]<20],b['trades'])
    def test_indicators_match_original(self):
        rng=np.random.default_rng(22);c=100*np.exp(np.cumsum(rng.normal(0,.03,500)))
        f=pd.DataFrame({'open':c,'high':c*1.01,'low':c*.99,'close':c,'volume':1.})
        buy,profit,low,atr=indicators(f)
        old=alternative_signals(f)
        np.testing.assert_array_equal(buy,old['RSI6_RECOVERY_BUY'])
        np.testing.assert_array_equal(profit|low,old['RSI6_RECOVERY_SELL'])
        small=indicators(f.iloc[:250])
        for x,y in zip((buy,profit,low,atr),small):np.testing.assert_array_equal(x[:250],y)

if __name__=='__main__':unittest.main()
