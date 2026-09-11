#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

QFILE=Path('inputs/accounting/korea_dart_quarterly_2016_2020_full.csv')
SEC=Path('inputs/security/korea_historical_security_universe_2015_2020.csv')
UNIDIR=Path('inputs/universe')
MARCAPDIR=Path('inputs/marcap/korea_marcap_raw_2015_2022')
YEARS=[2017,2018,2019,2020]
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
SRC_PERIOD={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}
OUT=Path('korea_development_multiyear_events_v1.csv')
GRID=Path('korea_development_multiyear_grid_v1.csv')
SUM=Path('korea_development_multiyear_summary_v1.json')

def st(s):
    s=pd.to_numeric(s,errors='coerce').dropna()
    if len(s)==0:return {'n':0}
    return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win':float((s>0).mean()),'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean()),'p10':float(s.quantile(.1)),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75)),'p90':float(s.quantile(.9))}

def bootstrap_median_ci(s,seed=5966,nboot=4000):
    a=pd.to_numeric(s,errors='coerce').dropna().to_numpy()
    if len(a)<5:return [None,None]
    rng=np.random.default_rng(seed)
    meds=np.median(rng.choice(a,size=(nboot,len(a)),replace=True),axis=1)
    return [float(np.quantile(meds,.025)),float(np.quantile(meds,.975))]

def accounting():
    d=pd.read_csv(QFILE,dtype={'corp_code':str},low_memory=False)
    d=d[d.business_year.astype(int).between(2016,2020)].copy()
    d['corp_code']=d.corp_code.astype(str).str.zfill(8)
    d['qord']=d.fiscal_quarter.map(QORD)
    d['seq']=d.business_year.astype(int)*4+d.qord.astype(int)
    # Same corp-quarter duplicates can occur around name changes; retain last identical accounting observation.
    d=d.sort_values(['corp_code','seq','company_name']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    key={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)}
    seq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)}
    rows=[]
    for r in d[d.business_year.astype(int).isin(YEARS)].itertuples(index=False):
        y=int(r.business_year); py=key.get((r.corp_code,y-1,r.fiscal_quarter))
        four=[seq.get((r.corp_code,s)) for s in range(int(r.seq)-3,int(r.seq)+1)]
        exact=all(x is not None for x in four)
        bases=[str(getattr(x,'statement_basis','') or '') for x in four] if exact else []
        same=bool(exact and bases and len(set(bases))==1 and bases[0])
        nis=[getattr(x,'net_income_q',np.nan) if x is not None else np.nan for x in four]
        ni=float(sum(nis)) if same and all(pd.notna(x) for x in nis) else np.nan
        op=r.operating_profit_q; pop=getattr(py,'operating_profit_q',np.nan) if py is not None else np.nan; eq=r.equity_q_end
        if pd.notna(op) and pd.notna(pop) and op>0 and pop<=0 and pd.notna(ni) and ni<0 and pd.notna(eq) and eq>0:
            f=r.fcf_q; pf=getattr(py,'fcf_q',np.nan) if py is not None else np.nan
            rows.append({'year':y,'corp_code':r.corp_code,'company_name':r.company_name,'quarter':r.fiscal_quarter,'op_q':op,'prior_op_q':pop,'ni_ttm':ni,'equity':eq,'fcf_q':f,'fcf_yoy':f-pf if pd.notna(f) and pd.notna(pf) else np.nan})
    return pd.DataFrame(rows)

def securities(x):
    s=pd.read_csv(SEC,dtype=str).fillna('')
    s['fiscal_year_num']=pd.to_numeric(s['fiscal_year'],errors='coerce')
    s=s[s.fiscal_year_num.isin(YEARS)].copy();s['corp_code']=s.corp_code.astype(str).str.zfill(8)
    keep=['fiscal_year_num','corp_code','stock_code','marcap_matched','security_review_status','observed_markets']
    s=s[keep].drop_duplicates(['fiscal_year_num','corp_code'])
    o=x.merge(s,left_on=['year','corp_code'],right_on=['fiscal_year_num','corp_code'],how='left')
    o['stock_code']=o.stock_code.fillna('').astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
    return o

