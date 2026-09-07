"""Four frozen hypotheses, signals known at the completed daily bar only.
Confirmed-pivot trendlines NEVER backdate an entry to the pivot day.
"""
import numpy as np
import pandas as pd
RULES=('RSI6','RSI2_PULLBACK','BAND_RECOVERY','CONFIRMED_TRENDLINE')

def quarantine_mask(st):
 st=np.asarray(st)
 if not np.isin(st,[-1,0,1]).all():raise ValueError('Invalid ST state')
 return np.maximum.accumulate(st==1) if st.size else np.zeros(0,bool)

def rsi(c,n):
 d=c.diff().fillna(0.);u=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean();a=d.abs().ewm(alpha=1/n,adjust=False).mean()
 return (100*u/a.replace(0,np.nan)).fillna(50.)

def compute_signals(x):
 c=pd.Series(np.asarray(x['close'],float));h=np.asarray(x['high'],float);n=len(c)
 ma5=c.rolling(5).mean();ma20=c.rolling(20).mean();ma60=c.rolling(60).mean();ma200=c.rolling(200).mean()
 r6=rsi(c,6);r2=rsi(c,2);lower=ma20-2*c.rolling(20).std(ddof=0)
 ready=np.arange(n)>=250
 b0=(r6.shift(1)<20)&(r6>r6.shift(1))&(c>c.shift(1))
 b1=(r2<10)&(c>ma200)&(ma200>ma200.shift(20))
 b2=(c.shift(1)<lower.shift(1))&(c>lower)&(c>c.shift(1))
 line=np.full(n,np.nan);bt=np.zeros(n,bool);peaks=[];last_confirmation=-1
 cv=c.to_numpy();m60=ma60.to_numpy();m60prev=ma60.shift(5).to_numpy()
 for t in range(n):
  if t>=6:
   center=t-3;w=h[t-6:t+1]
   if h[center]==np.max(w) and np.count_nonzero(w==h[center])==1:
    peaks.append(center);last_confirmation=t
  if len(peaks)<2:continue
  a,b=peaks[-2:];distance=b-a
  if distance<10 or distance>90 or h[b]>=h[a]:continue
  slope=(h[b]-h[a])/distance;now=h[b]+slope*(t-b);prev=now-slope;line[t]=now
  # The same two highs must already have been confirmed on the previous day.
  if t>last_confirmation and t and now>0:
   bt[t]=cv[t]>now and cv[t-1]<=prev and cv[t]>m60[t] and m60[t]>m60prev[t]
 buys=np.asarray([b0.fillna(False),b1.fillna(False),b2.fillna(False),bt],bool)&ready
 sells=np.asarray([((r6>=60)|(c<c.rolling(10).min().shift(1))).fillna(False),(c>=ma5).fillna(False),(c>=ma20).fillna(False),(c<ma20).fillna(False)],bool)&ready
 return {'buy':buys,'sell':sells,'trendline':line,'rsi6':r6.to_numpy(),'rsi2':r2.to_numpy()}
