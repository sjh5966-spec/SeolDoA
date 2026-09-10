#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path
import numpy as np
import pandas as pd
import requests

QFILE=Path('korea_dart_quarterly_2016_2020_full.csv')
SEC=Path('korea_historical_security_universe_2015_2020.csv')
UNI=Path('korea_dart_historical_universe_2019.csv')
OUT=Path('korea_2019_periodic_fallback_events.csv')
SUM=Path('korea_2019_periodic_fallback_summary.json')
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}; SRC_PERIOD={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}

def accounting():
 d=pd.read_csv(QFILE,dtype={'corp_code':str},low_memory=False);d=d[d.business_year.astype(int).isin([2018,2019])].copy();d['corp_code']=d.corp_code.astype(str).str.zfill(8);d['qord']=d.fiscal_quarter.map(QORD);d['seq']=d.business_year.astype(int)*4+d.qord.astype(int);d=d.sort_values(['corp_code','seq']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
 key={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)};seq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)};rows=[]
 for r in d[d.business_year.astype(int).eq(2019)].itertuples(index=False):
  py=key.get((r.corp_code,2018,r.fiscal_quarter));four=[seq.get((r.corp_code,s)) for s in range(int(r.seq)-3,int(r.seq)+1)];exact=all(x is not None for x in four);bases=[str(getattr(x,'statement_basis','') or '') for x in four] if exact else [];same=bool(exact and bases and len(set(bases))==1 and bases[0]);nis=[getattr(x,'net_income_q',np.nan) if x is not None else np.nan for x in four];ni=float(sum(nis)) if same and all(pd.notna(x) for x in nis) else np.nan;op=r.operating_profit_q;pop=getattr(py,'operating_profit_q',np.nan) if py is not None else np.nan;eq=r.equity_q_end
  if pd.notna(op) and pd.notna(pop) and op>0 and pop<=0 and pd.notna(ni) and ni<0 and pd.notna(eq) and eq>0:
   f=r.fcf_q;pf=getattr(py,'fcf_q',np.nan) if py is not None else np.nan;rows.append({'corp_code':r.corp_code,'company_name':r.company_name,'quarter':r.fiscal_quarter,'op_q':op,'prior_op_q':pop,'ni_ttm':ni,'equity':eq,'fcf_q':f,'fcf_yoy':f-pf if pd.notna(f) and pd.notna(pf) else np.nan})
 return pd.DataFrame(rows)

def securities(x):
 s=pd.read_csv(SEC,dtype=str).fillna('');s=s[pd.to_numeric(s['fiscal_year'],errors='coerce').eq(2019)].copy();s['corp_code']=s.corp_code.astype(str).str.zfill(8);s=s[['corp_code','stock_code','marcap_matched','security_review_status','observed_markets']].drop_duplicates('corp_code');o=x.merge(s,on='corp_code',how='left');o['stock_code']=o.stock_code.fillna('').astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6);return o

def signals(x):
 u=pd.read_csv(UNI,dtype=str).fillna('');u['corp_code']=u.corp_code.astype(str).str.zfill(8)
 if 'is_earliest_corp_period' in u.columns:u=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')].copy()
 else:u=u.sort_values(['corp_code','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','period'],keep='first')
 u=u[u.period.isin(['Q1','H1','Q3','FY'])][['corp_code','period','rcept_dt','rcept_no','report_nm']].copy();u=u.rename(columns={'rcept_dt':'signal_date','rcept_no':'signal_receipt_no','report_nm':'signal_report_name'})
 x=x.copy();x['period']=x.quarter.map(SRC_PERIOD);o=x.merge(u,on=['corp_code','period'],how='left');o['signal_date']=o.signal_date.fillna('');return o

def marcap():
 ds=[]
 for y in (2019,2020):
  p=Path(f'marcap-{y}.parquet')
  if not p.exists():r=requests.get(MARCAP.format(year=y),timeout=180);r.raise_for_status();p.write_bytes(r.content)
  z=pd.read_parquet(p);z['Date']=pd.to_datetime(z.Date);z['Code']=z.Code.astype(str).str.zfill(6);ds.append(z)
 return pd.concat(ds,ignore_index=True).sort_values(['Code','Date'])

