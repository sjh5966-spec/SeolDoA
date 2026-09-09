#!/usr/bin/env python3
"""Acquire reproducible Korean daily market data for Development+Validation only (2015-2022).
Hard stop before 2023 modern OOS. Raw files are artifacts, compact manifest is committed.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import pandas as pd
import requests

YEARS=range(2015,2023)
BASE='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
RAW=Path('korea_marcap_raw_2015_2022')
MAN=Path('korea_marcap_pre_oos_manifest_2015_2022.csv')
SUM=Path('korea_marcap_pre_oos_manifest_2015_2022_summary.json')
REQ=['Date','Code','Name','Open','High','Low','Close','Volume','Amount','Marcap','Stocks','Market']

def main():
    RAW.mkdir(exist_ok=True); rows=[]
    session=requests.Session();session.headers['User-Agent']='SeolDoA-pre-oos-marcap/1.0'
    for y in YEARS:
        if y>=2023: raise RuntimeError('OOS guard')
        p=RAW/f'marcap-{y}.parquet'
        if not p.exists():
            with session.get(BASE.format(year=y),stream=True,timeout=180) as r:
                r.raise_for_status()
                with p.open('wb') as f:
                    for c in r.iter_content(1024*1024):
                        if c:f.write(c)
        h=hashlib.sha256(p.read_bytes()).hexdigest();d=pd.read_parquet(p)
        if 'Date' not in d.columns:d=d.reset_index()
        miss=[c for c in REQ if c not in d.columns]
        if miss:raise RuntimeError(f'{y} schema missing {miss}')
        dt=pd.to_datetime(d.Date,errors='coerce')
        rows.append({'year':y,'rows':len(d),'unique_codes':d.Code.astype(str).nunique(),'first_date':dt.min().date().isoformat(),'last_date':dt.max().date().isoformat(),'bytes':p.stat().st_size,'sha256':h,'kospi_rows':int((d.Market=='KOSPI').sum()),'kosdaq_rows':int((d.Market=='KOSDAQ').sum()),'konex_rows':int((d.Market=='KONEX').sum())})
    pd.DataFrame(rows).to_csv(MAN,index=False)
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'pre_oos_market_data_acquisition','development_years':[2015,2016,2017,2018,2019,2020],'validation_years':[2021,2022],'modern_oos_protected':True,'oos_start_year':2023,'files':len(rows),'total_rows':int(sum(r['rows'] for r in rows)),'total_bytes':int(sum(r['bytes'] for r in rows)),'source':'FinanceData/marcap annual parquet snapshots sourced from KRX all-security daily data','note':'No strategy returns or 2023+ data accessed.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
