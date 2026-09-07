import tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from batch_portfolio import simulate_portfolio
from checks_batch_portfolio import panel
from audit_finite_account import audit

def make_evidence(root):
 d=panel();b=np.zeros((2,8),bool);s=b.copy();b[0,0]=1;s[0,2]=1
 summary=[];eq=[];tr=[];ev=[];order=[];buy=[]
 for per in ['older','early','middle','recent']:
  for rule in ['RSI6','RSI2_PULLBACK','BAND_RECOVERY','CONFIRMED_TRENDLINE']:
   for scenario in ['base','double_cost','delay2']+[f'random_{n}' for n in range(10)]:
    tags=dict(period=per,rule=rule,scenario=scenario)
    bb=b*False if (per,rule,scenario)==('older','RSI6','base') else b
    z=simulate_portfolio(d,bb,s,0,8,multiple=2 if scenario=='double_cost' else 1,delay=2 if scenario=='delay2' else 1)
    v=np.r_[100000.,z['equity']];tt=z['trades']
    summary.append(dict(**tags,return_total=v[-1]/100000-1,max_drawdown=max(1-v/np.maximum.accumulate(v)),closed_trades=len(tt),win_rate=np.mean([r['pnl']>0 for r in tt]) if tt else None,mean_trade_return=np.mean([r['net_return'] for r in tt]) if tt else None))
    for rows,dest in [(tt,tr),(z['cash_events'],ev),(z['orders'],order),(z['buy_events'],buy)]:dest.extend(dict(**tags,**r) for r in rows)
    eq.extend(dict(**tags,date=day,equity=e,cash=c,invested=i,positions=h) for day,e,c,i,h in zip(d['days'],z['equity'],z['cash'],z['invested'],z['nheld']))
 pd.DataFrame(summary).to_csv(root/'summary.csv',index=False)
 for name,rows in [('trades',tr),('cash_events',ev),('orders',order),('buy_events',buy),('equity',eq)]:pd.DataFrame(rows).to_csv(root/(name+'.csv.xz'),index=False)
 pd.DataFrame(columns=['period','rule','scenario','economic_units','last_mark']).to_csv(root/'open_positions.csv.xz',index=False)
class IndependentAuditTests(unittest.TestCase):
 def test_all_scenarios_and_empty_cash_account(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);make_evidence(p);self.assertEqual(audit(p)['checked_scenarios'],208)
 def test_forged_fees_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);make_evidence(p);t=pd.read_csv(p/'trades.csv.xz');t.loc[0,'buy_fee']+=.1;t.to_csv(p/'trades.csv.xz',index=False)
   with self.assertRaises(AssertionError):audit(p)
 def test_forged_daily_cash_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);make_evidence(p);t=pd.read_csv(p/'equity.csv.xz');t.loc[0,'cash']+=1;t.to_csv(p/'equity.csv.xz',index=False)
   with self.assertRaises(AssertionError):audit(p)
if __name__=='__main__':unittest.main()
