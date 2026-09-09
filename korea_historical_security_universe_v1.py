#!/usr/bin/env python3
"""Build a Development historical Korean security-universe bridge from DART + FinanceData/marcap.
2015-2020 only. No returns and no OOS.

Purpose:
- tie DART corp_code to the historically traded six-digit security code,
- verify KOSPI/KOSDAQ presence in each fiscal year,
- record observed trading span and liquidity/mcap diagnostics,
- flag non-common-stock-like categories for explicit exclusion review.
"""
from __future__ import annotations
import json,re
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
import requests

SEED=Path('korea_dart_historical_seed_2015_2020.csv')
RAW=Path('korea_marcap_raw_2015_2020')
BASE='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
OUT=Path('korea_historical_security_universe_2015_2020.csv')
SUM=Path('korea_historical_security_universe_2015_2020_summary.json')

def normcode(v,n=6):
    s=str(v or '').replace('.0','').strip();return s.zfill(n) if s else ''

def get(y):
    RAW.mkdir(exist_ok=True);p=RAW/f'marcap-{y}.parquet'
    if not p.exists():
        r=requests.get(BASE.format(year=y),timeout=180);r.raise_for_status();p.write_bytes(r.content)
    d=pd.read_parquet(p)
    if 'Date' not in d.columns:d=d.reset_index()
    d['Date']=pd.to_datetime(d.Date);d['Code']=d.Code.map(normcode)
    return d

def name_flags(name):
    n=re.sub(r'\s+','',str(name or '')).upper()
    return {
      'flag_spac':bool(re.search(r'스팩|기업인수목적',n)),
      'flag_reit':bool(re.search(r'리츠|부동산투자회사',n)),
      'flag_fund_etf_etn':bool(re.search(r'ETF|ETN|펀드|인덱스펀드',n)),
      'flag_preferred_name':bool(re.search(r'우$|우B$|우C$|우선주',n)),
    }

def main():
    s=pd.read_csv(SEED,dtype=str).fillna('');s=s[s.fiscal_year.astype(int).between(2015,2020)].copy()
    rows=[]
    for y in range(2015,2021):
        m=get(y);m=m[m.Market.isin(['KOSPI','KOSDAQ'])].copy();m['Code']=m.Code.map(normcode)
        for r in s[s.fiscal_year.astype(int).eq(y)].itertuples(index=False):
            code=normcode(getattr(r,'stock_code',''));z=m[m.Code.eq(code)] if code else m.iloc[0:0]
            markets=sorted(z.Market.dropna().astype(str).unique().tolist()) if len(z) else []
            names=sorted(z.Name.dropna().astype(str).unique().tolist()) if len(z) else []
            amount=pd.to_numeric(z.Amount,errors='coerce') if len(z) else pd.Series(dtype=float)
            mar=pd.to_numeric(z.Marcap,errors='coerce') if len(z) else pd.Series(dtype=float)
            vol=pd.to_numeric(z.Volume,errors='coerce') if len(z) else pd.Series(dtype=float)
            nm=names[-1] if names else getattr(r,'company_name','')
            flags=name_flags(nm)
            rows.append({
              'fiscal_year':y,'corp_code':normcode(getattr(r,'corp_code',''),8),'stock_code':code,'company_name':getattr(r,'company_name',''),
              'dart_corp_cls':getattr(r,'corp_cls',''),'marcap_matched':bool(len(z)),'observed_markets':'|'.join(markets),'observed_names':'|'.join(names),
              'first_trade_date':z.Date.min().date().isoformat() if len(z) else '', 'last_trade_date':z.Date.max().date().isoformat() if len(z) else '',
              'observed_trading_rows':int(len(z)),'positive_volume_days':int((vol>0).sum()) if len(z) else 0,
              'median_daily_amount_krw':float(amount.median()) if len(amount) else None,'median_marcap_raw':float(mar.median()) if len(mar) else None,
              'min_marcap_raw':float(mar.min()) if len(mar) else None,'max_marcap_raw':float(mar.max()) if len(mar) else None,
              **flags,'security_review_status':'EXCLUDE_FLAGGED' if any(flags.values()) else ('MATCHED_COMMON_CANDIDATE' if len(z) else 'UNMATCHED_REVIEW'),
              'modern_oos_protected':True})
    o=pd.DataFrame(rows);o.to_csv(OUT,index=False)
    summ={
      'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_historical_security_universe_bridge','modern_oos_protected':True,
      'rows':int(len(o)),'matched_rows':int(o.marcap_matched.sum()),'matched_pct':round(100*o.marcap_matched.mean(),3),
      'unmatched_rows':int((~o.marcap_matched).sum()),'unique_corps':int(o.corp_code.nunique()),
      'status_counts':o.security_review_status.value_counts().to_dict(),
      'flag_counts':{c:int(o[c].sum()) for c in ['flag_spac','flag_reit','flag_fund_etf_etn','flag_preferred_name']},
      'market_observation_counts':o.observed_markets.value_counts().head(10).to_dict(),
      'important_limitation':'Name-based flags are review aids, not a final legal/security-type classifier. Event-date tradability and PIT market cap must be joined on the signal/entry date.'}
    SUM.write_text(json.dumps(summ,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summ,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
