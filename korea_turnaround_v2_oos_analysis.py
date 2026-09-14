#!/usr/bin/env python3
from pathlib import Path
import json, math, time, requests
import numpy as np
import pandas as pd

ACC=Path('korea_turnaround_v2_oos_accounting_2022_2025.csv')
VAL=Path('korea_validation_quarterly_2021_2022_full.csv')
OUT=Path('korea_turnaround_v2_oos_events.csv')
SUM=Path('korea_turnaround_v2_oos_summary.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
YH='https://query1.finance.yahoo.com/v8/finance/chart/{sym}'
UA={'User-Agent':'Mozilla/5.0'}
QMAP={'Q1':'Q1','H1':'Q2','Q3':'Q3','FY':'Q4'}
SIGNAL_START=pd.Timestamp('2023-01-01'); SIGNAL_END=pd.Timestamp('2025-12-31')
THRESHOLD=5.0; MCAP_MAX=50e9; PEERS=20

def norm(v):
    s=str(v or '').replace('.0','').strip(); return s.zfill(6) if s else ''

def get_marcap(y):
    if y<2022 or y>2026: raise SystemExit('OOS market year outside frozen scope')
    p=Path(f'marcap-{y}.parquet')
    if not p.exists():
        r=requests.get(MARCAP.format(year=y),headers=UA,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
    z=pd.read_parquet(p)
    if 'Date' not in z: z=z.reset_index()
    z['Date']=pd.to_datetime(z['Date']); z['Code']=z['Code'].map(norm)
    return z[z.Market.isin(['KOSPI','KOSDAQ'])].sort_values(['Code','Date']).reset_index(drop=True)

def yahoo(sym):
    params={'period1':int(pd.Timestamp('2022-12-01',tz='UTC').timestamp()),'period2':int(pd.Timestamp('2026-03-01',tz='UTC').timestamp()),'interval':'1d','events':'history','includeAdjustedClose':'true'}
    for k in range(5):
        r=requests.get(YH.format(sym=sym),params=params,headers=UA,timeout=60)
        if r.ok:
            js=r.json(); res=(js.get('chart') or {}).get('result')
            if res:
                q=res[0]; ts=q.get('timestamp') or []; quote=((q.get('indicators') or {}).get('quote') or [{}])[0]
                d=pd.DataFrame({'Date':pd.to_datetime(ts,unit='s',utc=True).tz_convert('Asia/Seoul').tz_localize(None).normalize(),'Open':quote.get('open',[]),'Close':quote.get('close',[])})
                return d.dropna().drop_duplicates('Date').sort_values('Date').reset_index(drop=True)
        time.sleep(2*(k+1))
    raise RuntimeError(f'Yahoo failed {sym}')

def stats(g,col):
    s=pd.to_numeric(g[col],errors='coerce').dropna()
    if s.empty:return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win_rate':float((s>0).mean()),'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean()),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75))}

def signal_map():
    fs=sorted(Path('.').glob('oos_universe_*/korea_dart_historical_universe_20??.csv'))
    if not fs: fs=sorted(Path('.').glob('korea_dart_historical_universe_20??.csv'))
    frames=[]
    for f in fs:
        u=pd.read_csv(f,dtype=str).fillna('')
        if 'is_earliest_corp_period' in u: u=u[u.is_earliest_corp_period.str.lower().eq('true')]
        u['corp_code']=u.corp_code.astype(str).str.zfill(8)
        u['business_year']=pd.to_numeric(u['target_year'],errors='coerce')
        u['fiscal_quarter']=u['period'].map(QMAP)
        u['signal_date']=pd.to_datetime(u['rcept_dt'],format='%Y%m%d',errors='coerce')
        u=u[u.signal_date.between(SIGNAL_START,SIGNAL_END)]
        frames.append(u[['corp_code','business_year','fiscal_quarter','stock_code','corp_cls','signal_date']])
    x=pd.concat(frames,ignore_index=True)
    return x.sort_values(['corp_code','business_year','fiscal_quarter','signal_date']).drop_duplicates(['corp_code','business_year','fiscal_quarter'])

