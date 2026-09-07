"""Regression tests for history-date admission; synthetic cases, not market evidence."""
import unittest
import numpy as np
from historical_status import align_status, admission_masks, deterministic_order, source_gate
from exit_policy_study import simulate_exit

DAYS=['2024-04-15','2024-04-16','2024-04-17','2024-04-18']
SYM='SH600766'
def row(day, st, trade='1', sym='sh.600766'):
    return [day,sym,trade,st]

class HistoricalStatusTests(unittest.TestCase):
    def test_unknown_is_not_normal(self):
        st,tr,meta=align_status([],DAYS,SYM)
        m=admission_masks(st,tr)
        self.assertFalse(m['known'].any());self.assertFalse(m['normal'].any())
        self.assertTrue(m['baseline'].all())
    def test_future_st_does_not_blacklist_past(self):
        st,tr,_=align_status([row(DAYS[0],'0'),row(DAYS[3],'1')],DAYS,SYM)
        self.assertEqual(admission_masks(st,tr)['normal'].tolist(),[True,False,False,False])
    def test_missing_days_not_forward_filled(self):
        st,tr,_=align_status([row(DAYS[0],'0')],DAYS,SYM)
        self.assertEqual(st.tolist(),[0,-1,-1,-1])
    def test_empty_flag_retained_unknown(self):
        st,tr,meta=align_status([row(DAYS[0],'')],DAYS,SYM)
        self.assertEqual(st[0],-1);self.assertEqual(meta['unknown_st_rows'],1)
    def test_invalid_flag_rejected(self):
        with self.assertRaises(ValueError):align_status([row(DAYS[0],'2')],DAYS,SYM)
    def test_duplicate_rejected_even_identical(self):
        r=row(DAYS[0],'0')
        with self.assertRaises(ValueError):align_status([r,r],DAYS,SYM)
    def test_wrong_code_rejected(self):
        with self.assertRaises(ValueError):align_status([row(DAYS[0],'0',sym='sz.000001')],DAYS,SYM)
    def test_reversed_dates_rejected(self):
        with self.assertRaises(ValueError):align_status([row(DAYS[2],'0'),row(DAYS[1],'0')],DAYS,SYM)
    def test_unknown_calendar_day_counted(self):
        st,tr,meta=align_status([row('2024-04-14','0'),row(DAYS[0],'0')],DAYS,SYM)
        self.assertEqual(meta['outside_calendar_rows'],1);self.assertEqual(st[0],0)
    def test_halted_not_admitted(self):
        st,tr,_=align_status([row(DAYS[0],'0','0')],DAYS,SYM)
        self.assertFalse(admission_masks(st,tr)['known'][0])
    def test_all_known_separates_risk_from_missingness(self):
        st=np.array([0,1,-1]);tr=np.ones(3,int)
        masks=admission_masks(st,tr)
        self.assertEqual(masks['known'].tolist(),[True,True,False])
        self.assertEqual(masks['normal'].tolist(),[True,False,False])
    def test_order_is_independent_of_input_order(self):
        xs=['SH600000','SZ000001','SH600766']
        self.assertEqual(deterministic_order(xs),deterministic_order(list(reversed(xs))))
    def test_no_coverage_is_no_effectiveness_claim(self):
        self.assertFalse(source_gate(0,20,True));self.assertFalse(source_gate(20,20,False))
        self.assertTrue(source_gate(20,20,True))
    def test_signal_day_mask_not_next_day_lookahead(self):
        n=8;bars=np.tile([10.,10.,10.,10.,1000.],(n,1));cost=np.full(n,.0018)
        buy=np.zeros(n,bool);buy[1]=True;profit=np.zeros(n,bool);profit[4]=True
        low=np.zeros(n,bool);atr=np.ones(n)
        st=np.array([0,0,1,1,1,1,1,1]);tr=np.ones(n,int)
        # Later ST changes do not retroactively remove an order decided on day1.
        f=admission_masks(st,tr)['normal']
        res=simulate_exit(bars,buy&f,profit,low,atr,cost,0,'D0')
        self.assertEqual(res['trades'][0][1],2);self.assertEqual(res['trades'][0][3],5)
    def test_signal_day_st_does_block_order(self):
        n=8;bars=np.tile([10.,10.,10.,10.,1000.],(n,1));cost=np.full(n,.0018)
        buy=np.zeros(n,bool);buy[1]=True;profit=np.zeros(n,bool);profit[4]=True
        f=admission_masks(np.ones(n,int),np.ones(n,int))['normal']
        res=simulate_exit(bars,buy&f,profit,np.zeros(n,bool),np.ones(n),cost,0,'D0')
        self.assertEqual(res['entries'],0);self.assertEqual(res['cash'],1.)
    def test_filter_never_changes_existing_exit_logic(self):
        n=8;bars=np.tile([10.,10.,10.,10.,1000.],(n,1));cost=np.full(n,.0018)
        buy=np.zeros(n,bool);buy[1]=True;profit=np.zeros(n,bool);profit[4]=True
        masks=admission_masks(np.zeros(n,int),np.ones(n,int))
        x=simulate_exit(bars,buy,profit,np.zeros(n,bool),np.ones(n),cost,0,'D2')
        y=simulate_exit(bars,buy&masks['normal'],profit,np.zeros(n,bool),np.ones(n),cost,0,'D2')
        self.assertEqual(x['trades'],y['trades']);np.testing.assert_array_equal(x['nav'],y['nav'])

if __name__=='__main__':unittest.main()
