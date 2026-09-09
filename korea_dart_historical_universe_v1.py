#!/usr/bin/env python3
"""Reconstruct historical KOSPI/KOSDAQ filer universe from OpenDART periodic filing search.
Development-only 2015-2020. Uses filing lists, not current-company membership.
No KRX prices/returns and no 2021+ strategy data.
"""
from __future__ import annotations
import calendar, json, os, re, time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from collections import Counter
import pandas as pd
import requests

API='https://opendart.fss.or.kr/api/list.json'
REPORT_DETAIL=['A001','A002','A003']  # annual, half-year, quarterly
PERIOD_PATTERNS={
    'Q1': re.compile(r'\(\s*%s[./-]?0?3\s*\)'),
    'H1': re.compile(r'\(\s*%s[./-]?0?6\s*\)'),
    'Q3': re.compile(r'\(\s*%s[./-]?0?9\s*\)'),
    'FY': re.compile(r'\(\s*%s[./-]?12\s*\)'),
}

def ymd(d): return d.strftime('%Y%m%d')

def chunks(start,end,days=89):
    cur=start
    while cur<=end:
        nxt=min(end,cur+timedelta(days=days))
        yield cur,nxt
        cur=nxt+timedelta(days=1)

def api(session,key,params):
    last=None
    for attempt in range(5):
        try:
            r=session.get(API,params={'crtfc_key':key,**params},timeout=60); r.raise_for_status()
            d=r.json(); st=str(d.get('status',''))
            if st in ('000','013'): return d
            if st=='020': time.sleep(2*(attempt+1)); continue
            return d
        except Exception as e:
            last=str(e); time.sleep(attempt+1)
    return {'status':'REQUEST_ERROR','message':last,'list':[]}

def target_period(report_nm,year):
    s=str(report_nm or '')
    for q in ('Q1','H1','Q3','FY'):
        if re.search(rf'\(\s*{year}[./-]?0?{dict(Q1=3,H1=6,Q3=9,FY=12)[q]}\s*\)',s): return q
    return ''

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    year=int(os.environ.get('DART_UNIVERSE_YEAR','2020'))
    if year<2015 or year>2020: raise SystemExit('year must be 2015..2020')
    # Search through following April so FY reports for the target fiscal year are captured.
    start=date(year,1,1); end=date(year+1,4,30)
    session=requests.Session(); session.headers.update({'User-Agent':'SeolDoA-DART-Historical-Universe/1.0'})
    rows=[]; calls=Counter(); statuses=Counter()
    for a,b in chunks(start,end):
        for detail in REPORT_DETAIL:
            page=1
            while True:
                d=api(session,key,dict(bgn_de=ymd(a),end_de=ymd(b),pblntf_ty='A',pblntf_detail_ty=detail,page_no=str(page),page_count='100'))
                st=str(d.get('status','')); statuses[st]+=1; calls['requests']+=1
                if st=='013': break
                items=d.get('list') or []
                for x in items:
                    if str(x.get('corp_cls') or '') not in {'Y','K'}: continue
                    q=target_period(x.get('report_nm'),year)
                    if not q: continue
                    rows.append({
                        'target_year':year,'period':q,'corp_code':str(x.get('corp_code') or '').zfill(8),
                        'corp_name':x.get('corp_name'),'stock_code':x.get('stock_code'),'corp_cls':x.get('corp_cls'),
                        'report_nm':x.get('report_nm'),'rcept_no':x.get('rcept_no'),'rcept_dt':x.get('rcept_dt'),
                        'flr_nm':x.get('flr_nm'),'rm':x.get('rm'),'detail_type':detail,
                    })
                total_page=int(d.get('total_page') or 1)
                if page>=total_page: break
                page+=1
                if page>500: raise RuntimeError('pagination safety stop')
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df.sort_values(['corp_code','period','rcept_dt','rcept_no'])
        df['is_correction']=df['report_nm'].astype(str).str.contains('정정',na=False)
        # Preserve every filing; mark earliest original-like filing for PIT discovery.
        df['filing_rank_within_corp_period']=df.groupby(['corp_code','period']).cumcount()+1
        df['is_earliest_corp_period']=df['filing_rank_within_corp_period'].eq(1)
    out=Path(f'korea_dart_historical_universe_{year}.csv')
    summary=Path(f'korea_dart_historical_universe_{year}_summary.json')
    df.to_csv(out,index=False)
    earliest=df[df['is_earliest_corp_period']] if not df.empty else df
    s={
      'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_historical_dart_universe',
      'modern_oos_protected':True,'year':year,'search_end':ymd(end),'api_calls':int(calls['requests']),
      'api_status_counts':dict(statuses),'filing_rows':int(len(df)),'unique_corps':int(df['corp_code'].nunique()) if not df.empty else 0,
      'earliest_corp_period_rows':int(len(earliest)),'period_counts':earliest['period'].value_counts().to_dict() if not df.empty else {},
      'market_counts':earliest['corp_cls'].value_counts().to_dict() if not df.empty else {},
      'important_limitation':'DART filing universe only. Security-type exclusions, listing/delisting history, market cap and tradability still require KRX/history validation.'
    }
    summary.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(s,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
