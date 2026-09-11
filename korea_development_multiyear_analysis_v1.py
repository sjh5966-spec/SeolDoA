#!/usr/bin/env python3
from __future__ import annotations
import json, math, os
from pathlib import Path
import numpy as np
import pandas as pd
import requests

QFILE=Path('korea_dart_quarterly_2016_2020_full.csv')
SEC=Path('korea_historical_security_universe_2015_2020.csv')
SEED=Path('korea_dart_historical_seed_2015_2020.csv')
OUT=Path('korea_development_multiyear_events_v1.csv')
SUM=Path('korea_development_multiyear_summary_v1.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
PERIOD={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}


def normcode(v,n=6):
    s=str(v or '').replace('.0','').strip()
    return s.zfill(n) if s else ''

def stats(s):
    s=pd.to_numeric(s,errors='coerce').dropna()
    if not len(s): return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win':float((s>0).mean()),'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean()),'p10':float(s.quantile(.1)),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75)),'p90':float(s.quantile(.9))}

def load_accounting():
    d=pd.read_csv(QFILE,dtype={'corp_code':str},low_memory=False)
    d=d[d.business_year.astype(int).between(2016,2020)].copy()
    d['corp_code']=d.corp_code.astype(str).str.zfill(8)
    d['qord']=d.fiscal_quarter.map(QORD); d['seq']=d.business_year.astype(int)*4+d.qord.astype(int)
    d=d.sort_values(['corp_code','seq']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    return d

def coverage(d):
    seed=pd.read_csv(SEED,dtype=str).fillna('')
    seed=seed[seed.fiscal_year.astype(int).between(2016,2020)]
    expected=seed.groupby(seed.fiscal_year.astype(int)).corp_code.nunique().to_dict()
    out={}
    for y in range(2016,2021):
        z=d[d.business_year.astype(int).eq(y)]
        corps=z.corp_code.nunique(); rows=len(z)
        exp=int(expected.get(y,0))
        out[str(y)]={'expected_corps':exp,'observed_corps':int(corps),'rows':int(rows),'corp_coverage':float(corps/exp) if exp else None,'four_quarter_rows_expected':int(exp*4),'row_coverage':float(rows/(exp*4)) if exp else None}
    return out

def build_base(d):
    key={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)}
    seq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)}
    rows=[]
    for r in d.itertuples(index=False):
        y=int(r.business_year)
        if y<2017 or y>2020: continue
        py=key.get((r.corp_code,y-1,r.fiscal_quarter))
        four=[seq.get((r.corp_code,s)) for s in range(int(r.seq)-3,int(r.seq)+1)]
        if not all(x is not None for x in four): continue
        bases=[str(getattr(x,'statement_basis','') or '') for x in four]
        if not bases or not bases[0] or len(set(bases))!=1: continue
        nis=[getattr(x,'net_income_q',np.nan) for x in four]
        if not all(pd.notna(x) for x in nis): continue
        ni=float(sum(nis)); op=getattr(r,'operating_profit_q',np.nan); pop=getattr(py,'operating_profit_q',np.nan) if py is not None else np.nan; eq=getattr(r,'equity_q_end',np.nan)
        if pd.isna(op) or pd.isna(pop) or not (op>0 and pop<=0 and ni<0 and pd.notna(eq) and eq>0): continue
        f=getattr(r,'fcf_q',np.nan); pf=getattr(py,'fcf_q',np.nan) if py is not None else np.nan
        rows.append({'corp_code':r.corp_code,'company_name':getattr(r,'company_name',''),'business_year':y,'quarter':r.fiscal_quarter,'op_q':op,'prior_op_q':pop,'ni_ttm':ni,'equity':eq,'fcf_q':f,'fcf_yoy':f-pf if pd.notna(f) and pd.notna(pf) else np.nan})
    return pd.DataFrame(rows)