def main():
    a=pd.read_csv(ACC,dtype={'corp_code':str},low_memory=False); a.corp_code=a.corp_code.astype(str).str.zfill(8)
    v=pd.read_csv(VAL,dtype={'corp_code':str},low_memory=False); v.corp_code=v.corp_code.astype(str).str.zfill(8)
    a=pd.concat([v,a],ignore_index=True); a['business_year']=pd.to_numeric(a.business_year,errors='coerce')
    a=a.sort_values(['corp_code','business_year','fiscal_quarter']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    prev=a[['corp_code','business_year','fiscal_quarter','statement_basis','operating_profit_q']].copy(); prev.business_year=prev.business_year+1
    prev=prev.rename(columns={'statement_basis':'prior_basis','operating_profit_q':'prior_op_q'})
    x=a.merge(prev,on=['corp_code','business_year','fiscal_quarter'],how='left')
    x=x[x.statement_basis.fillna('').ne('') & x.statement_basis.eq(x.prior_basis)]
    x=x.merge(signal_map(),on=['corp_code','business_year','fiscal_quarter'],how='inner')

    mk={y:get_marcap(y) for y in range(2022,2027)}
    by={}
    for z in mk.values():
        for c,g in z.groupby('Code',sort=False): by.setdefault(c,[]).append(g)
    by={c:pd.concat(gs).sort_values('Date').drop_duplicates('Date').reset_index(drop=True) for c,gs in by.items()}
    idx={'KOSPI':yahoo('%5EKS11'),'KOSDAQ':yahoo('%5EKQ11')}
    rows=[]; drops={}
    def dr(k): drops[k]=drops.get(k,0)+1
    for r in x.itertuples(index=False):
        code=norm(r.stock_code); sd=pd.Timestamp(r.signal_date); z=by.get(code)
        if z is None: dr('no_market'); continue
        pre=z[z.Date<sd]
        if pre.empty: dr('no_pre_market'); continue
        mc=float(pre.iloc[-1].Marcap); mkt=str(pre.iloc[-1].Market)
        op=pd.to_numeric(pd.Series([r.operating_profit_q]),errors='coerce').iloc[0]; pop=pd.to_numeric(pd.Series([r.prior_op_q]),errors='coerce').iloc[0]
        if pd.isna(op) or pd.isna(pop): dr('missing_op'); continue
        opy=(op-pop)/mc*100
        if mc>MCAP_MAX or opy<THRESHOLD: dr('frozen_rule_fail'); continue
        elig=z[(z.Date>sd)&(pd.to_numeric(z.Open,errors='coerce')>0)&(pd.to_numeric(z.Volume,errors='coerce')>0)]
        if elig.empty: dr('no_entry'); continue
        e=elig.iloc[0]; ei=int(e.name); j=ei+19
        if j>=len(z): dr('r20_unmatured'); continue
        end=z.iloc[j]
        path=z.iloc[ei:j+1]; sh=pd.to_numeric(path.Stocks,errors='coerce')
        if bool(((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any()): dr('corporate_action'); continue
        R20=(float(end.Close)/float(e.Open)-1)*100
        b=idx[mkt]; be=b[b.Date.eq(pd.Timestamp(e.Date))]; bx=b[b.Date.eq(pd.Timestamp(end.Date))]
        if be.empty or bx.empty: dr('benchmark_missing'); continue
        br=(float(bx.iloc[0].Close)/float(be.iloc[0].Open)-1)*100
        # same-market nearest PIT market-cap peers, exact event dates
        allz=pd.concat([mk.get(sd.year-1,pd.DataFrame()),mk.get(sd.year,pd.DataFrame())],ignore_index=True)
        ppre=allz[allz.Date<sd].sort_values('Date').groupby('Code',as_index=False).tail(1)
        ppre=ppre[(ppre.Market==mkt)&(ppre.Code!=code)&(pd.to_numeric(ppre.Marcap,errors='coerce')>0)].copy()
        ppre['dist']=(np.log(pd.to_numeric(ppre.Marcap,errors='coerce'))-math.log(mc)).abs(); ppre=ppre.nsmallest(100,'dist')
        prs=[]
        for pr in ppre.itertuples(index=False):
            pz=by.get(norm(pr.Code));
            if pz is None: continue
            pe=pz[pz.Date.eq(pd.Timestamp(e.Date))]; px=pz[pz.Date.eq(pd.Timestamp(end.Date))]
            if pe.empty or px.empty: continue
            pe=pe.iloc[0]; px=px.iloc[0]
            if float(pe.Open)<=0 or float(pe.Volume)<=0: continue
            ppath=pz[(pz.Date>=pd.Timestamp(e.Date))&(pz.Date<=pd.Timestamp(end.Date))]; psh=pd.to_numeric(ppath.Stocks,errors='coerce')
            if bool(((psh/psh.shift(1)-1).abs()>0.20).fillna(False).any()): continue
            rr=(float(px.Close)/float(pe.Open)-1)*100
            if np.isfinite(rr): prs.append(rr)
            if len(prs)>=PEERS: break
        peer_med=float(np.median(prs)) if len(prs)>=10 else np.nan
        rows.append({'corp_code':r.corp_code,'stock_code':code,'market':mkt,'business_year':int(r.business_year),'fiscal_quarter':r.fiscal_quarter,'signal_date':sd.date().isoformat(),'signal_year':sd.year,'entry_date':pd.Timestamp(e.Date).date().isoformat(),'exit_date':pd.Timestamp(end.Date).date().isoformat(),'mcap':mc,'op_q':op,'prior_op_q':pop,'op_yoy_pct':opy,'R20':R20,'benchmark_R20':br,'market_excess_R20':R20-br,'matched_peer_n':len(prs),'matched_peer_median_R20':peer_med,'matched_excess_R20':R20-peer_med if np.isfinite(peer_med) else np.nan})
    out=pd.DataFrame(rows); out.to_csv(OUT,index=False)
    fam={'all':{'absolute':stats(out,'R20'),'market_excess':stats(out,'market_excess_R20'),'matched_excess':stats(out,'matched_excess_R20')}}
    for y in [2023,2024,2025]:
        g=out[out.signal_year==y]; fam[str(y)]={'absolute':stats(g,'R20'),'market_excess':stats(g,'market_excess_R20'),'matched_excess':stats(g,'matched_excess_R20')}
    summary={'lock_commit':'2a74fa7d9344cbf8c7c9cf8337d9cdf97a965eca','frozen_rule':'mcap<=50B KRW and pure-quarter OP YoY improvement / PIT mcap >=5%; entry next tradable open; R20; CA excluded','signal_window':'2023-01-01..2025-12-31','eligible_clean_events':int(len(out)),'drop_reasons':drops,'results':fam}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
