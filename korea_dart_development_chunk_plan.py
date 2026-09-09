#!/usr/bin/env python3
"""Plan controlled Korea Development quarterly accounting collection without making API calls."""
from pathlib import Path
import json, math
from datetime import datetime, timezone
import pandas as pd

SEED=Path('korea_dart_historical_seed_2015_2020.csv')
OUT=Path('korea_dart_development_chunk_plan.json')
CHUNK_2015=50
CHUNK_2016_2020=100

def main():
    if not SEED.exists(): raise SystemExit(f'missing {SEED}')
    d=pd.read_csv(SEED,dtype=str).fillna('')
    plan={}
    total_corps=total_chunks=0
    for y in range(2015,2021):
        n=int(d[d.fiscal_year.astype(str).eq(str(y))].corp_code.astype(str).nunique())
        size=CHUNK_2015 if y==2015 else CHUNK_2016_2020
        chunks=math.ceil(n/size) if n else 0
        # 2015: up to four receipt-XBRL calls/corp. 2016+: up to four quarters * two bases/corp.
        max_calls_per_corp=4 if y==2015 else 8
        plan[str(y)]={'corp_years':n,'chunk_size':size,'chunks':chunks,'max_source_calls_estimate':n*max_calls_per_corp,
                      'collector':'korea_dart_2015_xbrl_collector_v2.py' if y==2015 else 'korea_dart_quarterly_collector_v2.py'}
        total_corps+=n; total_chunks+=chunks
    out={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_collection_planning_only',
         'modern_oos_protected':True,'seed':SEED.name,'years':plan,'total_corp_years':total_corps,'total_chunks':total_chunks,
         'notes':['No API calls or prices are made by this planner.','2015 uses receipt-specific XBRL.','2016-2020 use full-financial API with CFS/OFS fallback.','Run chunks serially/conservatively to avoid DART rate limits.']}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
