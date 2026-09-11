#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np, pandas as pd, requests
Q=Path('korea_dart_quarterly_2016_2020_recovered.csv')
SEC=Path('korea_historical_security_universe_2015_2020.csv')
MAR='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}; PERIOD={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}

def stats(s):
 s=pd.to_numeric(s,errors='coerce').dropna()
 return {'n':int(len(s)),'median':float(s.median()),'mean':float(s.mean()),'win':float((s>0).mean()),'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean())} if len(s) else {'n':0}

def accounting():
 d=pd.read_csv(Q,dtype={'corp_code':str},low_memory=False); d['business_year']=pd.to_numeric(d.business_year,errors='coerce'); d=d[d.business_year.between(2016,2020)].copy(); d['business_year']=d.business_year.astype(int); d['corp_code']=d.corp_code.astype(str).str.zfill(8); d['qord']=d.fiscal_quarter.map(QORD); d['seq']=d.business_year*4+d.qord; d=d.dropna(subset=['qord']).sort_values(['corp_code','seq']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
 key={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)}; seq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)}; rows=[]
 for r in d[d.business_year.between(2018,2020)].itertuples(index=False):
  y=int(r.business_year); py=key.get((r.corp_code,y-1,r.fiscal_quarter)); four=[seq.get((r.corp_code,s)) for s in range(int(r.seq)-3,int(r.seq)+1)]; exact=all(x is not None for x in four); bases=[str(getattr(x,'statement_basis','') or '') for x in four] if exact else []; same=bool(exact and bases and len(set(bases))==1 and bases[0]); nis=[getattr(x,'net_income_q',np.nan) if x else np.nan for x in four]; ni=float(sum(nis)) if same and all(pd.notna(x) for x in nis) else np.nan; op=r.operating_profit_q; pop=getattr(py,'operating_profit_q',np.nan) if py else np.nan; eq=r.equity_q_end
  if pd.notna(op) and pd.notna(pop) and op>0 and pop<=0 and pd.notna(ni) and ni<0 and pd.notna(eq) and eq>0:
   f=r.fcf_q; pf=getattr(py,'fcf_q',np.nan) if py else np.nan; rows.append({'year':y,'corp_code':r.corp_code,'company_name':r.company_name,'quarter':r.fiscal_quarter,'fcf_q':f,'fcf_yoy':f-pf if pd.notna(f) and pd.notna(pf) else np.nan,'ni_ttm':ni})
 return pd.DataFrame(rows)

def add_security(x):
 s=pd.read_csv(SEC,dtype=str).fillna(''); s['fiscal_year_num']=pd.to_numeric(s.fiscal_year,errors='coerce'); s['corp_code']=s.corp_code.astype(str).str.zfill(8); s=s[['fiscal_year_num','corp_code','stock_code','security_review_status']].drop_duplicates(['fiscal_year_num','corp_code']); return x.merge(s,left_on=['year','corp_code'],right_on=['fiscal_year_num','corp_code'],how='left')

def add_signal(x):
 out=[]
 for y,g in x.groupby('year'):
  p=Path(f'korea_dart_historical_universe_{y}.csv')
  if not p.exists(): continue
  u=pd.read_csv(p,dtype=str).fillna(''); u['corp_code']=u.corp_code.astype(str).str.zfill(8)
  if 'is_earliest_corp_period' in u: u=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')]
  else: u=u.sort_values(['corp_code','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','period'])
  u=u[['corp_code','period','rcept_dt']].rename(columns={'rcept_dt':'signal_date'}); gg=g.copy(); gg['period']=gg.quarter.map(PERIOD); out.append(gg.merge(u,on=['corp_code','period'],how='left'))
 return pd.concat(out,ignore_index=True) if out else x.assign(signal_date='')

def prices(years):
 ds=[]
 for y in sorted(set(years)|{max(years)+1}):
  p=Path(f'marcap-{y}.parquet')
  if not p.exists(): r=requests.get(MAR.format(year=y),timeout=180); r.raise_for_status(); p.write_bytes(r.content)
  z=pd.read_parquet(p); z['Date']=pd.to_datetime(z.Date); z['Code']=z.Code.astype(str).str.zfill(6); ds.append(z)
 return pd.concat(ds,ignore_index=True)