def market(x):
 m=marcap();rows=[]
 defaults={'mcap_pre_signal':np.nan,'mcap_date':'','entry_date':'','entry_open':np.nan,'adv20':np.nan,'R5':np.nan,'R10':np.nan,'R20':np.nan,'R60':np.nan,'R120':np.nan,'R5_raw':np.nan,'R10_raw':np.nan,'R20_raw':np.nan,'R60_raw':np.nan,'R120_raw':np.nan,'CA_R5':np.nan,'CA_R10':np.nan,'CA_R20':np.nan,'CA_R60':np.nan,'CA_R120':np.nan,'MFE20':np.nan,'MAE20':np.nan,'fcf_pct':np.nan,'fcf_yoy_pct':np.nan,'loss_pct':np.nan}
 for r in x.itertuples(index=False):
  d={**r._asdict(),**defaults};sd=pd.to_datetime(str(r.signal_date),format='%Y%m%d',errors='coerce');code=str(r.stock_code).zfill(6);z=m[(m.Code==code)&(m.Market.isin(['KOSPI','KOSDAQ']))].sort_values('Date').reset_index(drop=True)
  if pd.isna(sd) or z.empty:d['status']='NO_SIGNAL_OR_MARKET';rows.append(d);continue
  pre=z[z.Date<sd];d['mcap_pre_signal']=float(pre.iloc[-1].Marcap) if len(pre) else np.nan;d['mcap_date']=pre.iloc[-1].Date.date().isoformat() if len(pre) else ''
  elig=z[(z.Date>sd)&(z.Open>0)&(z.Volume>0)&(z.Amount>0)]
  if elig.empty:d['status']='NO_ENTRY';rows.append(d);continue
  e=elig.iloc[0];idx=int(z.index[z.Date.eq(e.Date)][0]);hist=z.iloc[max(0,idx-20):idx];d.update({'entry_date':e.Date.date().isoformat(),'entry_open':float(e.Open),'adv20':float(hist.Amount.mean()) if len(hist)==20 else np.nan,'status':'OK'})
  for h in (5,10,20,60,120):
   j=idx+h-1;ret=np.nan;ca=np.nan
   if j<len(z):
    path=z.iloc[max(0,idx-1):j+1];rat=(pd.to_numeric(path.Stocks,errors='coerce')/pd.to_numeric(path.Stocks,errors='coerce').shift(1)-1).abs();ca=bool((rat>0.20).fillna(False).any());ret=(float(z.iloc[j].Close)/float(e.Open)-1)*100
   d[f'R{h}_raw']=ret;d[f'CA_R{h}']=ca;d[f'R{h}']=ret if pd.notna(ret) and ca is False else np.nan
  if idx+19<len(z) and d.get('CA_R20') is False:
   pth=z.iloc[idx:idx+20];d['MFE20']=(float(pth.High.max())/float(e.Open)-1)*100;d['MAE20']=(float(pth.Low.min())/float(e.Open)-1)*100
  mc=d.get('mcap_pre_signal',np.nan);d['fcf_pct']=float(r.fcf_q)/mc*100 if pd.notna(r.fcf_q) and pd.notna(mc) and mc>0 else np.nan;d['fcf_yoy_pct']=float(r.fcf_yoy)/mc*100 if pd.notna(r.fcf_yoy) and pd.notna(mc) and mc>0 else np.nan;d['loss_pct']=abs(float(r.ni_ttm))/mc*100 if pd.notna(mc) and mc>0 else np.nan;rows.append(d)
 return pd.DataFrame(rows)

def st(s):
 s=pd.to_numeric(s,errors='coerce').dropna();return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win':float((s>0).mean()),'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean()),'p10':float(s.quantile(.1)),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75)),'p90':float(s.quantile(.9))} if len(s) else {'n':0}

def main():
 x=accounting();print('base',len(x));x=securities(x);print('matched security',int(x.marcap_matched.astype(str).str.lower().eq('true').sum()));x=signals(x);print('signals',int(x.signal_date.astype(bool).sum()));x=market(x);x.to_csv(OUT,index=False);mc=pd.to_numeric(x.mcap_pre_signal,errors='coerce').dropna();clean=x[x.security_review_status.eq('MATCHED_COMMON_CANDIDATE')].copy();s={'development_only':True,'modern_oos_protected':True,'year':2019,'accounting_base_a':int(len(x)),'matched_common_candidate':int((x.security_review_status=='MATCHED_COMMON_CANDIDATE').sum()),'excluded_flagged':int((x.security_review_status=='EXCLUDE_FLAGGED').sum()),'signals_found':int(x.signal_date.astype(bool).sum()),'market_ok':int((x.status=='OK').sum()),'research_clean_market_ok':int(((x.status=='OK')&(x.security_review_status=='MATCHED_COMMON_CANDIDATE')).sum()),'r20':st(clean.R20),'r5':st(clean.R5),'r10':st(clean.R10),'r60':st(clean.R60),'r120':st(clean.R120),'mcap_krw':{'n':int(len(mc)),'p10':float(mc.quantile(.1)) if len(mc) else None,'p25':float(mc.quantile(.25)) if len(mc) else None,'median':float(mc.median()) if len(mc) else None,'p75':float(mc.quantile(.75)) if len(mc) else None,'p90':float(mc.quantile(.9)) if len(mc) else None},'fcf_pct':st(clean.fcf_pct),'fcf_yoy_pct':st(clean.fcf_yoy_pct),'loss_pct':st(clean.loss_pct),'ca_r20':int(pd.Series(clean.CA_R20).fillna(False).astype(bool).sum()),'limitation':'Periodic-report fallback signal from the previously reconstructed historical DART receipt universe; no new DART API signal calls. Preliminary/earnings disclosures may move signal earlier. Directional Development evidence only, not frozen efficacy. PIT mcap is last trading-day close strictly before signal; entry is first tradable open strictly after signal. 2023+ OOS untouched.'};SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2));print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
