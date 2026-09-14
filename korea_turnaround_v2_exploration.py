#!/usr/bin/env python3
"""Turnaround V2 research exploration using only already-opened 2020-2022 data.

This is a NEW research generation after V1 Validation failed for insufficient replication.
2021-2022 are therefore Development/Research for V2, not Validation.
Hard guard: never read 2023+ filings, prices, or returns.
Goal: test whether continuous improvement (FCF and/or operating profit), including loss
narrowing, is more useful and better populated than V1's hard profitability intersection.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import requests

VAL=Path('korea_validation_quarterly_2021_2022_full.csv')
DEV=Path('korea_dart_quarterly_2016_2020_full.csv')
U21=Path('korea_validation_historical_universe_2021.csv')
U22=Path('korea_validation_historical_universe_2022.csv')
OUT=Path('korea_turnaround_v2_events.csv')
SUM=Path('korea_turnaround_v2_summary.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}

def norm(v,n=6):
    s=str(v or '').replace('.0','').strip(); return s.zfill(n) if s else ''

def stats(g):
    s=pd.to_numeric(g.R20,errors='coerce').dropna()
    if len(s)==0:return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win_rate':float((s>0).mean()),
            'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean()),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75))}

def load_acc():
    v=pd.read_csv(VAL,dtype={'corp_code':str},low_memory=False); v.corp_code=v.corp_code.astype(str).str.zfill(8)
    v.business_year=pd.to_numeric(v.business_year,errors='coerce').astype('Int64')
    if ((v.business_year==2022)&v.fiscal_quarter.eq('Q4')).any(): raise SystemExit('OOS guard: 2022 Q4 forbidden')
    d=pd.read_csv(DEV,dtype={'corp_code':str},low_memory=False); d.corp_code=d.corp_code.astype(str).str.zfill(8)
    d.business_year=pd.to_numeric(d.business_year,errors='coerce').astype('Int64'); d=d[d.business_year.eq(2020)]
    return pd.concat([d,v],ignore_index=True)

def signal_map():
    ps=[]
    for p,y in [(U21,2021),(U22,2022)]:
        u=pd.read_csv(p,dtype=str).fillna(''); u.corp_code=u.corp_code.astype(str).str.zfill(8)
        if 'is_earliest_corp_period' in u: u=u[u.is_earliest_corp_period.str.lower().eq('true')]
        u['business_year']=y; u['quarter']=u.period.map({'Q1':'Q1','H1':'Q2','Q3':'Q3','FY':'Q4'})
        if y==2022:u=u[u.quarter.ne('Q4')]
        ps.append(u[['corp_code','business_year','quarter','stock_code','corp_cls','rcept_dt']])
    return pd.concat(ps).sort_values(['corp_code','business_year','quarter','rcept_dt']).drop_duplicates(['corp_code','business_year','quarter']).rename(columns={'rcept_dt':'signal_date'})

def market(y):
    if y>2022: raise SystemExit('OOS guard: market year >2022')
    p=Path(f'marcap-{y}.parquet')
    if not p.exists():
        r=requests.get(MARCAP.format(year=y),timeout=180);r.raise_for_status();p.write_bytes(r.content)
    z=pd.read_parquet(p)
    if 'Date' not in z:z=z.reset_index()
    z.Date=pd.to_datetime(z.Date);z.Code=z.Code.map(norm)
    return z[z.Market.isin(['KOSPI','KOSDAQ'])].sort_values(['Code','Date']).reset_index(drop=True)

def main():
    a=load_acc(); a['qord']=a.fiscal_quarter.map(QORD); a=a[a.qord.notna()].copy()
    a=a.sort_values(['corp_code','business_year','qord']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    prev=a[['corp_code','business_year','fiscal_quarter','statement_basis','operating_profit_q','fcf_q']].copy()
    prev.business_year=prev.business_year+1
    prev=prev.rename(columns={'statement_basis':'prior_basis','operating_profit_q':'prior_op_q','fcf_q':'prior_fcf_q'})
    x=a[a.business_year.isin([2021,2022])].merge(prev,on=['corp_code','business_year','fiscal_quarter'],how='left')
    x=x[(x.statement_basis.fillna('')!='') & x.statement_basis.eq(x.prior_basis)].copy()
    x=x.merge(signal_map(),left_on=['corp_code','business_year','fiscal_quarter'],right_on=['corp_code','business_year','quarter'],how='left')
    mk={2021:market(2021),2022:market(2022)}; by={}
    for y,z in mk.items():
        for c,g in z.groupby('Code',sort=False):by.setdefault(c,[]).append(g)
    by={c:pd.concat(gs).sort_values('Date').reset_index(drop=True) for c,gs in by.items()}
    rows=[]; drops={}
    def dr(k):drops[k]=drops.get(k,0)+1
    for r in x.itertuples(index=False):
        sd=pd.to_datetime(str(r.signal_date),format='%Y%m%d',errors='coerce'); code=norm(r.stock_code)
        if pd.isna(sd) or not(pd.Timestamp('2021-01-01')<=sd<=pd.Timestamp('2022-12-31')):dr('bad_signal');continue
        z=by.get(code)
        if z is None or z.empty:dr('no_market');continue
        pre=z[z.Date<sd]
        if pre.empty:dr('no_pre_market');continue
        mc=float(pre.iloc[-1].Marcap); mkt=str(pre.iloc[-1].Market)
        elig=z[(z.Date>sd)&(pd.to_numeric(z.Open,errors='coerce')>0)&(pd.to_numeric(z.Volume,errors='coerce')>0)]
        if elig.empty:dr('no_entry');continue
        e=elig.iloc[0]; idx=int(elig.index[0]); j=idx+19
        if j>=len(z) or z.iloc[j].Date.year>2022:dr('r20_censored');continue
        path=z.iloc[max(0,idx-1):j+1]; sh=pd.to_numeric(path.Stocks,errors='coerce'); ca=bool(((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any())
        if ca:dr('corporate_action');continue
        op=pd.to_numeric(pd.Series([r.operating_profit_q]),errors='coerce').iloc[0]; pop=pd.to_numeric(pd.Series([r.prior_op_q]),errors='coerce').iloc[0]
        f=pd.to_numeric(pd.Series([r.fcf_q]),errors='coerce').iloc[0]; pf=pd.to_numeric(pd.Series([r.prior_fcf_q]),errors='coerce').iloc[0]
        if pd.isna(op) or pd.isna(pop):dr('missing_op');continue
        hist=z.iloc[max(0,idx-20):idx]; adv=float(pd.to_numeric(hist.Amount,errors='coerce').mean()) if len(hist)==20 else np.nan
        rows.append({'corp_code':r.corp_code,'company_name':getattr(r,'company_name',''),'signal_date':sd.date().isoformat(),'signal_year':sd.year,
          'stock_code':code,'market':mkt,'mcap':mc,'adv20':adv,'op_q':op,'prior_op_q':pop,'op_yoy_pct':(op-pop)/mc*100,
          'fcf_q':f,'prior_fcf_q':pf,'fcf_yoy_pct':(f-pf)/mc*100 if pd.notna(f) and pd.notna(pf) else np.nan,
          'op_current_pct':op/mc*100,'fcf_current_pct':f/mc*100 if pd.notna(f) else np.nan,
          'op_loss_narrowing':bool(op<0 and pop<0 and op>pop),'op_turn_positive':bool(op>0 and pop<=0),'op_profit_expansion':bool(op>0 and pop>0 and op>pop),
          'fcf_loss_narrowing':bool(pd.notna(f) and pd.notna(pf) and f<0 and pf<0 and f>pf),'fcf_turn_positive':bool(pd.notna(f) and pd.notna(pf) and f>=0 and pf<0),
          'R20':(float(z.iloc[j].Close)/float(e.Open)-1)*100})
    ev=pd.DataFrame(rows); ev.to_csv(OUT,index=False)
    # V2 is exploratory: use broad, interpretable families and monotonic bins, not a threshold grid.
    small=ev[ev.mcap<=50e9].copy()
    families={
      'small_all':small,
      'op_improving':small[small.op_yoy_pct>0],
      'op_loss_narrowing':small[small.op_loss_narrowing],
      'op_turn_positive':small[small.op_turn_positive],
      'op_profit_expansion':small[small.op_profit_expansion],
      'fcf_improving':small[small.fcf_yoy_pct>0],
      'fcf_loss_narrowing':small[small.fcf_loss_narrowing],
      'fcf_turn_positive':small[small.fcf_turn_positive],
      'dual_improving':small[(small.op_yoy_pct>0)&(small.fcf_yoy_pct>0)],
      'op_improving_fcf_nonworsening':small[(small.op_yoy_pct>0)&(small.fcf_yoy_pct>=0)],
    }
    fam={k:{'all':stats(g),'2021':stats(g[g.signal_year==2021]),'2022':stats(g[g.signal_year==2022])} for k,g in families.items()}
    bins={}
    for col in ['op_yoy_pct','fcf_yoy_pct']:
        q=small[col].dropna()
        if len(q)>=20:
            labels=pd.qcut(small.loc[q.index,col].rank(method='first'),5,labels=False,duplicates='drop')
            bins[col]={f'Q{int(k)+1}':stats(small.loc[labels[labels==k].index]) for k in sorted(labels.dropna().unique())}
    summary={'research_generation':'Turnaround V2','v1_status':'frozen FAIL; not modified','v2_period_role':'2021-2022 are Development/Research because V1 Validation was already observed',
      'oos_guard':'2023+ unopened and forbidden','design':'continuous improvement and state-transition families; no V1 retrofit',
      'event_count':int(len(ev)),'smallcap_event_count':int(len(small)),'drop_reasons':drops,'families':fam,'quintiles':bins,
      'interpretation_rule':'Prefer a V2 candidate only if it has materially larger sample than V1 frozen filter, positive median/mean, >50% win rate, and same-sign median in both 2021 and 2022. Do not open 2023+ until a V2 rule is explicitly frozen.'}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
