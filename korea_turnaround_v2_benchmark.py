#!/usr/bin/env python3
from pathlib import Path
import json, time
import numpy as np
import pandas as pd
import requests

IN=Path('korea_turnaround_v2_events.csv')
OUT=Path('korea_turnaround_v2_benchmark_events.csv')
SUM=Path('korea_turnaround_v2_benchmark_summary.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
YH='https://query1.finance.yahoo.com/v8/finance/chart/{sym}'
UA={'User-Agent':'Mozilla/5.0'}

def norm(v,n=6):
    s=str(v or '').replace('.0','').strip(); return s.zfill(n) if s else ''

def get_marcap(y):
    if y>2022: raise SystemExit('OOS guard: market year > 2022 forbidden')
    p=Path(f'marcap-{y}.parquet')
    if not p.exists():
        r=requests.get(MARCAP.format(year=y),headers=UA,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
    z=pd.read_parquet(p)
    if 'Date' not in z: z=z.reset_index()
    z['Date']=pd.to_datetime(z['Date']); z['Code']=z['Code'].map(norm)
    return z[z.Market.isin(['KOSPI','KOSDAQ'])].sort_values(['Code','Date']).reset_index(drop=True)

def yahoo(sym):
    params={'period1':int(pd.Timestamp('2021-01-01',tz='UTC').timestamp()),
            'period2':int(pd.Timestamp('2023-01-01',tz='UTC').timestamp()),
            'interval':'1d','events':'history','includeAdjustedClose':'true'}
    last=None
    for k in range(5):
        r=requests.get(YH.format(sym=sym),params=params,headers=UA,timeout=60)
        last=r
        if r.ok:
            js=r.json(); res=(js.get('chart') or {}).get('result')
            if res:
                q=res[0]; ts=q.get('timestamp') or []; quote=((q.get('indicators') or {}).get('quote') or [{}])[0]
                d=pd.DataFrame({'Date':pd.to_datetime(ts,unit='s',utc=True).tz_convert('Asia/Seoul').tz_localize(None).normalize(),
                                'Open':quote.get('open',[]),'Close':quote.get('close',[])})
                d=d.dropna(subset=['Date','Open','Close']).drop_duplicates('Date').sort_values('Date').reset_index(drop=True)
                if len(d)>400:return d
        time.sleep(2*(k+1))
    raise RuntimeError(f'Yahoo failed {sym}: {getattr(last,"status_code",None)} {getattr(last,"text","")[:200]}')

def stats(g,col):
    s=pd.to_numeric(g[col],errors='coerce').dropna()
    if len(s)==0:return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win_rate':float((s>0).mean()),
            'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75))}

def main():
    ev=pd.read_csv(IN,dtype={'stock_code':str})
    ev['stock_code']=ev.stock_code.map(norm); ev['signal_date']=pd.to_datetime(ev.signal_date)
    cand=ev[(ev.mcap<=50e9)&(ev.op_yoy_pct>0)].copy().reset_index(drop=True)
    if len(cand)!=365: raise SystemExit(f'expected 365 V2 op-improving events, got {len(cand)}')
    # Quintiles strictly within the 365 candidate events; Q5 = largest improvement/mcap.
    cand['improvement_quintile']=pd.qcut(cand.op_yoy_pct.rank(method='first'),5,labels=['Q1','Q2','Q3','Q4','Q5'])

    mk={2021:get_marcap(2021),2022:get_marcap(2022)}
    by={}
    for y,z in mk.items():
        for c,g in z.groupby('Code',sort=False): by.setdefault(c,[]).append(g)
    by={c:pd.concat(gs).sort_values('Date').reset_index(drop=True) for c,gs in by.items()}

    idx={'KOSPI':yahoo('%5EKS11'),'KOSDAQ':yahoo('%5EKQ11')}
    # guard: do not retain or use any 2023+ data even if source unexpectedly returns it.
    for k in idx: idx[k]=idx[k][idx[k].Date.dt.year<=2022].copy()

    rows=[]; miss=[]
    for r in cand.itertuples(index=False):
        z=by.get(r.stock_code)
        if z is None or z.empty: miss.append(('stock',r.stock_code)); continue
        elig=z[(z.Date>r.signal_date)&(pd.to_numeric(z.Open,errors='coerce')>0)&(pd.to_numeric(z.Volume,errors='coerce')>0)]
        if elig.empty: miss.append(('entry',r.stock_code)); continue
        e=elig.iloc[0]; j=int(e.name)+19
        if j>=len(z) or z.iloc[j].Date.year>2022: miss.append(('end',r.stock_code)); continue
        end=z.iloc[j]
        b=idx[r.market]
        be=b[b.Date.eq(pd.Timestamp(e.Date))]
        bx=b[b.Date.eq(pd.Timestamp(end.Date))]
        if be.empty or bx.empty: miss.append(('benchmark_date',f'{r.market}:{e.Date}:{end.Date}')); continue
        br=(float(bx.iloc[0].Close)/float(be.iloc[0].Open)-1)*100
        d=r._asdict(); d['entry_date']=pd.Timestamp(e.Date).date().isoformat(); d['exit_date']=pd.Timestamp(end.Date).date().isoformat()
        d['benchmark_symbol']='^KS11' if r.market=='KOSPI' else '^KQ11'; d['benchmark_R20']=br
        d['market_excess_R20']=float(r.R20)-br; rows.append(d)
    out=pd.DataFrame(rows); out.to_csv(OUT,index=False)
    if len(out)!=365: raise SystemExit(f'benchmark coverage incomplete: {len(out)}/365; misses={miss[:20]}')

    fam={}
    groups={'ALL':out}
    for q in ['Q1','Q2','Q3','Q4','Q5']: groups[q]=out[out.improvement_quintile.astype(str).eq(q)]
    for name,g in groups.items():
        fam[name]={
          'absolute':stats(g,'R20'), 'benchmark':stats(g,'benchmark_R20'), 'excess':stats(g,'market_excess_R20'),
          '2021':{'absolute':stats(g[g.signal_year==2021],'R20'),'benchmark':stats(g[g.signal_year==2021],'benchmark_R20'),'excess':stats(g[g.signal_year==2021],'market_excess_R20')},
          '2022':{'absolute':stats(g[g.signal_year==2022],'R20'),'benchmark':stats(g[g.signal_year==2022],'benchmark_R20'),'excess':stats(g[g.signal_year==2022],'market_excess_R20')}
        }
    summary={'source':'Yahoo Finance chart API, no KRX auth key; ^KS11 for KOSPI and ^KQ11 for KOSDAQ',
             'window':'same event entry open -> same 20th trading-session close as stock R20',
             'oos_guard':'2023+ not used; benchmark data truncated at 2022-12-31',
             'candidate_n':int(len(out)),'families':fam}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
