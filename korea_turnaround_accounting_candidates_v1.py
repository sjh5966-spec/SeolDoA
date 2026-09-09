#!/usr/bin/env python3
"""Build accounting-only Korea turnaround candidates from pure-quarter DART outputs.

No market cap, KRX price, return, or signal-date use. This is a pre-KRX accounting screen only.
Requires exact four-quarter TTM NI and same-quarter prior-year operating profit.
"""
from __future__ import annotations
import glob, json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

OUT=Path('korea_turnaround_accounting_candidates.csv')
SUM=Path('korea_turnaround_accounting_candidates_summary.json')
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}

def seq_id(y,q): return int(y)*4+QORD[q]

def main():
    files=sorted(glob.glob('korea_dart_quarterly_v2_20??_chunk*.csv'))
    if not files: raise SystemExit('No quarterly v2 files found')
    frames=[]
    for f in files:
        d=pd.read_csv(f,dtype={'corp_code':str})
        d['source_file']=f; frames.append(d)
    df=pd.concat(frames,ignore_index=True)
    df=df[df['business_year'].astype(int).between(2015,2020)].copy()
    df['corp_code']=df['corp_code'].astype(str).str.zfill(8)
    df['qord']=df['fiscal_quarter'].map(QORD); df=df[df.qord.notna()].copy()
    df['seq']=df.apply(lambda r:seq_id(r.business_year,r.fiscal_quarter),axis=1)
    df=df.sort_values(['corp_code','seq']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    keys={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in df.itertuples(index=False)}
    out=[]
    for corp,g in df.groupby('corp_code',sort=False):
        g=g.sort_values('seq'); history=list(g.itertuples(index=False))
        byseq={int(r.seq):r for r in history}
        for r in history:
            y=int(r.business_year); q=r.fiscal_quarter; prevy=keys.get((corp,y-1,q))
            last4=[byseq.get(int(r.seq)-i) for i in range(3,-1,-1)]
            exact4=all(x is not None for x in last4) and [x.seq for x in last4]==list(range(int(r.seq)-3,int(r.seq)+1))
            ni_vals=[getattr(x,'net_income_q',None) if x is not None else None for x in last4]
            same_basis=exact4 and len({getattr(x,'statement_basis','') for x in last4})==1 and all(getattr(x,'statement_basis','') for x in last4)
            ni_complete=exact4 and all(pd.notna(v) for v in ni_vals)
            ni_ttm=sum(float(v) for v in ni_vals) if ni_complete and same_basis else None
            op=float(r.operating_profit_q) if pd.notna(r.operating_profit_q) else None
            prior_op=float(prevy.operating_profit_q) if prevy is not None and pd.notna(prevy.operating_profit_q) else None
            equity=float(r.equity_q_end) if pd.notna(r.equity_q_end) else None
            fcf=float(r.fcf_q) if pd.notna(r.fcf_q) else None
            prior_fcf=float(prevy.fcf_q) if prevy is not None and pd.notna(prevy.fcf_q) else None
            turnaround=(op is not None and prior_op is not None and op>0 and prior_op<=0)
            base_accounting=bool(turnaround and ni_ttm is not None and ni_ttm<0 and equity is not None and equity>0)
            out.append({
                'corp_code':corp,'company_name':r.company_name,'business_year':y,'fiscal_quarter':q,'statement_basis':r.statement_basis,
                'operating_profit_q':op,'prior_year_same_q_operating_profit':prior_op,'op_turnaround_yoy':turnaround,
                'net_income_ttm':ni_ttm,'ttm_exact_four_quarters':bool(exact4),'ttm_same_basis':bool(same_basis),'equity_q_end':equity,
                'fcf_q':fcf,'prior_year_same_q_fcf':prior_fcf,'fcf_yoy_improvement':(fcf-prior_fcf) if fcf is not None and prior_fcf is not None else None,
                'base_a_accounting_only':base_accounting,'signal_date_status':'NOT_CONFIRMED','mcap_status':'NOT_AVAILABLE_KRX_PENDING',
                'modern_oos_protected':True,
            })
    o=pd.DataFrame(out); o.to_csv(OUT,index=False)
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_accounting_candidate_screen','modern_oos_protected':True,
       'source_files':files,'rows':int(len(o)),'op_turnaround_rows':int(o.op_turnaround_yoy.sum()),'base_a_accounting_only_rows':int(o.base_a_accounting_only.sum()),
       'ttm_complete_same_basis_rows':int((o.ttm_exact_four_quarters & o.ttm_same_basis).sum()),
       'important_limitation':'Accounting-only. Base A is not final until contemporaneous market cap/universe filters and confirmed earliest disclosure signal dates are joined.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(s,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
