"""User-scope regression tests. Synthetic examples are not market evidence."""
import unittest
import numpy as np
from strict_mainboard_scope import simulate_scope
from exit_policy_study import simulate_exit


def inputs(n=20):
    bars=np.tile([10.,10.1,9.9,10.,1000.],(n,1))
    buy=np.zeros(n,bool);buy[1]=True
    target=np.zeros(n,bool);low=target.copy();atr=np.ones(n)
    return bars,buy,target,low,atr,np.full(n,.0023),np.zeros(n,np.int8),np.ones(n,np.int8)


def run(x,symbol='SH600000',rule='D0',mode='strict',**kw):
    b,buy,target,low,atr,cost,st,tr=x
    return simulate_scope(b,buy,target,low,atr,cost,0,rule,st,tr,symbol,mode=mode,**kw)


class ScopeTests(unittest.TestCase):
    def test_board_rejects_all_excluded_markets(self):
        for symbol in ['SH688001','SZ300001','SZ301001','BJ920001','SH900901','SZ200001','SH000001','AAPL','600000']:
            with self.subTest(symbol=symbol),self.assertRaises(ValueError):run(inputs(),symbol)
    def test_allowed_boards(self):
        for symbol in ['SH600000','SH601000','SH603000','SH605000','SZ000001','SZ001001','SZ002001','SZ003001']:
            self.assertEqual(run(inputs(),symbol)['entries'],1)
    def test_signal_day_st_blocked(self):
        x=inputs();x[6][1]=1;self.assertEqual(run(x)['entries'],0)
    def test_signal_day_unknown_blocked(self):
        x=inputs();x[6][1]=-1;self.assertEqual(run(x)['entries'],0)
    def test_execution_day_st_cancels_without_rewriting_signal(self):
        x=inputs();x[6][2]=1;r=run(x)
        self.assertEqual(r['entries'],0);self.assertEqual(r['status_cancelled_buys'],1)
        self.assertEqual(r['orders'][0]['signal'],1)
    def test_execution_day_unknown_cancels(self):
        x=inputs();x[6][2]=-1;self.assertEqual(run(x)['entries'],0)
    def test_execution_day_halt_cancels(self):
        x=inputs();x[7][2]=0;self.assertEqual(run(x)['entries'],0)
    def test_st_after_entry_forces_next_day_exit(self):
        x=inputs();x[6][4:]=1;r=run(x)
        self.assertEqual(r['trades'][0][2:4],(4,5));self.assertEqual(r['risk_exit_requests'],1)
    def test_st_exit_not_blocked_just_because_st(self):
        x=inputs();x[6][4:]=1;r=run(x)
        self.assertEqual(r['units'],0.);self.assertEqual(r['trades'][0][3],5)
    def test_st_during_missing_quote_latches(self):
        x=inputs();x[0][4:7]=np.nan;x[6][4:]=1;x[7][4:7]=0;r=run(x)
        self.assertEqual(r['trades'][0][2:4],(4,7))
    def test_forced_order_survives_removal_of_st(self):
        x=inputs();x[6][4]=1;x[7][5]=0;r=run(x)
        self.assertEqual(r['trades'][0][2:4],(4,6))
    def test_halted_sell_with_quote_is_not_filled(self):
        x=inputs();x[2][3]=True;x[7][4]=0;r=run(x)
        self.assertEqual(r['trades'][0][3],5)
    def test_no_future_status_changes_past_ledger(self):
        x=inputs();x[2][6]=True;a=run(x)
        x[6][12:]=1;b=run(x)
        np.testing.assert_array_equal(a['nav'][:12],b['nav'][:12])
        self.assertEqual(a['trades'],b['trades'])
    def test_last_bar_signal_never_filled(self):
        x=inputs();x[1][:]=False;x[1][-1]=True;self.assertEqual(run(x)['entries'],0)
    def test_invalid_status_enum(self):
        x=inputs();x[6][4]=2
        with self.assertRaises(ValueError):run(x)
    def test_nan_status_rejected(self):
        x=list(inputs());x[6]=x[6].astype(float);x[6][4]=np.nan
        with self.assertRaises(ValueError):run(x)
    def test_no_same_day_sell_after_entry(self):
        x=inputs();x[2][2]=True;r=run(x)
        self.assertEqual(r['trades'][0][1:4],(2,2,3))
    def test_normal_status_preserves_legacy_exactly(self):
        for seed in range(12):
            rng=np.random.default_rng(seed);n=150
            c=10*np.exp(np.cumsum(rng.normal(0,.01,n)));o=c*(1+rng.normal(0,.002,n))
            b=np.column_stack([o,np.maximum(o,c)*1.01,np.minimum(o,c)*.99,c,np.ones(n)*1000])
            buy=rng.random(n)<.12;t=rng.random(n)<.12;lo=rng.random(n)<.1;at=np.ones(n)*.2;cost=np.full(n,.0023)
            x=(b,buy,t,lo,at,cost,np.zeros(n,np.int8),np.ones(n,np.int8))
            for rule in ['D0','D2']:
                old=simulate_exit(b,buy,t,lo,at,cost,0,rule)
                new=run(x,rule=rule)
                np.testing.assert_array_equal(old['nav'],new['nav']);self.assertEqual(old['trades'],new['trades'])

if __name__=='__main__':unittest.main()
