"""Offline independent saved-ledger review. Does not call the simulation engine.
It rechecks fees, orders, all daily cash and final value, not every source quote.
"""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
KEY=['period','rule','scenario']

def fees(value,days,selling,mul):
 days=np.asarray(days,dtype=str)
 transfer=np.where(days<'2022-04-29',.00002,.00001)
 stamp=np.where(days<'2023-08-28',.001,.0005) if selling else 0.
 return mul*(np.maximum(5.,np.asarray(value)*.0003)+np.asarray(value)*(transfer+stamp))

def read(root,name):
 try:return pd.read_csv(root/(name+'.csv.xz'))
 except pd.errors.EmptyDataError:return pd.DataFrame(columns=KEY)

def audit(root):
 root=Path(root);summary=pd.read_csv(root/'summary.csv');equity=read(root,'equity');trades=read(root,'trades');events=read(root,'cash_events');orders=read(root,'orders');buys=read(root,'buy_events');opens=read(root,'open_positions')
 assert len(summary)==208 and not summary.duplicated(KEY).any()
 tmul=np.where(trades.scenario=='double_cost',2.,1.)
 bf=fees(trades.shares_entry*trades.buy_price,trades.buy_date,False,tmul)
 sf=fees(trades.equivalent_shares_exit*trades.sell_price,trades.sell_date,True,tmul)
 checks=[np.max(abs(bf-trades.buy_fee)),np.max(abs(sf-trades.sell_fee))]
 np.testing.assert_allclose(bf,trades.buy_fee,atol=1e-7,rtol=1e-12);np.testing.assert_allclose(sf,trades.sell_fee,atol=1e-7,rtol=1e-12)
 basis=trades.shares_entry*trades.buy_price+bf;proceeds=trades.equivalent_shares_exit*trades.sell_price-sf
 for a,b in [(basis,trades.entry_cost),(proceeds,trades.proceeds),(proceeds-basis,trades.pnl),(proceeds/basis-1,trades.net_return)]:np.testing.assert_allclose(a,b,atol=1e-7,rtol=1e-12)
 assert (trades.shares_entry%100==0).all() and (trades.signal_index<trades.buy_index).all()
 assert (trades.buy_index<=trades.sell_signal_index).all() and (trades.sell_signal_index<trades.sell_index).all()
 assert (buys.isST==0).all() and (buys.trade==1).all() and (buys.entry_cost<=buys.reserve+1e-7).all()
 assert (orders.shares%100==0).all() and (orders.total_reserve_before+orders.reserve<=orders.cash_at_plan+1e-7).all()
 groups={k:g for k,g in equity.groupby(KEY)};trs={k:g for k,g in trades.groupby(KEY)};evs={k:g for k,g in events.groupby(KEY)};ops={k:g for k,g in opens.groupby(KEY)};stats=[]
 for row in summary.to_dict('records'):
  key=tuple(row[k] for k in KEY);curve=groups[key].sort_values('date');daily=evs.get(key,events.iloc[:0]).groupby('date').cash_delta.sum().reindex(curve.date,fill_value=0).to_numpy();rebuilt=100000+np.cumsum(daily)
  err=float(np.max(abs(rebuilt-curve.cash.to_numpy())));checks.append(err)
  np.testing.assert_allclose(rebuilt,curve.cash,rtol=1e-12,atol=1e-6)
  np.testing.assert_allclose(curve.equity,curve.cash+curve.invested,atol=1e-7)
  assert curve.positions.max()<=5 and curve.cash.min()>-1e-6
  tr=trs.get(key,trades.iloc[:0]);op=ops.get(key,opens.iloc[:0]);value=float((op.economic_units*op.last_mark).sum()) if len(op) else 0.
  np.testing.assert_allclose(rebuilt[-1]+value,curve.equity.iloc[-1],atol=1e-6)
  nav=np.r_[100000.,curve.equity.to_numpy()];dd=float((1-nav/np.maximum.accumulate(nav)).max())
  np.testing.assert_allclose([nav[-1]/100000-1,dd,len(tr)],[row['return_total'],row['max_drawdown'],row['closed_trades']],atol=1e-10)
  if len(tr):np.testing.assert_allclose([float((tr.pnl>0).mean()),tr.net_return.mean()],[row['win_rate'],row['mean_trade_return']],atol=1e-12)
  stats.append(dict(**{k:row[k] for k in KEY},cash_error=err,closed_trades=len(tr),minimum_cash=float(curve.cash.min()),max_positions=int(curve.positions.max())))
 result=dict(checked_scenarios=len(summary),checked_trade_rows=len(trades),checked_buy_events=len(buys),checked_order_rows=len(orders),checked_daily_equity_rows=len(equity),maximum_arithmetic_error=max(checks),source_quote_reexecution=False,ordinary_listing_certified=False,real_corporate_action_ledger=False,native_ths_verified=False)
 (root/'independent_audit.json').write_text(json.dumps(result,indent=2));pd.DataFrame(stats).to_csv(root/'independent_account_checks.csv',index=False);return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();print(json.dumps(audit(a.root),indent=2))