def attach_security(x):
    s=pd.read_csv(SEC,dtype=str).fillna('');s['corp_code']=s.corp_code.astype(str).str.zfill(8);s['fiscal_year']=pd.to_numeric(s.fiscal_year,errors='coerce')
    cols=['corp_code','fiscal_year','stock_code','security_review_status','observed_markets']
    s=s[cols].drop_duplicates(['corp_code','fiscal_year'])
    x=x.merge(s,left_on=['corp_code','business_year'],right_on=['corp_code','fiscal_year'],how='left')
    x['stock_code']=x.stock_code.map(normcode)
    return x

def attach_periodic_signal(x):
    u=pd.read_csv('korea_dart_historical_seed_2015_2020.csv',dtype=str).fillna('')
    u['corp_code']=u.corp_code.astype(str).str.zfill(8);u['fiscal_year']=pd.to_numeric(u.fiscal_year,errors='coerce')
    if 'is_earliest_corp_period' in u.columns:u=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')]
    u=u[u.period.isin(['Q1','H1','Q3','FY'])].copy();u['quarter']=u.period.map({'Q1':'Q1','H1':'Q2','Q3':'Q3','FY':'Q4'})
    u=u.sort_values(['corp_code','fiscal_year','quarter','rcept_dt','rcept_no']).drop_duplicates(['corp_code','fiscal_year','quarter'],keep='first')
    m=u[['corp_code','fiscal_year','quarter','rcept_dt','rcept_no']].rename(columns={'rcept_dt':'signal_date','rcept_no':'signal_receipt_no'})
    return x.merge(m,left_on=['corp_code','business_year','quarter'],right_on=['corp_code','fiscal_year','quarter'],how='left')

def get_market(year):
    p=Path(f'marcap-{year}.parquet')
    if not p.exists():
        r=requests.get(MARCAP.format(year=year),timeout=180);r.raise_for_status();p.write_bytes(r.content)
    z=pd.read_parquet(p)
    if 'Date' not in z.columns:z=z.reset_index()
    z['Date']=pd.to_datetime(z.Date);z['Code']=z.Code.map(normcode)
    return z[z.Market.isin(['KOSPI','KOSDAQ'])].sort_values(['Code','Date'])

def market_join(x):
    markets={y:get_market(y) for y in range(2017,2022)}
    rows=[]
    for r in x.itertuples(index=False):
        d=r._asdict(); sd=pd.to_datetime(str(r.signal_date),format='%Y%m%d',errors='coerce');code=normcode(r.stock_code);y=int(r.business_year)
        z=pd.concat([markets.get(y,pd.DataFrame()),markets.get(y+1,pd.DataFrame())],ignore_index=True) if y<2021 else markets.get(y,pd.DataFrame())
        z=z[z.Code.eq(code)].sort_values('Date').reset_index(drop=True) if len(z) else pd.DataFrame()
        if pd.isna(sd) or z.empty: d['status']='NO_SIGNAL_OR_MARKET';rows.append(d);continue
        pre=z[z.Date<sd];d['mcap_pre_signal']=float(pre.iloc[-1].Marcap) if len(pre) else np.nan
        elig=z[(z.Date>sd)&(pd.to_numeric(z.Open,errors='coerce')>0)&(pd.to_numeric(z.Volume,errors='coerce')>0)&(pd.to_numeric(z.Amount,errors='coerce')>0)]
        if elig.empty:d['status']='NO_ENTRY';rows.append(d);continue
        e=elig.iloc[0];idx=int(z.index[z.Date.eq(e.Date)][0]);d['entry_date']=e.Date.date().isoformat();d['entry_open']=float(e.Open);d['status']='OK'
        hist=z.iloc[max(0,idx-20):idx];d['adv20']=float(pd.to_numeric(hist.Amount,errors='coerce').mean()) if len(hist)==20 else np.nan
        for h in (5,10,20,60,120):
            j=idx+h-1;ret=np.nan;ca=np.nan
            if j<len(z):
                path=z.iloc[max(0,idx-1):j+1];sh=pd.to_numeric(path.Stocks,errors='coerce');rat=(sh/sh.shift(1)-1).abs();ca=bool((rat>0.20).fillna(False).any());ret=(float(z.iloc[j].Close)/float(e.Open)-1)*100
            d[f'CA_R{h}']=ca;d[f'R{h}']=ret if pd.notna(ret) and ca is False else np.nan
        mc=d.get('mcap_pre_signal',np.nan);d['fcf_pct']=float(r.fcf_q)/mc*100 if pd.notna(r.fcf_q) and pd.notna(mc) and mc>0 else np.nan;d['fcf_yoy_pct']=float(r.fcf_yoy)/mc*100 if pd.notna(r.fcf_yoy) and pd.notna(mc) and mc>0 else np.nan;d['loss_pct']=abs(float(r.ni_ttm))/mc*100 if pd.notna(mc) and mc>0 else np.nan
        rows.append(d)
    return pd.DataFrame(rows)

