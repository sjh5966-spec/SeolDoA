#!/usr/bin/env python3
"""Build annual corp-year accounting seed from reconstructed historical DART filing universes.
Development-only 2015-2020. No current-membership assumption, no KRX, no returns/OOS.
"""
from __future__ import annotations
import glob, json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

OUT=Path('korea_dart_historical_seed_2015_2020.csv')
SUM=Path('korea_dart_historical_seed_2015_2020_summary.json')

def main():
    files=sorted(glob.glob('korea_dart_historical_universe_20??.csv'))
    frames=[]
    for f in files:
        try:
            d=pd.read_csv(f,dtype=str).fillna('')
        except Exception:
            continue
        if 'target_year' not in d.columns or d.empty: continue
        d=d[d['target_year'].astype(int).between(2015,2020)].copy()
        frames.append(d)
    if not frames:
        raise SystemExit('No historical universe CSVs found')
    df=pd.concat(frames,ignore_index=True)
    # One corp-year row: choose earliest PIT periodic filing in the target fiscal year set.
    df=df.sort_values(['target_year','corp_code','rcept_dt','rcept_no'])
    first=df.groupby(['target_year','corp_code'],as_index=False).first()
    out=pd.DataFrame({
        'corp_code':first['corp_code'].astype(str).str.zfill(8),
        'fiscal_year':first['target_year'].astype(str),
        'company_name':first.get('corp_name',''),
        'basis':'',
        'filing_date':first.get('rcept_dt',''),
        'receipt_no':first.get('rcept_no',''),
        'period_to':'',
        'stock_code':first.get('stock_code',''),
        'corp_cls':first.get('corp_cls',''),
        'first_period':first.get('period',''),
        'seed_source':'historical_dart_periodic_filing_universe',
    }).sort_values(['fiscal_year','corp_code'])
    out.to_csv(OUT,index=False)
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_historical_seed_build','modern_oos_protected':True,
       'source_files':files,'rows':int(len(out)),'year_counts':out.fiscal_year.value_counts().sort_index().to_dict(),
       'market_counts':out.corp_cls.value_counts().to_dict(),
       'important_limitation':'DART filer seed; KRX security-type exclusions and historical listing/tradability remain separate validation.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(s,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
