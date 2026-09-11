#!/usr/bin/env python3
"""Reaggregate all available 2016-2020 DART accounting chunk artifacts after retries.
Development only. Excludes sequence_checked derivative files and deduplicates by corp/year/quarter,
preferring the row with the most populated core accounting fields.
"""
from __future__ import annotations
import json,re
from pathlib import Path
import pandas as pd

ROOT=Path('recovery_chunks')
OUT=Path('korea_dart_quarterly_2016_2020_recovered.csv')
SUM=Path('korea_dart_quarterly_2016_2020_recovered_summary.json')
SEED=Path('korea_dart_historical_seed_2015_2020.csv')
CORE=['operating_profit_q','net_income_q','equity_q_end','cfo_q','fcf_q']


def main():
    files=[]
    for p in ROOT.rglob('*.csv'):
        n=p.name
        if '_sequence_checked' in n: continue
        if not re.match(r'korea_dart_quarterly_v2_20(16|17|18|19|20)_chunk\d+\.csv$',n): continue
        files.append(p)
    if not files: raise SystemExit('no chunk csv files found')
    frames=[]; bad=[]
    for p in files:
        try:
            d=pd.read_csv(p,dtype={'corp_code':str},low_memory=False)
            if d.empty or not {'corp_code','business_year','fiscal_quarter'}.issubset(d.columns):
                bad.append(str(p));continue
            d['_artifact_path']=str(p)
            frames.append(d)
        except Exception as e: bad.append(f'{p}:{type(e).__name__}')
    if not frames: raise SystemExit('no readable chunk frames')
    d=pd.concat(frames,ignore_index=True,sort=False)
    d['corp_code']=d.corp_code.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(8)
    d['business_year']=pd.to_numeric(d.business_year,errors='coerce')
    d=d[d.business_year.between(2016,2020)].copy()
    for c in CORE:
        if c not in d.columns:d[c]=pd.NA
    d['_core_score']=d[CORE].notna().sum(axis=1)
    if 'source_status' in d.columns:d['_ok_score']=d.source_status.astype(str).eq('ok').astype(int)
    else:d['_ok_score']=0
    d=d.sort_values(['corp_code','business_year','fiscal_quarter','_core_score','_ok_score'])
    before=len(d);dup=int(d.duplicated(['corp_code','business_year','fiscal_quarter'],keep=False).sum())
    d=d.drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last').copy()
    d=d.drop(columns=['_core_score','_ok_score'])
    d.to_csv(OUT,index=False)
    seed=pd.read_csv(SEED,dtype=str).fillna('');seed['fiscal_year']=pd.to_numeric(seed.fiscal_year,errors='coerce')
    expected=seed[seed.fiscal_year.between(2016,2020)].groupby('fiscal_year').corp_code.nunique().to_dict()
    coverage={}
    for y in range(2016,2021):
        z=d[d.business_year.eq(y)];exp=int(expected.get(y,0));corps=int(z.corp_code.nunique())
        coverage[str(y)]={'expected_corps':exp,'observed_corps':corps,'corp_coverage':corps/exp if exp else None,'rows':int(len(z)),'expected_rows':exp*4,'row_coverage':len(z)/(exp*4) if exp else None,'op_populated':int(z.operating_profit_q.notna().sum()),'ni_populated':int(z.net_income_q.notna().sum()),'equity_populated':int(z.equity_q_end.notna().sum()),'fcf_populated':int(z.fcf_q.notna().sum())}
    s={'development_only':True,'modern_oos_protected':True,'artifact_csv_files':len(files),'readable_frames':len(frames),'bad_files':bad,'rows_before_dedup':before,'duplicate_key_rows_seen':dup,'rows_after_dedup':len(d),'unique_corps':int(d.corp_code.nunique()),'coverage':coverage,'source_root':str(ROOT),'note':'Recovery aggregate prefers the most complete duplicate row. It excludes sequence_checked derivative files. 2021+ accounting and 2023+ OOS are not accessed.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
