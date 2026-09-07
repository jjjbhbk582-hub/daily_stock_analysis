"""User's hard scope: mainboard only, known non-ST entry, exit on later ST.

Effective-date vendor flags are not verified announcement timestamps. This is
an adjusted-unit diagnostic, not native Tonghuashun or a real RMB account.
The legacy simulator is left untouched; normal-state parity is tested exactly.
"""
from __future__ import annotations
import math
import numpy as np
from verify_data import is_mainboard


def simulate_scope(bars,buy,profit,low,atr,costs,start,rule,st,trade,symbol,
                   mode='strict',multiple=1.,delay=1,gap=-.048):
    n=len(bars)
    if not is_mainboard(symbol) or mode not in ('strict','signal_only'):
        raise ValueError('Outside the authorized mainboard scope or invalid mode')
    if rule not in ('D0','D2') or delay not in (1,2) or not 0<=start<n or multiple<=0:
        raise ValueError('Invalid fixed diagnostic settings')
    if bars.shape!=(n,5) or any(len(x)!=n for x in (buy,profit,low,atr,costs,st,trade)):
        raise ValueError('Input shapes differ')
    if not np.isin(st,[-1,0,1]).all() or not np.isin(trade,[-1,0,1]).all():
        raise ValueError('Invalid/NaN historical status; unknown must be -1')
    strict=mode=='strict'
    valid=np.isfinite(bars).all(axis=1)&(bars>0).all(axis=1)
    o,c=bars[:,0],bars[:,3];previous=np.flatnonzero(valid[:start])
    mark=float(c[previous[-1]]) if len(previous) else math.nan
    last_quote=int(previous[-1]) if len(previous) else -1
    cash=1.;units=0.;buyfee=.0013*multiple
    pending_buy=pending_sell=entry=None
    stop=0.;mae=0.;risk_seen=False;trades=[];details=[];events=[];orders=[]
    entries=cancelled=blocked=status_cancelled=risk_requests=0
    held_unknown=held_st=0
    nav=np.empty(n-start);exposure=np.empty(n-start)
    for i in range(start,n):
        if valid[i]:
            if units>0 and pending_sell is not None and i>=pending_sell[0]:
                if (strict and trade[i]!=1) or o[i]/mark-1<=gap:
                    blocked+=1
                else:
                    proceeds=units*o[i]*(1-float(costs[i])*multiple);basis=entry[3]
                    trades.append((entry[0],entry[1],pending_sell[1],i,entry[2],float(o[i]),
                                   units,basis,proceeds-basis,proceeds/basis-1))
                    details.append((pending_sell[2],i-entry[1],mae,pending_sell[3],stop))
                    events.append((i,'sell',pending_sell[1],int(st[i]),int(trade[i]),int(pending_sell[2])))
                    cash+=proceeds;units=0.;entry=None;pending_sell=None
            if pending_buy is not None and pending_buy[0]==i:
                _,limit,q,sig,record=pending_buy;spend=q*o[i]*(1+buyfee)
                accepted_status=(st[i]==0 and trade[i]==1) if strict else True
                if not accepted_status:
                    cancelled+=1;status_cancelled+=1;record['outcome']='status_cancelled'
                    events.append((i,'cancel_status',sig,int(st[i]),int(trade[i]),0))
                elif o[i]<=limit and spend<=cash+1e-12 and units==0:
                    cash-=spend;units=q;entries+=1;entry=(sig,i,float(o[i]),spend)
                    stop=float(o[i])*.92 if rule=='D2' else 0.;mae=0.;risk_seen=False
                    record['outcome']='filled'
                    events.append((i,'buy',sig,int(st[i]),int(trade[i]),0))
                else:
                    cancelled+=1;record['outcome']='price_or_cash_cancelled'
                pending_buy=None
            mark=float(c[i]);last_quote=i
            if units:mae=min(mae,mark/entry[2]-1)
        elif pending_buy is not None and pending_buy[0]==i:
            cancelled+=1;pending_buy[4]['outcome']='missing_price_cancelled';pending_buy=None
        value=units*mark if units else 0.
        nav[i-start]=cash+value;exposure[i-start]=value/nav[i-start]
        if units:
            held_unknown+=int(st[i]<0);held_st+=int(st[i]==1)
        if units>0 and strict and st[i]==1 and not risk_seen:
            risk_seen=True;risk_requests+=1
            events.append((i,'risk_ST',entry[1],int(st[i]),int(trade[i]),32))
            if pending_sell is None:
                pending_sell=(i+delay,i,32,mark/entry[2]-1 if valid[i] else math.nan)
            else:
                due,sig,reason,sigr=pending_sell
                pending_sell=(min(due,i+delay),sig,reason|32,sigr)
        if units>0 and pending_sell is None:
            reason=int(valid[i] and profit[i])
            if rule=='D0':reason|=2*int(valid[i] and low[i])
            else:
                reason|=4*int(i-entry[1]+1>=10)
                reason|=8*int(valid[i] and mark<=stop)
            if reason:
                pending_sell=(i+delay,i,reason,mark/entry[2]-1 if valid[i] else math.nan)
        elif units==0 and pending_buy is None and valid[i] and buy[i] and st[i]==0 and trade[i]==1:
            limit=mark*1.03;quantity=cash/(limit*(1+buyfee))
            record=dict(signal=i,due=i+delay,limit=float(limit),units=float(quantity),outcome='pending')
            orders.append(record);pending_buy=(i+delay,limit,quantity,i,record)
        if cash < -1e-10:raise AssertionError('Negative cash')
    return dict(nav=nav,exposure=exposure,trades=trades,details=details,cash=cash,
        units=units,mark=mark,last_quote=last_quote,entries=entries,cancelled=cancelled,
        blocked_sells=blocked,open_entry_cost=entry[3] if entry else 0.,
        open_entry_price=entry[2] if entry else 0.,open_entry_index=entry[1] if entry else -1,
        events=events,orders=orders,status_cancelled_buys=status_cancelled,
        risk_exit_requests=risk_requests,held_unknown_days=held_unknown,held_st_days=held_st,
        pending_ST_exit=bool(pending_sell and pending_sell[2]&32),
        open_ST=bool(units and st[-1]==1))
