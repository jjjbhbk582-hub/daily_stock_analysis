"""Frozen volume-shock signals and conditional block diagnostics, no orders."""
from __future__ import annotations
import numpy as np
import pandas as pd

FIELDS=['open','high','low','close','volume']

def volume_signals(frame):
    if list(frame.columns)!=FIELDS:
        raise ValueError('Expected exact OHLCV columns')
    x=frame.to_numpy(dtype=float)
    if not np.isfinite(x).all() or (x<=0).any():
        raise ValueError('Only complete positive observed bars may enter the signal function')
    c=frame.close;p=c.shift(1);v=frame.volume
    tr=pd.concat([frame.high-frame.low,(frame.high-p).abs(),(frame.low-p).abs()],axis=1).max(axis=1)
    a=tr.rolling(14).mean().shift(1);vm=v.rolling(20).mean().shift(1)
    ready=pd.Series(np.arange(len(c))>=120,index=frame.index)
    shock=(c<=p-1.5*a)&(c<c.rolling(5).min().shift(1))&(a>0)&(vm>0)&ready
    return {'V0':shock.fillna(False).to_numpy(bool),
            'VH':(shock&(v>=1.5*vm)).fillna(False).to_numpy(bool),
            'VL':(shock&(v<=vm)).fillna(False).to_numpy(bool),
            'RECOVER5':((c>=c.rolling(5).mean())&ready).fillna(False).to_numpy(bool),
            'ATR_PREV':a.to_numpy(float),'VOL_PREV':vm.to_numpy(float)}

def independent_flags(frame):
    """Direct-window reference; never uses pandas rolling functions."""
    x=frame.to_numpy(float);n=len(x)
    ans={k:np.zeros(n,bool) for k in ('V0','VH','VL','RECOVER5')}
    if not n:return ans
    c=x[:,3];v=x[:,4];p=np.r_[c[0],c[:-1]]
    tr=np.maximum(x[:,1]-x[:,2],np.maximum(np.abs(x[:,1]-p),np.abs(x[:,2]-p)))
    for i in range(120,n):
        a=float(np.mean(tr[i-14:i]));vm=float(np.mean(v[i-20:i]))
        hit=a>0 and vm>0 and c[i]<=c[i-1]-1.5*a and c[i]<np.min(c[i-5:i])
        ans['V0'][i]=hit;ans['VH'][i]=hit and v[i]>=1.5*vm
        ans['VL'][i]=hit and v[i]<=vm;ans['RECOVER5'][i]=c[i]>=np.mean(c[i-4:i+1])
    return ans

def block_interval(log_returns,block=20,draws=1000,seed=91007):
    """Conditional 95% circular moving-block interval for annual mean log return.
    Does NOT correct repeated historical strategy selection or provider biases.
    """
    x=np.asarray(log_returns,float)
    if x.ndim!=1 or not len(x) or not np.isfinite(x).all() or block<1 or draws<2:
        raise ValueError('Invalid bootstrap input')
    n=len(x);rng=np.random.default_rng(seed);out=np.empty(draws)
    offsets=np.arange(block);nb=(n+block-1)//block
    for i in range(draws):
        starts=rng.integers(0,n,size=nb)
        ix=((starts[:,None]+offsets)%n).ravel()[:n]
        out[i]=x[ix].mean()*252
    q=np.quantile(out,[.025,.975])
    return dict(estimate_annual_log=float(x.mean()*252),lower_annual_log=float(q[0]),
                upper_annual_log=float(q[1]),block_sessions=block,draws=draws,seed=seed,
                selection_adjusted=False)
