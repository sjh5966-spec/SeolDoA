#!/usr/bin/env python3
"""Integrity and corporate-action diagnostics for FinanceData/marcap Development data.
2015-2020 only. No OOS. This does not alter prices or create strategy returns.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import requests

YEARS=range(2015,2021)
BASE='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
RAW=Path('korea_marcap_raw_2015_2020')
OUT=Path('korea_marcap_quality_v1_summary.json')
ACTIONS=Path('korea_marcap_corporate_action_flags_2015_2020.csv')

def get(y):
    RAW.mkdir(exist_ok=True); p=RAW/f'marcap-{y}.parquet'
    if not p.exists():
        r=requests.get(BASE.format(year=y),timeout=180);r.raise_for_status();p.write_bytes(r.content)
    d=pd.read_parquet(p)
    if 'Date' not in d.columns:d=d.reset_index()
    d['Date']=pd.to_datetime(d.Date); d['Code']=d.Code.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
    return d

def main():
    frames=[]
    for y in YEARS:
        d=get(y); d=d[d.Market.isin(['KOSPI','KOSDAQ'])].copy(); frames.append(d)
    x=pd.concat(frames,ignore_index=True).sort_values(['Code','Date'])
    # Basic integrity
    dup=int(x.duplicated(['Date','Code']).sum())
    close=pd.to_numeric(x.Close,errors='coerce'); stocks=pd.to_numeric(x.Stocks,errors='coerce'); mar=pd.to_numeric(x.Marcap,errors='coerce')
    implied=close*stocks
    ratio=np.where(implied>0,mar/implied,np.nan)
    finite=pd.Series(ratio).replace([np.inf,-np.inf],np.nan).dropna()
    exactish=float(((finite-1).abs()<=1e-9).mean()) if len(finite) else None
    zero_open=int((pd.to_numeric(x.Open,errors='coerce')<=0).sum()); zero_close=int((close<=0).sum())
    zero_vol=int((pd.to_numeric(x.Volume,errors='coerce')<=0).sum()); zero_amount=int((pd.to_numeric(x.Amount,errors='coerce')<=0).sum())
    # Sequential changes by code. Large share-count changes are never silently adjusted.
    g=x.groupby('Code',sort=False)
    x['prev_date']=g.Date.shift(1); x['prev_close']=g.Close.shift(1); x['prev_stocks']=g.Stocks.shift(1); x['prev_marcap']=g.Marcap.shift(1)
    x['stocks_ratio']=pd.to_numeric(x.Stocks,errors='coerce')/pd.to_numeric(x.prev_stocks,errors='coerce')
    x['open_ratio']=pd.to_numeric(x.Open,errors='coerce')/pd.to_numeric(x.prev_close,errors='coerce')
    x['marcap_ratio']=pd.to_numeric(x.Marcap,errors='coerce')/pd.to_numeric(x.prev_marcap,errors='coerce')
    large=x[(x.stocks_ratio>=1.2)|(x.stocks_ratio<=0.8)].copy()
    # split-like: share ratio * price ratio approximately 1, while market cap remains broadly continuous.
    large['share_price_product']=large.stocks_ratio*large.open_ratio
    large['split_like']=(large.share_price_product.between(0.80,1.20)&large.marcap_ratio.between(0.70,1.30))
    cols=['Date','Code','Name','Market','prev_date','prev_close','Open','Close','prev_stocks','Stocks','stocks_ratio','open_ratio','prev_marcap','Marcap','marcap_ratio','share_price_product','split_like']
    large[cols].to_csv(ACTIONS,index=False)
    # Explicit Samsung 50:1 split diagnostic, a known stress case, without hardcoding an adjustment.
    ss=x[(x.Code=='005930')&(x.Date.between('2018-04-25','2018-05-10'))][['Date','Open','Close','Stocks','Marcap']].copy()
    sam=[]
    for r in ss.itertuples(index=False):sam.append({k:(v.isoformat() if hasattr(v,'isoformat') else (v.item() if hasattr(v,'item') else v)) for k,v in r._asdict().items()})
    s={
      'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_marcap_integrity_and_corporate_actions','modern_oos_protected':True,
      'rows_kospi_kosdaq':int(len(x)),'unique_codes':int(x.Code.nunique()),'duplicate_date_code_rows':dup,
      'marcap_equals_close_times_stocks_share':exactish,'marcap_ratio_median':float(finite.median()) if len(finite) else None,
      'zero_open_rows':zero_open,'zero_close_rows':zero_close,'zero_volume_rows':zero_vol,'zero_amount_rows':zero_amount,
      'large_share_count_change_rows':int(len(large)),'split_like_rows':int(large.split_like.sum()),
      'samsung_2018_split_window':sam,
      'policy_recommendation':'Use raw open/close for ordinary windows. Any holding window crossing a large share-count change must be corporate-action flagged; do not compute naive raw-price return across the event until adjustment classification is validated.',
      'files':[str(ACTIONS)]}
    OUT.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
