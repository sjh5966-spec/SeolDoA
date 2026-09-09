#!/usr/bin/env python3
"""Validate and acquire KRX-free historical Korean daily market data from FinanceData/marcap.

Development accounting research support only.
- Downloads only 2015-2020 annual parquet files.
- Does not touch 2023+ modern OOS.
- Validates OHLCV, traded amount, market cap, shares outstanding and market fields.
- Cross-checks against any reconstructed DART historical universe files already present.
- Raw parquets are kept as workflow artifacts, not committed.

The upstream dataset states it is reconstructed from KRX daily all-security market-cap data.
It is a research data source, not an official KRX API entitlement.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import pandas as pd
import requests

YEARS=range(2015,2021)
BASE='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
RAW=Path('korea_marcap_raw_2015_2020')
SUMMARY=Path('korea_marcap_development_probe_summary.json')
CROSS=Path('korea_marcap_dart_crosscheck_2015_2020.csv')
EXPECTED_CORE=['Date','Code','Name','Open','High','Low','Close','Volume','Amount','Marcap','Stocks']

def download(session, year):
    RAW.mkdir(exist_ok=True)
    p=RAW/f'marcap-{year}.parquet'
    if p.exists() and p.stat().st_size>100000:
        return p,'cached'
    u=BASE.format(year=year)
    with session.get(u,stream=True,timeout=180) as r:
        r.raise_for_status()
        with p.open('wb') as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)
    return p,'downloaded'

def norm_code(s):
    return s.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)

def main():
    s=requests.Session(); s.headers.update({'User-Agent':'SeolDoA-marcap-development-probe/1.0'})
    yearly=[]; cross=[]; schema_union=set(); statuses=Counter()
    all_frames={}
    for y in YEARS:
        p,st=download(s,y); statuses[st]+=1
        d=pd.read_parquet(p)
        if 'Date' not in d.columns:
            if isinstance(d.index,pd.DatetimeIndex): d=d.reset_index()
            elif d.index.name=='Date': d=d.reset_index()
        missing=[c for c in EXPECTED_CORE if c not in d.columns]
        if missing: raise RuntimeError(f'{y} missing required columns: {missing}; got={list(d.columns)}')
        d['Code']=norm_code(d['Code'])
        d['Date']=pd.to_datetime(d['Date'],errors='coerce')
        schema_union.update(d.columns)
        all_frames[y]=d
        market_col='Market' if 'Market' in d.columns else None
        market_counts=d[market_col].astype(str).value_counts().to_dict() if market_col else {}
        dates=d['Date'].dropna()
        zero_vol=(pd.to_numeric(d['Volume'],errors='coerce').fillna(0)<=0)
        yearly.append({
            'year':y,'rows':int(len(d)),'unique_codes':int(d['Code'].nunique()),
            'first_date':str(dates.min().date()) if len(dates) else None,'last_date':str(dates.max().date()) if len(dates) else None,
            'bytes':int(p.stat().st_size),'market_counts':market_counts,
            'missing_open':int(pd.to_numeric(d['Open'],errors='coerce').isna().sum()),
            'missing_close':int(pd.to_numeric(d['Close'],errors='coerce').isna().sum()),
            'missing_amount':int(pd.to_numeric(d['Amount'],errors='coerce').isna().sum()),
            'missing_marcap':int(pd.to_numeric(d['Marcap'],errors='coerce').isna().sum()),
            'zero_or_missing_volume_rows':int(zero_vol.sum()),
            'nonpositive_marcap_rows':int((pd.to_numeric(d['Marcap'],errors='coerce').fillna(0)<=0).sum()),
        })
        up=Path(f'korea_dart_historical_universe_{y}.csv')
        if up.exists():
            u=pd.read_csv(up,dtype=str).fillna('')
            # One security code per DART corp-period row; evaluate code-level historical coverage.
            uc=set(norm_code(u.loc[u['stock_code'].str.strip().ne(''),'stock_code'])) if 'stock_code' in u else set()
            mc=set(d['Code'])
            matched=uc & mc
            cross.append({'year':y,'dart_stock_codes':len(uc),'marcap_codes':len(mc),'matched_codes':len(matched),
                          'coverage_pct':round(100*len(matched)/len(uc),3) if uc else None,
                          'dart_only_codes':len(uc-mc),'marcap_only_codes':len(mc-uc)})
    pd.DataFrame(cross).to_csv(CROSS,index=False)
    # Detect codes that existed in Development but disappeared before 2020: evidence that the source retains historical/delisted observations.
    codes_by_year={y:set(d['Code']) for y,d in all_frames.items()}
    early=set().union(*(codes_by_year[y] for y in range(2015,2020)))
    disappeared=early-codes_by_year[2020]
    out={
      'checked_at_utc':datetime.now(timezone.utc).isoformat(),
      'research_stage':'development_krx_free_historical_market_data_probe',
      'modern_oos_protected':True,
      'source':'FinanceData/marcap GitHub annual parquet files',
      'source_years':[2015,2016,2017,2018,2019,2020],
      'download_status_counts':dict(statuses),
      'schema_columns':sorted(schema_union),
      'yearly':yearly,
      'dart_crosscheck':cross,
      'codes_seen_2015_2019_but_absent_2020':len(disappeared),
      'example_disappeared_codes':sorted(disappeared)[:25],
      'total_raw_bytes':sum(x['bytes'] for x in yearly),
      'usable_for':['next-trading-day open','R5/R10/R20/R60/R120 price path','ADV20 traded value','PIT daily market cap','shares outstanding','zero-volume diagnostics'],
      'limitations':['third-party reconstruction sourced from KRX rather than official API','security-type filtering still must be applied','corporate actions and raw-vs-adjusted price behavior require explicit validation before returns are frozen'],
    }
    SUMMARY.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
