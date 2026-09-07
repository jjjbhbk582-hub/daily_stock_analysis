"""One finite RMB-budget research account; NOT a certified real-share ledger.
Entry quantities are raw-price 100-share lots. Subsequent value uses constant
adjusted units: corporate actions are economic-equivalent, not reconstructed
cash dividends/bonus-share settlement. Every affected trade is identified.
"""
from __future__ import annotations
import math
import numpy as np
from verify_data import is_mainboard

def trade_fee(notional,day,sell=False,multiple=1.):
 if not math.isfinite(notional) or notional<0 or multiple<=0:raise ValueError('Bad fee input')
 transfer=.00001 if str(day)>='2022-04-29' else .00002
 stamp=(.0005 if str(day)>='2023-08-28' else .001) if sell else 0.
 return (max(5.,notional*.0003)+notional*(transfer+stamp))*multiple

def simulate_portfolio(d,buy,sell,start,end,max_positions=5,fraction=.10,multiple=1.,delay=1,seed=None,max_hold=10):
 syms=list(map(str,d['symbols']));ns=len(syms);nd=len(d['days'])
 if not all(is_mainboard(s) for s in syms):raise ValueError('Forbidden board')
 if not 0<=start<end<=nd or delay not in (1,2) or not 0<fraction<=1 or not 1<=max_positions<=5:raise ValueError('Invalid settings')
 if buy.shape!=(ns,nd) or sell.shape!=(ns,nd):raise ValueError('Signal shape differs')
 for k in ('open','close','factor','amount','st','trade','valid','eligible','score','raw_volume'):
  if d[k].shape!=(ns,nd):raise ValueError('Input shape '+k)
 if not np.isin(d['st'],[-1,0,1]).all() or not np.isin(d['trade'],[-1,0,1]).all():raise ValueError('Unknown flag must be -1')
 rng=np.random.default_rng(seed);cash=100000.;held={};pending=[];orders=[];cash_events=[];trades=[];buys=[]
 nav=[];cashcurve=[];invested=[];nheld=[];stale=[];entries=cancelled=0
 mark=np.full(ns,np.nan);lastq=np.full(ns,-1,int)
 for j in range(ns):
  prev=np.flatnonzero(d['valid'][j,:start])
  if len(prev):lastq[j]=prev[-1];mark[j]=d['close'][j,prev[-1]]
 for t in range(start,end):
  day=str(d['days'][t]);valid=d['valid'][:,t]
  # Existing sell orders only; today's new ST is handled at the completed bar.
  for j,p in list(held.items()):
   if not valid[j] or p['sell_due'] is None or t<p['sell_due']:continue
   op=float(d['open'][j,t]);fac=float(d['factor'][j,t]);raw=round(op/fac,2)
   gap=op/mark[j]-1 if math.isfinite(mark[j]) else -1.
   threshold=-.048 if d['st'][j,t]==1 else -.098
   if d['trade'][j,t]!=1 or gap<=threshold:
    p['blocked_days']+=1;continue
   fill=math.floor(raw*(1-.001*multiple)*100+1e-8)/100
   if fill<=0:continue
   equivalent=p['economic_units']*fac;gross=equivalent*fill;fee=trade_fee(gross,day,True,multiple);proceeds=gross-fee
   cash+=proceeds;delta=proceeds-p['basis']
   tr=dict(symbol=syms[j],signal_index=p['signal'],buy_index=p['entry'],sell_signal_index=p['sell_signal'],sell_index=t,
    signal_date=str(d['days'][p['signal']]),buy_date=str(d['days'][p['entry']]),sell_signal_date=str(d['days'][p['sell_signal']]),sell_date=day,
    shares_entry=p['shares'],equivalent_shares_exit=equivalent,buy_price=p['buy_price'],sell_price=fill,buy_factor=p['factor'],sell_factor=fac,
    buy_fee=p['buy_fee'],sell_fee=fee,entry_cost=p['basis'],proceeds=proceeds,pnl=delta,net_return=delta/p['basis'],reason=p['reason'],holding_days=t-p['entry'],mae=p['mae'],action_days=p['action_days']+int(abs(fac/p['last_factor']-1)>1e-6),blocked_days=p['blocked_days'])
   trades.append(tr);cash_events.append(dict(index=t,date=day,symbol=syms[j],kind='sell',cash_delta=proceeds))
   del held[j]
  todo=[q for q in pending if q['due']==t];pending=[q for q in pending if q['due']>t]
  for q in todo:
   j=q['j'];reason=None
   if not valid[j]:reason='missing_quote'
   elif d['st'][j,t]!=0 or d['trade'][j,t]!=1 or not d['eligible'][j,t]:reason='scope_or_quarantine'
   else:
    fac=float(d['factor'][j,t]);raw=round(float(d['open'][j,t])/fac,2)
    fill=math.ceil(raw*(1+.001*multiple)*100-1e-8)/100
    gross=q['shares']*fill;fee=trade_fee(gross,day,False,multiple);spend=gross+fee
    gap=float(d['open'][j,t])/mark[j]-1 if math.isfinite(mark[j]) else 0.
    if fill>q['limit'] or raw<3 or gap>=.098:reason='price_limit'
    elif spend>q['reserve']+1e-7 or spend>cash+1e-7 or len(held)>=max_positions or j in held:reason='cash_or_slots'
   if reason is not None:q['outcome']=reason;cancelled+=1;continue
   cash-=spend;entries+=1;q['outcome']='filled'
   held[j]=dict(signal=q['signal'],entry=t,shares=q['shares'],economic_units=q['shares']/fac,basis=spend,buy_fee=fee,buy_price=fill,factor=fac,last_factor=fac,action_days=0,mae=0.,sell_due=None,sell_signal=None,reason='',blocked_days=0)
   event=dict(index=t,date=day,symbol=syms[j],shares_entry=q['shares'],signal=q['signal'],isST=int(d['st'][j,t]),trade=int(d['trade'][j,t]),reserve=q['reserve'],entry_cost=spend)
   buys.append(event);cash_events.append(dict(index=t,date=day,symbol=syms[j],kind='buy',cash_delta=-spend))
  mark[valid]=d['close'][valid,t];lastq[valid]=t
  value=0.;staleval=0.
  for j,p in held.items():
   v=p['economic_units']*mark[j];value+=v
   if t-lastq[j]>=20:staleval+=v
   if valid[j]:
    fac=float(d['factor'][j,t]);p['action_days']+=int(abs(fac/p['last_factor']-1)>1e-6);p['last_factor']=fac
    p['mae']=min(p['mae'],mark[j]/(p['buy_price']*p['factor'])-1)
   reasons=[]
   if d['st'][j,t]==1:reasons.append('ST')
   if valid[j] and sell[j,t]:reasons.append('technical')
   if valid[j] and mark[j]<=p['buy_price']*p['factor']*.92:reasons.append('stop8_close')
   if t-p['entry']+1>=max_hold:reasons.append('time')
   if reasons and p['sell_due'] is None:p.update(sell_due=t+delay,sell_signal=t,reason='+'.join(reasons))
   elif 'ST' in reasons and 'ST' not in p['reason']:p['reason']+='+ST'
  equity=cash+value;nav.append(equity);cashcurve.append(cash);invested.append(value);nheld.append(len(held));stale.append(staleval)
  if cash < -1e-6 or len(held)>max_positions:raise AssertionError('Cash/slot invariant')
  reserved=sum(q['reserve'] for q in pending)
  free=cash-reserved;slots=max_positions-len(held)-len(pending)
  if slots<=0 or free<305:continue
  candidates=np.flatnonzero(buy[:,t]&valid&d['eligible'][:,t]&(d['st'][:,t]==0)&(d['trade'][:,t]==1)&(d['score'][:,t]>=5e7))
  candidates=[int(j) for j in candidates if j not in held and all(q['j']!=j for q in pending)]
  if seed is None:candidates.sort(key=lambda j:(-float(d['score'][j,t]),syms[j]))
  else:rng.shuffle(candidates)
  for j in candidates:
   if slots<=0:break
   raw=round(float(d['close'][j,t])/float(d['factor'][j,t]),2)
   if raw<3:continue
   limit=math.floor(raw*1.03*100+1e-8)/100
   budget=min(equity*fraction,free)
   shares=100*int(max(0.,budget-5*multiple)/(limit*100))
   cap=100*int(max(0.,float(d['raw_volume'][j,t]))*.001/100)
   shares=min(shares,cap)
   while shares>0 and shares*limit+trade_fee(shares*limit,day,False,multiple)>budget+1e-8:shares-=100
   if shares<100:continue
   reserve=shares*limit+trade_fee(shares*limit,day,False,multiple)
   q=dict(j=j,symbol=syms[j],signal=t,due=t+delay,limit=limit,shares=shares,reserve=reserve,outcome='pending',cash_at_plan=cash,total_reserve_before=reserved)
   orders.append(q);pending.append(q);free-=reserve;reserved+=reserve;slots-=1
   if reserved>cash+1e-7:raise AssertionError('Future sale cash reserved')
 return dict(equity=np.asarray(nav),cash=np.asarray(cashcurve),invested=np.asarray(invested),nheld=np.asarray(nheld),stale=np.asarray(stale),trades=trades,buy_events=buys,orders=orders,cash_events=cash_events,entries=entries,cancelled=cancelled,open_positions=[dict(symbol=syms[j],**p,last_mark=float(mark[j])) for j,p in held.items()],real_share_ledger_verified=False)
