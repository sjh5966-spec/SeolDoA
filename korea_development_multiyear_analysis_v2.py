#!/usr/bin/env python3
"""Patch v1 multiyear Development analysis to use receipt-level historical universes.
Development only; 2023+ OOS untouched.
"""
from __future__ import annotations
import pandas as pd
import korea_development_multiyear_analysis_v1 as v1


def attach_periodic_signal(x: pd.DataFrame) -> pd.DataFrame:
    parts=[]
    for y in range(2016,2021):
        p=f'korea_dart_historical_universe_{y}.csv'
        u=pd.read_csv(p,dtype=str).fillna('')
        u['fiscal_year']=y
        if 'is_earliest_corp_period' in u.columns:
            u=u[u['is_earliest_corp_period'].astype(str).str.lower().eq('true')].copy()
        else:
            u=u.sort_values(['corp_code','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','period'],keep='first')
        u=u[u['period'].isin(['Q1','H1','Q3','FY'])].copy()
        u['corp_code']=u['corp_code'].astype(str).str.zfill(8)
        u['quarter']=u['period'].map({'Q1':'Q1','H1':'Q2','Q3':'Q3','FY':'Q4'})
        parts.append(u[['corp_code','fiscal_year','quarter','rcept_dt','rcept_no']])
    m=pd.concat(parts,ignore_index=True)
    m=m.sort_values(['corp_code','fiscal_year','quarter','rcept_dt','rcept_no']).drop_duplicates(['corp_code','fiscal_year','quarter'],keep='first')
    m=m.rename(columns={'rcept_dt':'signal_date','rcept_no':'signal_receipt_no'})
    # v1 security join already creates fiscal_year; avoid duplicate fiscal-year columns.
    left=x.drop(columns=['fiscal_year'],errors='ignore')
    return left.merge(m,left_on=['corp_code','business_year','quarter'],right_on=['corp_code','fiscal_year','quarter'],how='left')

v1.attach_periodic_signal=attach_periodic_signal

if __name__=='__main__':
    v1.main()