def signals(x):
    us=[]
    for y in YEARS:
        p=UNIDIR/f'korea_dart_historical_universe_{y}.csv'
        u=pd.read_csv(p,dtype=str).fillna('');u['year']=y;u['corp_code']=u.corp_code.astype(str).str.zfill(8)
        if 'is_earliest_corp_period' in u.columns:u=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')].copy()
        else:u=u.sort_values(['corp_code','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','period'],keep='first')
        u=u[u.period.isin(['Q1','H1','Q3','FY'])][['year','corp_code','period','rcept_dt','rcept_no','report_nm']]
        us.append(u)
    u=pd.concat(us,ignore_index=True).rename(columns={'rcept_dt':'signal_date','rcept_no':'signal_receipt_no','report_nm':'signal_report_name'})
    z=x.copy();z['period']=z.quarter.map(SRC_PERIOD)
    o=z.merge(u,on=['year','corp_code','period'],how='left');o['signal_date']=o.signal_date.fillna('')
    return o

def load_marcap():
    ds=[]
    for y in range(2017,2022):
        p=MARCAPDIR/f'marcap-{y}.parquet'
        z=pd.read_parquet(p);z['Date']=pd.to_datetime(z.Date);z['Code']=z.Code.astype(str).str.zfill(6)
        z=z[z.Market.isin(['KOSPI','KOSDAQ'])]
        ds.append(z)
    return pd.concat(ds,ignore_index=True).sort_values(['Code','Date'])

def market(x):
    m=load_marcap(); groups={k:v.sort_values('Date').reset_index(drop=True) for k,v in m.groupby('Code',sort=False)}
    rows=[]
    for r in x.itertuples(index=False):
        d=r._asdict();sd=pd.to_datetime(str(r.signal_date),format='%Y%m%d',errors='coerce');z=groups.get(str(r.stock_code).zfill(6))
        d.update({'mcap_pre_signal':np.nan,'mcap_date':'','entry_date':'','entry_open':np.nan,'adv20':np.nan,'R20':np.nan,'R20_raw':np.nan,'CA_R20':np.nan,'fcf_pct':np.nan,'fcf_yoy_pct':np.nan,'loss_pct':np.nan,'status':'NO_SIGNAL_OR_MARKET'})
        if pd.isna(sd) or z is None or z.empty:rows.append(d);continue
        pre=z[z.Date<sd]
        if len(pre):d['mcap_pre_signal']=float(pre.iloc[-1].Marcap);d['mcap_date']=pre.iloc[-1].Date.date().isoformat()
        elig=z[(z.Date>sd)&(z.Open>0)&(z.Volume>0)&(z.Amount>0)]
        if elig.empty:d['status']='NO_ENTRY';rows.append(d);continue
        e=elig.iloc[0];idx=int(z.index[z.Date.eq(e.Date)][0]);hist=z.iloc[max(0,idx-20):idx]
        d.update({'entry_date':e.Date.date().isoformat(),'entry_open':float(e.Open),'adv20':float(hist.Amount.mean()) if len(hist)==20 else np.nan,'status':'OK'})
        j=idx+19
        if j<len(z):
            path=z.iloc[max(0,idx-1):j+1];stocks=pd.to_numeric(path.Stocks,errors='coerce');rat=(stocks/stocks.shift(1)-1).abs();ca=bool((rat>0.20).fillna(False).any());ret=(float(z.iloc[j].Close)/float(e.Open)-1)*100
            d['R20_raw']=ret;d['CA_R20']=ca;d['R20']=ret if ca is False else np.nan
        mc=d['mcap_pre_signal']
        if pd.notna(mc) and mc>0:
            d['fcf_pct']=float(r.fcf_q)/mc*100 if pd.notna(r.fcf_q) else np.nan
            d['fcf_yoy_pct']=float(r.fcf_yoy)/mc*100 if pd.notna(r.fcf_yoy) else np.nan
            d['loss_pct']=abs(float(r.ni_ttm))/mc*100
        rows.append(d)
    return pd.DataFrame(rows)