def slices(x):
    out={}
    clean=x[(x.status=='OK')&x.R20.notna()].copy()
    for y,g in clean.groupby('business_year'):
        yy={}; yy['all']=stats(g.R20)
        for cap in (30e9,40e9,50e9,80e9,100e9): yy[f'mcap_le_{int(cap/1e8)}eok']=stats(g.loc[g.mcap_pre_signal<=cap,'R20'])
        for cur in (0,3,5,7.5,10):
            for yoy in (0,5,10,12.5,15):
                z=g[(g.mcap_pre_signal<=50e9)&(g.fcf_pct>=cur)&(g.fcf_yoy_pct>=yoy)]
                if len(z)>=5: yy[f'cap500_cur{cur}_yoy{yoy}']=stats(z.R20)
        out[str(int(y))]=yy
    return out

def loo_grid(x):
    clean=x[(x.status=='OK')&x.R20.notna()].copy();years=sorted(clean.business_year.unique());rows=[]
    for cap in (30e9,40e9,50e9,80e9,100e9):
      for cur in (0,3,5,7.5,10):
       for yoy in (0,5,10,12.5,15):
        z=clean[(clean.mcap_pre_signal<=cap)&(clean.fcf_pct>=cur)&(clean.fcf_yoy_pct>=yoy)]
        if len(z)<15:continue
        yearly={str(int(y)):stats(z[z.business_year==y].R20) for y in years}
        medians=[v.get('median') for v in yearly.values() if v.get('n',0)>=5]
        neg=sum(1 for m in medians if m is not None and m<0)
        rows.append({'cap_krw':cap,'cur_fcf_pct':cur,'yoy_fcf_pct':yoy,'n':len(z),'median':float(z.R20.median()),'mean':float(z.R20.mean()),'years_ge5':len(medians),'negative_years':neg,'min_year_median':min(medians) if medians else None,'yearly':yearly})
    rows.sort(key=lambda r:(r['negative_years'],-(r['years_ge5']),-(r['min_year_median'] if r['min_year_median'] is not None else -999),-r['median'], -r['n']))
    return rows[:50]

def main():
    d=load_accounting();cov=coverage(d);base=build_base(d);base=attach_security(base);base=base[base.security_review_status.eq('MATCHED_COMMON_CANDIDATE')].copy();base=attach_periodic_signal(base);ev=market_join(base);ev.to_csv(OUT,index=False)
    summary={'development_only':True,'modern_oos_protected':True,'signal_rule':'earliest periodic receipt fallback only; preliminary disclosures not yet candidate-confirmed','coverage':cov,'base_a_by_year':base.groupby('business_year').size().to_dict(),'market_ok_by_year':ev[ev.status.eq('OK')].groupby('business_year').size().to_dict(),'clean_r20_by_year':ev[ev.R20.notna()].groupby('business_year').size().to_dict(),'yearly_slices':slices(ev),'loo_grid_top50':loo_grid(ev),'important_limitation':'Use only years with strong accounting coverage for Development threshold selection. Incomplete years are diagnostic, not efficacy evidence. 2021+ Validation and 2023+ OOS are not accessed.'}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
