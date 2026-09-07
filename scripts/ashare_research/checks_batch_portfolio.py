import unittest
import numpy as np
from batch_portfolio import simulate_portfolio,trade_fee
from batch_signals import compute_signals,quarantine_mask

def panel(n=8,k=2):
 shape=(k,n);one=np.ones(shape)
 return dict(symbols=np.array(['SH600001','SZ000001'][:k]),days=np.array([f'2021-01-{i+1:02d}' for i in range(n)]),open=one*10,close=one*10,high=one*10.2,low=one*9.8,factor=one,amount=one*1e8,st=np.zeros(shape,np.int8),trade=one.astype(np.int8),valid=np.ones(shape,bool),eligible=np.ones(shape,bool),score=one*1e8,raw_volume=one*1e7)
class PortfolioTests(unittest.TestCase):
 def runit(self,d,buy,sell,**kw):return simulate_portfolio(d,buy,sell,0,len(d['days']),**kw)
 def test_next_day_integer_and_minimum_commission(self):
  d=panel();b=np.zeros((2,8),bool);s=b.copy();b[0,0]=1;s[0,2]=1
  r=self.runit(d,b,s);t=r['trades'][0]
  self.assertEqual(t['buy_index'],1);self.assertEqual(t['sell_index'],3)
  self.assertEqual(t['shares_entry']%100,0);self.assertGreaterEqual(t['buy_fee'],5)
  self.assertLess(r['equity'][-1],100000)
 def test_no_lookahead_fill_final_bar(self):
  d=panel();b=np.zeros((2,8),bool);b[0,-1]=1
  r=self.runit(d,b,b*False);self.assertEqual(len(r['trades']),0);self.assertEqual(r['entries'],0)
 def test_reject_ST_at_execution(self):
  d=panel();b=np.zeros((2,8),bool);b[0,0]=1;d['st'][0,1]=1
  r=self.runit(d,b,b*False);self.assertEqual(r['entries'],0)
 def test_reject_nonmainboard(self):
  d=panel();d['symbols'][0]='SZ300001';b=np.zeros((2,8),bool);b[0,0]=1
  with self.assertRaises(ValueError):self.runit(d,b,b*False)
 def test_missing_open_buy_cancels_not_delays(self):
  d=panel();d['valid'][0,1]=False;b=np.zeros((2,8),bool);b[0,0]=1
  r=self.runit(d,b,b*False);self.assertEqual(r['entries'],0)
 def test_forced_ST_exit_keeps_loss(self):
  d=panel();b=np.zeros((2,8),bool);b[0,0]=1;d['st'][0,2:]=1
  d['close'][0,2:]=9.8;d['open'][0,3:]=9.8
  r=self.runit(d,b,b*False);self.assertEqual(len(r['trades']),1);self.assertIn('ST',r['trades'][0]['reason']);self.assertLess(r['trades'][0]['pnl'],0)
 def test_no_same_open_sale_cash_reuse(self):
  d=panel();b=np.zeros((2,8),bool);s=b.copy();b[0,0]=1;s[0,1]=1;b[1,1]=1
  r=self.runit(d,b,s,max_positions=1);self.assertEqual(r['entries'],1)
 def test_preplanned_quantity_not_expanded_on_gapdown(self):
  d=panel();b=np.zeros((2,8),bool);b[0,0]=1
  a=self.runit(d,b,b*False);d['open'][0,1]=9.6
  z=self.runit(d,b,b*False)
  self.assertEqual(a['buy_events'][0]['shares_entry'],z['buy_events'][0]['shares_entry'])
 def test_costs_and_cash_reconcile(self):
  d=panel();b=np.zeros((2,8),bool);s=b.copy();b[0,0]=1;s[0,3]=1
  r=self.runit(d,b,s);self.assertAlmostEqual(100000+sum(e['cash_delta'] for e in r['cash_events']),r['cash'][-1],8)
 def test_prefix_invariance(self):
  d=panel();b=np.zeros((2,8),bool);s=b.copy();b[0,0]=1;s[0,2]=1
  a=self.runit(d,b,s);z=simulate_portfolio(d,b,s,0,5)
  np.testing.assert_array_equal(a['equity'][:5],z['equity'])
 def test_declared_action_is_not_raw_share_certification(self):
  d=panel();b=np.zeros((2,8),bool);s=b.copy();b[0,0]=1;s[0,4]=1;d['factor'][0,3:]=2
  r=self.runit(d,b,s);self.assertGreater(r['trades'][0]['action_days'],0)
 def test_quarantine_is_causal(self):
  st=np.array([0,0,1,0,-1,0]);q=quarantine_mask(st)
  np.testing.assert_array_equal(q,[False,False,True,True,True,True])
  np.testing.assert_array_equal(q[:2],quarantine_mask(st[:2]))
 def test_signals_prefix(self):
  rng=np.random.default_rng(543);c=np.exp(np.cumsum(rng.normal(0,.02,400)))*10
  x=dict(close=c,open=c*.999,high=c*1.02,low=c*.98,volume=np.full(400,1e6))
  full=compute_signals(x);short=compute_signals({k:v[:300] for k,v in x.items()})
  for k in full:np.testing.assert_array_equal(full[k][:,:300] if full[k].ndim==2 else full[k][:300],short[k])
 def test_flat_prices_no_entries(self):
  x=dict(close=np.ones(400)*10,open=np.ones(400)*10,high=np.ones(400)*10,low=np.ones(400)*10,volume=np.ones(400))
  self.assertFalse(compute_signals(x)['buy'].any())
if __name__=='__main__':unittest.main()
