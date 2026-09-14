#!/usr/bin/env python3
from pathlib import Path
import json, math, requests
import numpy as np
import pandas as pd

EVENTS=Path('korea_turnaround_v2_events.csv')
OUT=Path('korea_turnaround_v2_matched_events.csv')
SUM=Path('korea_turnaround_v2_matched_summary.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
YEARS=(2021,2022)
PEERS=20

def norm(v):
    s=str(v or '').replace('.0','').strip()
    return s.zfill(6) if s else ''

def load_year(y):
    if y not in YEARS: raise SystemExit('pre-OOS guard: only 2021-2022 allowed')
    p=Path(f'marcap-{y}.parquet')
    if not p.exists():
        r=requests.get(MARCAP.format(year=y),timeout=180); r.raise_for_status(); p.write_bytes(r.content)
    z=pd.read_parquet(p)
    if 'Date' not in z: z=z.reset_index()
    z['Date']=pd.to_datetime(z['Date'])
    z['Code']=z['Code'].map(norm)
    return z[z.Market.isin(['KOSPI','KOSDAQ'])].sort_values(['Code','Date']).reset_index(drop=True)

def summary_stats(g,col):
    s=pd.to_numeric(g[col],errors='coerce').dropna()
    if s.empty: return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win_rate':float((s>0).mean()),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75))}

def main():
    ev=pd.read_csv(EVENTS,dtype={'stock_code':str})
    ev['stock_code']=ev.stock_code.map(norm)
    ev=ev[(ev.mcap<=50e9)&(ev.op_yoy_pct>0)].copy().reset_index(drop=True)
    if not set(ev.signal_year.unique()).issubset(set(YEARS)): raise SystemExit('pre-OOS guard violated')
    # Freeze development quintiles exactly as previously analyzed.
    ev['improvement_quintile']=pd.qcut(ev.op_yoy_pct.rank(method='first'),5,labels=[1,2,3,4,5]).astype(int)
    mk={y:load_year(y) for y in YEARS}
    by={}
    for y,z in mk.items():
        for c,g in z.groupby('Code',sort=False): by.setdefault(c,[]).append(g)
    by={c:pd.concat(gs).sort_values('Date').reset_index(drop=True) for c,gs in by.items()}
    rows=[]
    for r in ev.itertuples(index=False):
        sd=pd.Timestamp(r.signal_date); code=norm(r.stock_code); z=by.get(code)
        if z is None: continue
        elig=z[(z.Date>sd)&(pd.to_numeric(z.Open,errors='coerce')>0)&(pd.to_numeric(z.Volume,errors='coerce')>0)]
        if elig.empty: continue
        entry=elig.iloc[0]; ei=int(elig.index[0]); j=ei+19
        if j>=len(z) or z.iloc[j].Date.year>2022: continue
        entry_date=pd.Timestamp(entry.Date); end_date=pd.Timestamp(z.iloc[j].Date)
        target_mcap=float(r.mcap); market=str(r.market)
        # Point-in-time peer universe: same market, latest observation strictly before signal date.
        allz=mk[int(r.signal_year)]
        pre=allz[allz.Date<sd].sort_values('Date').groupby('Code',as_index=False).tail(1)
        pre=pre[(pre.Market==market)&(pre.Code!=code)&(pd.to_numeric(pre.Marcap,errors='coerce')>0)].copy()
        pre['dist']=(np.log(pd.to_numeric(pre.Marcap,errors='coerce'))-math.log(target_mcap)).abs()
        pre=pre.nsmallest(80,'dist')
        peer_returns=[]; peer_codes=[]
        for pr in pre.itertuples(index=False):
            pz=by.get(norm(pr.Code))
            if pz is None: continue
            a=pz[pz.Date==entry_date]
            b=pz[pz.Date==end_date]
            if a.empty or b.empty: continue
            a=a.iloc[0]; b=b.iloc[0]
            op=float(a.Open) if pd.notna(a.Open) else np.nan
            vol=float(a.Volume) if pd.notna(a.Volume) else 0
            if not np.isfinite(op) or op<=0 or vol<=0: continue
            path=pz[(pz.Date>=entry_date)&(pz.Date<=end_date)]
            sh=pd.to_numeric(path.Stocks,errors='coerce')
            if bool(((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any()): continue
            rr=(float(b.Close)/op-1)*100
            if np.isfinite(rr):
                peer_returns.append(rr); peer_codes.append(norm(pr.Code))
            if len(peer_returns)>=PEERS: break
        if len(peer_returns)<10: continue
        peer_med=float(np.median(peer_returns)); peer_mean=float(np.mean(peer_returns))
        d=r._asdict(); d.update({'entry_date':entry_date.date().isoformat(),'end_date':end_date.date().isoformat(),'matched_peer_n':len(peer_returns),'matched_peer_median_R20':peer_med,'matched_peer_mean_R20':peer_mean,'matched_excess_R20':float(r.R20)-peer_med,'matched_peer_codes':'|'.join(peer_codes)})
        rows.append(d)
    out=pd.DataFrame(rows); out.to_csv(OUT,index=False)
    groups={'all':out}
    for q in range(1,6): groups[f'Q{q}']=out[out.improvement_quintile==q]
    res={}
    for k,g in groups.items():
        res[k]={'all':summary_stats(g,'matched_excess_R20'),'2021':summary_stats(g[g.signal_year==2021],'matched_excess_R20'),'2022':summary_stats(g[g.signal_year==2022],'matched_excess_R20'),'peer_benchmark':summary_stats(g,'matched_peer_median_R20'),'stock':summary_stats(g,'R20')}
    summary={'guard':'2021-2022 only; 2023+ not accessed','peer_definition':'same market; nearest PIT log-market-cap; 20 clean peers; same entry-date open to exact event end-date close; benchmark=peer median','event_count':int(len(out)),'results':res}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