def metrics(df):
    q=st(df.R20);q['bootstrap_median_ci95']=bootstrap_median_ci(df.R20);return q

def main():
    x=market(signals(securities(accounting())))
    x.to_csv(OUT,index=False)
    clean=x[(x.security_review_status=='MATCHED_COMMON_CANDIDATE')&(x.status=='OK')].copy()
    clean['mcap_b']=pd.to_numeric(clean.mcap_pre_signal,errors='coerce')/1e9
    grid=[]
    def add(name,d):
        q=metrics(d);q.update({'filter':name});grid.append(q)
    add('BASE',clean)
    for cap in [30,40,50,60,75,100,150]: add(f'MCAP<={cap}B',clean[clean.mcap_b<=cap])
    for cap in [40,50,60,75,100]:
        z=clean[clean.mcap_b<=cap]
        for cur in [0,2,5]:
            for yoy in [0,5,10]: add(f'MCAP<={cap}B_CUR>={cur}_YOY>={yoy}',z[(z.fcf_pct>=cur)&(z.fcf_yoy_pct>=yoy)])
    g=pd.DataFrame(grid);g.to_csv(GRID,index=False)
    yearly={str(y):metrics(clean[clean.year==y]) for y in YEARS}
    yearly_caps={str(y):{} for y in YEARS}
    for y in YEARS:
        for cap in [40,50,60,75,100]:yearly_caps[str(y)][str(cap)]=metrics(clean[(clean.year==y)&(clean.mcap_b<=cap)])
    loo={}
    for holdout in YEARS:
        tr=clean[clean.year!=holdout]
        loo[str(holdout)]={}
        for name in ['MCAP<=50B','MCAP<=50B_CUR>=0_YOY>=5','MCAP<=50B_CUR>=5_YOY>=5','MCAP<=60B_CUR>=0_YOY>=5','MCAP<=75B_CUR>=0_YOY>=5']:
            if name=='MCAP<=50B':d=tr[tr.mcap_b<=50]
            else:
                import re
                mm=re.match(r'MCAP<=(\d+)B_CUR>=(\d+)_YOY>=(\d+)',name);cap,cur,yoy=map(float,mm.groups());d=tr[(tr.mcap_b<=cap)&(tr.fcf_pct>=cur)&(tr.fcf_yoy_pct>=yoy)]
            loo[str(holdout)][name]=metrics(d)
    summary={'development_only':True,'modern_oos_protected':True,'years':YEARS,'accounting_base_a':{str(y):int((x.year==y).sum()) for y in YEARS},'total_accounting_base_a':int(len(x)),'signals_found':int(x.signal_date.astype(bool).sum()),'market_ok':int((x.status=='OK').sum()),'clean_market_ok':int(len(clean)),'ca_r20':int(pd.Series(clean.CA_R20).fillna(False).astype(bool).sum()),'baseline':metrics(clean),'yearly':yearly,'yearly_caps':yearly_caps,'loo':loo,'top_grid_by_min_n':g[g.n>=20].sort_values(['median','n'],ascending=[False,False]).head(20).to_dict('records'),'limitations':['Periodic-report fallback signal from reconstructed historical DART receipt universe; preliminary/earnings disclosure may move signal earlier.','PIT market cap uses last trading-day close strictly before signal; entry uses first tradable open strictly after signal.','Corporate-action contaminated R20 observations are excluded.','Threshold search is Development-only; 2021-2022 Validation and 2023+ OOS are not used here.']}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