def market(x):
 m=prices(x.year.unique().tolist()); rows=[]
 for r in x.itertuples(index=False):
  d=r._asdict(); sd=pd.to_datetime(str(getattr(r,'signal_date','')),format='%Y%m%d',errors='coerce'); code=str(getattr(r,'stock_code','')).replace('.0','').zfill(6); z=m[(m.Code==code)&m.Market.isin(['KOSPI','KOSDAQ'])].sort_values('Date').reset_index(drop=True)
  if pd.isna(sd) or z.empty: d['status']='NO_SIGNAL_OR_MARKET'; rows.append(d); continue
  pre=z[z.Date<sd]; d['mcap']=float(pre.iloc[-1].Marcap) if len(pre) else np.nan; elig=z[(z.Date>sd)&(z.Open>0)&(z.Volume>0)&(z.Amount>0)]
  if elig.empty: d['status']='NO_ENTRY'; rows.append(d); continue
  e=elig.iloc[0]; idx=int(z.index[z.Date.eq(e.Date)][0]); j=idx+19; d['status']='OK'; d['entry_date']=e.Date.date().isoformat(); d['R20']=np.nan; d['CA_R20']=np.nan
  if j<len(z):
   path=z.iloc[max(0,idx-1):j+1]; rat=(pd.to_numeric(path.Stocks,errors='coerce')/pd.to_numeric(path.Stocks,errors='coerce').shift(1)-1).abs(); ca=bool((rat>0.20).fillna(False).any()); ret=(float(z.iloc[j].Close)/float(e.Open)-1)*100; d['CA_R20']=ca; d['R20']=ret if not ca else np.nan
  mc=d.get('mcap',np.nan); d['fcf_pct']=float(r.fcf_q)/mc*100 if pd.notna(r.fcf_q) and pd.notna(mc) and mc>0 else np.nan; d['fcf_yoy_pct']=float(r.fcf_yoy)/mc*100 if pd.notna(r.fcf_yoy) and pd.notna(mc) and mc>0 else np.nan; rows.append(d)
 return pd.DataFrame(rows)

def main():
 x=market(add_signal(add_security(accounting()))); clean=x[(x.security_review_status=='MATCHED_COMMON_CANDIDATE')&(x.status=='OK')&x.R20.notna()].copy(); clean.to_csv('korea_development_2018_2020_events.csv',index=False)
 mcap_grid=[3e10,4e10,5e10,6e10,8e10,1e11,1.5e11,2e11]; fcf_grid=[0,2.5,5,7.5,10]; yoy_grid=[0,5,10,12.5,15]
 grids=[]
 for mc in mcap_grid:
  for f in fcf_grid:
   for yy in yoy_grid:
    z=clean[(clean.mcap<=mc)&(clean.fcf_pct>=f)&(clean.fcf_yoy_pct>=yy)]
    if len(z)>=10:
     st=stats(z.R20); grids.append({'mcap_cap':mc,'fcf_min':f,'fcf_yoy_min':yy,**st,'years':int(z.year.nunique())})
 gd=pd.DataFrame(grids).sort_values(['years','median','win','n'],ascending=[False,False,False,False]); gd.to_csv('korea_development_threshold_grid.csv',index=False)
 yearly=[]
 for y,z in clean.groupby('year'): yearly.append({'year':int(y),**stats(z.R20),'base_n':len(z)})
 # LOO score: choose top rule on training years by median with min 5 obs/year, evaluate held-out
 loo=[]
 for hold in sorted(clean.year.unique()):
  tr=clean[clean.year!=hold]; te=clean[clean.year==hold]; cand=[]
  for mc in mcap_grid:
   for f in fcf_grid:
    for yy in yoy_grid:
     z=tr[(tr.mcap<=mc)&(tr.fcf_pct>=f)&(tr.fcf_yoy_pct>=yy)]
     counts=z.groupby('year').size()
     if len(counts)==tr.year.nunique() and counts.min()>=5 and len(z)>=15:
      s=stats(z.R20); cand.append((s['median'],s['win'],len(z),mc,f,yy))
  if cand:
   best=max(cand); _,_,_,mc,f,yy=best; z=te[(te.mcap<=mc)&(te.fcf_pct>=f)&(te.fcf_yoy_pct>=yy)]; loo.append({'holdout':int(hold),'mcap_cap':mc,'fcf_min':f,'fcf_yoy_min':yy,**stats(z.R20)})
 summary={'development_only':True,'oos_2023_plus_untouched':True,'validation_2021_2022_unused':True,'accounting_base':int(len(x)),'clean_events':int(len(clean)),'yearly':yearly,'top_grid':gd.head(20).to_dict('records'),'loo':loo}
 Path('korea_development_multiyear_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
