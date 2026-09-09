#!/usr/bin/env python3
"""Development-only provisional market analysis for bulk-discovered Base A candidates.

Signal is the earliest periodic receipt for the fiscal quarter, NOT yet the final earliest-public signal.
This is a conservative/late-entry diagnostic while preliminary disclosure confirmation is pending.
Bulk accounting values are current snapshots, not PIT-confirmed. Results MUST NOT be frozen as strategy evidence.
"""
from __future__ import annotations
import glob,json,re
from pathlib import Path
from datetime import datetime,timezone
import numpy as np,pandas as pd,requests

SRC=Path('korea_turnaround_bulk_base_a_2017_2020.csv')
OUT=Path('korea_periodic_fallback_market_analysis_v1.csv');SUM=Path('korea_periodic_fallback_market_analysis_v1_summary.json')
PER={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}
MAR='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'

def code(x):
 m=re.search(r'(\d{6})',str(x or ''));return m.group(1) if m else ''
def ordinary_name(n):
 s=str(n or '').replace(' ','').upper()
 bad=('스팩','SPAC','리츠','REIT','ETF','ETN')
 if any(x in s for x in bad):return False
 if re.search(r'우(?:B|C|선주|\d*)?$',s):return False
 return True
def pct(a,b):return (b/a-1)*100 if a and b and a>0 else None
def main():
 c=pd.read_csv(SRC,dtype={'corp_code':str,'stock_code':str});c['corp_code']=c.corp_code.astype(str).str.zfill(8);c['stock_code']=c.stock_code.map(code)
 # earliest periodic receipts from historical DART universe
 us=[]
 for f in sorted(glob.glob('korea_dart_historical_universe_20??.csv')):
  d=pd.read_csv(f,dtype=str).fillna('');d=d[d.target_year.astype(int).between(2016,2020)]
  if 'is_earliest_corp_period' in d:d=d[d.is_earliest_corp_period.astype(str).str.lower().eq('true')]
  us.append(d)
 u=pd.concat(us,ignore_index=True);u['corp_code']=u.corp_code.astype(str).str.zfill(8)
 key={(r.corp_code,int(r.target_year),str(r.period)):r for r in u.itertuples(index=False)}
 years=set();base=[]
 for r in c.itertuples(index=False):
  x=key.get((r.corp_code,int(r.business_year),PER[str(r.fiscal_quarter)]))
  if x is None:continue
  sd=pd.to_datetime(str(x.rcept_dt),format='%Y%m%d',errors='coerce')
  if pd.isna(sd) or not (pd.Timestamp('2015-01-01')<=sd<=pd.Timestamp('2020-12-31')):continue
  years.update([sd.year,sd.year+1]);base.append((r,x,sd))
 session=requests.Session();session.headers['User-Agent']='SeolDoA-periodic-fallback-market/1.0';md={}
 for y in sorted(years):
  if y>2021:continue
  d=pd.read_parquet(MAR.format(year=y));d['Date']=pd.to_datetime(d.Date);d['Code']=d.Code.astype(str).str.zfill(6);md[y]=d
 allm=pd.concat(md.values(),ignore_index=True).sort_values(['Code','Date']) if md else pd.DataFrame()
 rows=[]
 for r,x,sd in base:
  sc=code(r.stock_code) or code(getattr(x,'stock_code',''));g=allm[(allm.Code==sc)&allm.Market.isin(['KOSPI','KOSDAQ'])].sort_values('Date') if sc else pd.DataFrame()
  rec={'corp_code':r.corp_code,'company_name':r.company_name,'stock_code':sc,'business_year':int(r.business_year),'fiscal_quarter':r.fiscal_quarter,'periodic_receipt_no':x.rcept_no,'periodic_signal_date':sd.date().isoformat(),'statement_basis':r.statement_basis,'net_income_ttm':r.net_income_ttm,'fcf_q':r.fcf_q,'fcf_yoy_improvement':r.fcf_yoy_improvement,'ordinary_name_candidate':ordinary_name(r.company_name),'signal_status':'PERIODIC_FALLBACK_NOT_EARLIEST_CONFIRMED'}
  if g.empty:rec['status']='NO_MARKET_MATCH';rows.append(rec);continue
  pre=g[g.Date<=sd];post=g[(g.Date>sd)&(g.Open>0)&(g.Volume>0)&(g.Amount>0)]
  if pre.empty or post.empty:rec['status']='NO_PREENTRY_OR_ENTRY';rows.append(rec);continue
  pe=pre.iloc[-1];en=post.iloc[0];idx=g.index.get_loc(en.name);path=g.iloc[idx:idx+121].copy();hist=g[g.Date<en.Date].tail(20)
  rec.update({'status':'OK','market':en.Market,'preentry_mcap':float(pe.Marcap),'preentry_mcap_date':pe.Date.date().isoformat(),'entry_date':en.Date.date().isoformat(),'entry_open':float(en.Open),'adv20_amount':float(hist.Amount.mean()) if len(hist)==20 else None,'median_amount20':float(hist.Amount.median()) if len(hist)==20 else None,'adv20_complete':len(hist)==20})
  rec['fcf_to_mcap']=float(r.fcf_q)/rec['preentry_mcap'] if pd.notna(r.fcf_q) and rec['preentry_mcap']>0 else None;rec['fcf_yoy_improvement_to_mcap']=float(r.fcf_yoy_improvement)/rec['preentry_mcap'] if pd.notna(r.fcf_yoy_improvement) and rec['preentry_mcap']>0 else None;rec['abs_ttm_loss_to_mcap']=abs(float(r.net_income_ttm))/rec['preentry_mcap'] if pd.notna(r.net_income_ttm) and rec['preentry_mcap']>0 else None
  sh0=float(en.Stocks) if pd.notna(en.Stocks) else None;rec['shares_change_gt20pct_R20']=False
  if sh0 and len(path):rec['shares_change_gt20pct_R20']=bool(((path.head(21).Stocks.astype(float)/sh0-1).abs()>0.20).any())
  for h in (5,10,20,60,120):
   rec[f'R{h}']=pct(float(en.Open),float(path.iloc[h].Close)) if len(path)>h and float(path.iloc[h].Close)>0 else None
  if len(path)>20:
   rec['MFE20']=float(path.iloc[:21].High.max()/float(en.Open)-1)*100;rec['MAE20']=float(path.iloc[:21].Low.min()/float(en.Open)-1)*100
  rows.append(rec)
 o=pd.DataFrame(rows);o.to_csv(OUT,index=False)
 valid=o[(o.status=='OK')&o.ordinary_name_candidate.eq(True)&o.R20.notna()&~o.shares_change_gt20pct_R20.astype(bool)].copy() if len(o) else pd.DataFrame()
 def stats(z):
  if z.empty:return {'n':0}
  a=z.R20.astype(float).to_numpy();rng=np.random.default_rng(5966);med=[]
  if len(a):
   for _ in range(3000):med.append(float(np.median(rng.choice(a,len(a),replace=True))))
  return {'n':len(a),'median_R20':float(np.median(a)),'mean_R20':float(np.mean(a)),'win_rate':float(np.mean(a>0)),'ge20_rate':float(np.mean(a>=20)),'le_minus20_rate':float(np.mean(a<=-20)),'p10':float(np.quantile(a,.1)),'p25':float(np.quantile(a,.25)),'p75':float(np.quantile(a,.75)),'p90':float(np.quantile(a,.9)),'median_bootstrap_ci95':[float(np.quantile(med,.025)),float(np.quantile(med,.975))]}
 sm={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_periodic_fallback_market_diagnostic','modern_oos_protected':True,'bulk_candidates_input':len(c),'events_with_development_periodic_signal':len(base),'market_ok':int((o.status=='OK').sum()) if len(o) else 0,'primary_provisional_eligible':len(valid),'periodic_fallback_stats':stats(valid),'by_signal_year':{str(y):stats(g) for y,g in valid.groupby(pd.to_datetime(valid.periodic_signal_date).dt.year)} if len(valid) else {},'by_market':{str(k):stats(g) for k,g in valid.groupby('market')} if len(valid) else {},'critical_limitation':'NOT final strategy evidence: periodic receipt may be later than an earlier preliminary disclosure, and bulk accounting may reflect later corrections. Corporate-action-flagged R20 paths are excluded. PIT candidate confirmation is required.'}
 SUM.write_text(json.dumps(sm,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(sm,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
