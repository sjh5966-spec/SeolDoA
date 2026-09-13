#!/usr/bin/env python3
"""One-time Korea 2021-2022 Validation analysis using the pre-Validation locked rule.

Guardrails:
- Validation signal dates only: 2021-01-01..2022-12-31.
- 2022 Q4 accounting is forbidden.
- No 2023+ filings, prices, or returns are read.
- Locked thresholds only: PIT mcap <= KRW 50B; current FCF/mcap >= 0%; YoY FCF improvement/mcap >= 5%.
- R20 only for strategy decision; no alternate thresholds/holding periods/exits/liquidity filters.
- Periodic DART receipt is the conservative reproducible signal fallback used in Development threshold selection.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import requests

VAL=Path('korea_validation_quarterly_2021_2022_full.csv')
DEV=Path('korea_dart_quarterly_2016_2020_full.csv')
U21=Path('korea_validation_historical_universe_2021.csv')
U22=Path('korea_validation_historical_universe_2022.csv')
OUT=Path('korea_validation_locked_events_v1.csv')
SUM=Path('korea_validation_locked_summary_v1.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
PERIOD={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}


def normcode(v,n=6):
    s=str(v or '').replace('.0','').strip()
    return s.zfill(n) if s else ''


def stat(s):
    s=pd.to_numeric(s,errors='coerce').dropna()
    if len(s)==0:return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win_rate':float((s>0).mean()),
            'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean()),'p10':float(s.quantile(.10)),
            'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75)),'p90':float(s.quantile(.90))}


def bootstrap_median_ci(s,seed=20210911,nboot=10000):
    a=pd.to_numeric(s,errors='coerce').dropna().to_numpy(float)
    if len(a)<2:return [None,None]
    rng=np.random.default_rng(seed)
    meds=np.median(rng.choice(a,size=(nboot,len(a)),replace=True),axis=1)
    return [float(np.quantile(meds,.025)),float(np.quantile(meds,.975))]


def load_accounting():
    v=pd.read_csv(VAL,dtype={'corp_code':str},low_memory=False)
    v['corp_code']=v.corp_code.astype(str).str.zfill(8)
    v['business_year']=pd.to_numeric(v.business_year,errors='coerce').astype('Int64')
    if ((v.business_year==2022)&v.fiscal_quarter.eq('Q4')).any():
        raise SystemExit('OOS guard: validation accounting contains forbidden 2022 Q4')
    d=pd.read_csv(DEV,dtype={'corp_code':str},low_memory=False)
    d['corp_code']=d.corp_code.astype(str).str.zfill(8)
    d['business_year']=pd.to_numeric(d.business_year,errors='coerce').astype('Int64')
    d=d[d.business_year.eq(2020)].copy()
    x=pd.concat([d,v],ignore_index=True)
    x['qord']=x.fiscal_quarter.map(QORD)
    x=x[x.qord.notna() & x.business_year.notna()].copy()
    x['seq']=x.business_year.astype(int)*4+x.qord.astype(int)
    x=x.sort_values(['corp_code','seq']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    return x


def build_base(a):
    byq={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in a.itertuples(index=False)}
    byseq={(r.corp_code,int(r.seq)):r for r in a.itertuples(index=False)}
    rows=[]; drops={}
    def drop(k):drops[k]=drops.get(k,0)+1
    for r in a[a.business_year.astype(int).isin([2021,2022])].itertuples(index=False):
        y=int(r.business_year); q=r.fiscal_quarter
        if y==2022 and q=='Q4':raise SystemExit('OOS guard tripped')
        py=byq.get((r.corp_code,y-1,q))
        if py is None:drop('missing_prior_year_same_quarter');continue
        four=[byseq.get((r.corp_code,s)) for s in range(int(r.seq)-3,int(r.seq)+1)]
        if not all(z is not None for z in four):drop('missing_exact_four_quarters_ttm');continue
        bases=[str(getattr(z,'statement_basis','') or '') for z in four]
        if not bases[0] or len(set(bases))!=1:drop('ttm_basis_noncomparable');continue
        if str(getattr(py,'statement_basis','') or '')!=str(getattr(r,'statement_basis','') or ''):drop('yoy_basis_noncomparable');continue
        ni=[getattr(z,'net_income_q',np.nan) for z in four]
        if not all(pd.notna(z) for z in ni):drop('missing_ttm_net_income');continue
        op=getattr(r,'operating_profit_q',np.nan); pop=getattr(py,'operating_profit_q',np.nan); eq=getattr(r,'equity_q_end',np.nan)
        if pd.isna(op) or pd.isna(pop) or pd.isna(eq):drop('missing_base_accounting_field');continue
        if not (float(op)>0 and float(pop)<=0 and float(sum(ni))<0 and float(eq)>0):drop('fails_base_a');continue
        f=getattr(r,'fcf_q',np.nan); pf=getattr(py,'fcf_q',np.nan)
        rows.append({'corp_code':r.corp_code,'company_name':getattr(r,'company_name',''),'business_year':y,'quarter':q,
                     'statement_basis':getattr(r,'statement_basis',''),'op_q':op,'prior_op_q':pop,'ni_ttm':float(sum(ni)),
                     'equity':eq,'fcf_q':f,'prior_fcf_q':pf,'fcf_yoy':(float(f)-float(pf)) if pd.notna(f) and pd.notna(pf) else np.nan})
    return pd.DataFrame(rows),drops


def signal_map():
    parts=[]
    for p,y in [(U21,2021),(U22,2022)]:
        u=pd.read_csv(p,dtype=str).fillna('')
        u['corp_code']=u.corp_code.astype(str).str.zfill(8)
        if 'is_earliest_corp_period' in u.columns:
            u=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')].copy()
        else:
            u=u.sort_values(['corp_code','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','period'],keep='first')
        u=u[u.period.isin(['Q1','H1','Q3','FY'])].copy()
        u['business_year']=y
        u['quarter']=u.period.map({'Q1':'Q1','H1':'Q2','Q3':'Q3','FY':'Q4'})
        if y==2022:u=u[u.quarter.ne('Q4')].copy()
        parts.append(u[['corp_code','business_year','quarter','stock_code','corp_cls','rcept_dt','rcept_no','report_nm']])
    m=pd.concat(parts,ignore_index=True)
    m=m.sort_values(['corp_code','business_year','quarter','rcept_dt','rcept_no']).drop_duplicates(['corp_code','business_year','quarter'],keep='first')
    m=m.rename(columns={'rcept_dt':'signal_date','rcept_no':'signal_receipt_no','report_nm':'signal_report_nm'})
    return m


def get_market(y):
    p=Path(f'marcap-{y}.parquet')
    if not p.exists():
        if y>2022:raise SystemExit('OOS guard: attempted market year > 2022')
        r=requests.get(MARCAP.format(year=y),timeout=180);r.raise_for_status();p.write_bytes(r.content)
    z=pd.read_parquet(p)
    if 'Date' not in z.columns:z=z.reset_index()
    z['Date']=pd.to_datetime(z.Date);z['Code']=z.Code.map(normcode)
    return z[z.Market.isin(['KOSPI','KOSDAQ'])].sort_values(['Code','Date'])


def attach_market(x):
    mk={2021:get_market(2021),2022:get_market(2022)}
    bycode={}
    for y,z in mk.items():
        for code,g in z.groupby('Code',sort=False):bycode.setdefault(code,[]).append(g)
    bycode={c:pd.concat(gs,ignore_index=True).sort_values('Date').reset_index(drop=True) for c,gs in bycode.items()}
    out=[]; drops={}
    def drop(k):drops[k]=drops.get(k,0)+1
    for r in x.itertuples(index=False):
        d=r._asdict(); sd=pd.to_datetime(str(r.signal_date),format='%Y%m%d',errors='coerce'); code=normcode(r.stock_code)
        if pd.isna(sd) or not (pd.Timestamp('2021-01-01')<=sd<=pd.Timestamp('2022-12-31')):
            d['status']='SIGNAL_OUTSIDE_VALIDATION_OR_MISSING';drop(d['status']);out.append(d);continue
        z=bycode.get(code)
        if z is None or z.empty:d['status']='NO_KOSPI_KOSDAQ_MARKET';drop(d['status']);out.append(d);continue
        pre=z[z.Date<sd]
        if pre.empty:d['status']='NO_PRE_SIGNAL_MARKET';drop(d['status']);out.append(d);continue
        d['mcap_pre_signal']=float(pre.iloc[-1].Marcap);d['market']=str(pre.iloc[-1].Market)
        elig=z[(z.Date>sd)&(pd.to_numeric(z.Open,errors='coerce')>0)&(pd.to_numeric(z.Volume,errors='coerce')>0)&(pd.to_numeric(z.Amount,errors='coerce')>0)]
        if elig.empty:d['status']='NO_ENTRY_WITHIN_2022';drop(d['status']);out.append(d);continue
        e=elig.iloc[0]; idx=int(z.index[z.Date.eq(e.Date)][0])
        d['entry_date']=e.Date.date().isoformat();d['entry_open']=float(e.Open);d['market']=str(e.Market)
        hist=z.iloc[max(0,idx-20):idx];d['adv20']=float(pd.to_numeric(hist.Amount,errors='coerce').mean()) if len(hist)==20 else np.nan
        j=idx+19
        if j>=len(z) or pd.Timestamp(z.iloc[j].Date).year>2022:
            d['status']='R20_CENSORED_NO_2023_PRICE';drop(d['status']);out.append(d);continue
        path=z.iloc[max(0,idx-1):j+1];sh=pd.to_numeric(path.Stocks,errors='coerce');rat=(sh/sh.shift(1)-1).abs()
        ca=bool((rat>0.20).fillna(False).any());d['ca_r20']=ca
        d['R20_raw']=(float(z.iloc[j].Close)/float(e.Open)-1)*100
        d['R20']=np.nan if ca else d['R20_raw']
        d['status']='OK_CA_EXCLUDED' if ca else 'OK'
        if ca:drop('CORPORATE_ACTION_R20')
        mc=d['mcap_pre_signal'];d['fcf_pct']=float(r.fcf_q)/mc*100 if pd.notna(r.fcf_q) and mc>0 else np.nan
        d['fcf_yoy_pct']=float(r.fcf_yoy)/mc*100 if pd.notna(r.fcf_yoy) and mc>0 else np.nan
        d['signal_year']=int(sd.year)
        d['locked_filter']=bool(mc<=50e9 and pd.notna(d['fcf_pct']) and pd.notna(d['fcf_yoy_pct']) and d['fcf_pct']>=0 and d['fcf_yoy_pct']>=5)
        out.append(d)
    return pd.DataFrame(out),drops


def group_stats(g):
    z=g[g.status.eq('OK') & g.R20.notna()].copy()
    s=stat(z.R20);s['bootstrap_median_95ci']=bootstrap_median_ci(z.R20)
    return s


def main():
    a=load_accounting();base,base_drops=build_base(a)
    sig=signal_map();base=base.merge(sig,on=['corp_code','business_year','quarter'],how='left')
    ev,market_drops=attach_market(base);ev.to_csv(OUT,index=False)
    clean=ev[ev.status.eq('OK') & ev.R20.notna()].copy();frozen=clean[clean.locked_filter.fillna(False)].copy()
    yearly={}
    for y in (2021,2022):
        yearly[str(y)]={'base_a':group_stats(clean[clean.signal_year.eq(y)]),'frozen':group_stats(frozen[frozen.signal_year.eq(y)])}
    markets={}
    for m in ('KOSPI','KOSDAQ'):
        markets[m]={'base_a':group_stats(clean[clean.market.eq(m)]),'frozen':group_stats(frozen[frozen.market.eq(m)])}
    capdiag={}
    for label,lo,hi in [('le20b',0,20e9),('20_50b',20e9,50e9),('gt50b',50e9,float('inf'))]:
        g=clean[(clean.mcap_pre_signal>lo)&(clean.mcap_pre_signal<=hi)] if lo else clean[clean.mcap_pre_signal<=hi]
        capdiag[label]=group_stats(g)
    liq={}
    q=pd.qcut(clean.adv20.rank(method='first'),4,labels=False,duplicates='drop') if clean.adv20.notna().sum()>=4 else pd.Series(index=clean.index,dtype=float)
    for k in sorted(pd.Series(q).dropna().unique()):liq[f'adv20_q{int(k)+1}']=group_stats(clean[q.eq(k)])
    summary={'validation_only':True,'one_time_locked_check':True,'modern_oos_protected':True,
      'validation_signal_window':['2021-01-01','2022-12-31'],'forbidden_market_years':'2023+',
      'signal_method':'earliest DART periodic receipt fallback, matching conservative Development threshold-selection timing; preliminary timing not reconstructed here',
      'locked_rule':{'mcap_max_krw':50000000000,'current_fcf_pct_min':0.0,'fcf_yoy_pct_min':5.0,'primary_horizon':'R20','ca_contaminated_excluded':True},
      'accounting_rows_context':int(len(a)),'base_a_candidates_before_signal_market':int(len(base)),'base_a_drop_reasons':base_drops,'market_drop_reasons':market_drops,
      'base_a_clean':group_stats(clean),'frozen_filter_clean':group_stats(frozen),'yearly_by_signal_year':yearly,'market_split':markets,
      'market_cap_diagnostic_base_a':capdiag,'liquidity_diagnostic_base_a':liq,
      'counts':{'event_rows':int(len(ev)),'clean_base_a':int(len(clean)),'clean_frozen':int(len(frozen)),'ca_excluded':int(ev.status.eq('OK_CA_EXCLUDED').sum()),'r20_censored_no_2023':int(ev.status.eq('R20_CENSORED_NO_2023_PRICE').sum())},
      'limitations':['2021 accounting corpus coverage is below 100%; missing corp-years can induce selection bias if missingness is non-random.',
                     'Historical universe is DART Y/K periodic-filer based and then intersected with historical KOSPI/KOSDAQ market data; security-type and delisting coverage inherits those sources.',
                     'Signal timing uses periodic-report receipt fallback for direct comparability to Development; earlier preliminary disclosures are not reconstructed in this one-time efficacy check.'],
      'decision_note':'This file reports locked Validation evidence only. Do not retune thresholds from these results; make Pass/Fail from the frozen specification and record it before any 2023+ OOS access.'}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
