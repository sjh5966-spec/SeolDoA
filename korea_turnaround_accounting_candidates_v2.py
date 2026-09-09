#!/usr/bin/env python3
"""Accounting-only turnaround candidate builder v2 using sequence-checked quarterly data.
Development only. No KRX/mcap/returns/signal-date assignment.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd

FILES=[Path('korea_dart_quarterly_xbrl_2015_sequence_checked.csv'),Path('korea_dart_quarterly_v2_2016_chunk000_sequence_checked.csv')]
OUT=Path('korea_turnaround_accounting_candidates_v2.csv');SUM=Path('korea_turnaround_accounting_candidates_v2_summary.json')
Q={'Q1':1,'Q2':2,'Q3':3,'Q4':4}

def main():
    frames=[]
    for f in FILES:
        if not f.exists():continue
        d=pd.read_csv(f,dtype={'corp_code':str}).copy();d['source_file']=str(f);frames.append(d)
    if not frames:raise SystemExit('no sequence-checked inputs')
    d=pd.concat(frames,ignore_index=True,sort=False);d=d[d.business_year.astype(int).between(2015,2020)].copy();d['corp_code']=d.corp_code.astype(str).str.zfill(8)
    if 'company_name' not in d:d['company_name']=''
    d['company_name']=d['company_name'].fillna('');d['qord']=d.fiscal_quarter.map(Q);d=d[d.qord.notna()];d['seq']=d.business_year.astype(int)*4+d.qord.astype(int)
    d['priority']=d.source_file.str.contains('xbrl_2015').astype(int)
    d=d.sort_values(['corp_code','seq','priority']).drop_duplicates(['corp_code','seq'],keep='last')
    keyed={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)}
    byseq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)}
    rows=[]
    for r in d.itertuples(index=False):
        corp=r.corp_code;y=int(r.business_year);q=r.fiscal_quarter;seq=int(r.seq);py=keyed.get((corp,y-1,q))
        op=float(r.operating_profit_q) if pd.notna(r.operating_profit_q) else None;pop=float(py.operating_profit_q) if py is not None and pd.notna(py.operating_profit_q) else None
        four=[byseq.get((corp,s)) for s in range(seq-3,seq+1)];exact=all(x is not None for x in four)
        bases=[str(x.statement_basis or '') for x in four] if exact else [];same_basis=bool(exact and len(set(bases))==1 and bases[0])
        nis=[x.net_income_q if x is not None else None for x in four];ni_ok=bool(same_basis and all(pd.notna(x) for x in nis));ni_ttm=sum(float(x) for x in nis) if ni_ok else None
        eq=float(r.equity_q_end) if pd.notna(r.equity_q_end) else None;fcf=float(r.fcf_q) if pd.notna(r.fcf_q) else None;pfcf=float(py.fcf_q) if py is not None and pd.notna(py.fcf_q) else None
        turn=bool(op is not None and pop is not None and op>0 and pop<=0);base=bool(turn and ni_ttm is not None and ni_ttm<0 and eq is not None and eq>0)
        rows.append({'corp_code':corp,'company_name':r.company_name,'business_year':y,'fiscal_quarter':q,'statement_basis':r.statement_basis,'operating_profit_q':op,'prior_year_same_q_operating_profit':pop,'op_turnaround_yoy':turn,'net_income_ttm':ni_ttm,'ttm_exact_four_quarters':exact,'ttm_same_basis':same_basis,'equity_q_end':eq,'fcf_q':fcf,'prior_year_same_q_fcf':pfcf,'fcf_yoy_improvement':fcf-pfcf if fcf is not None and pfcf is not None else None,'base_a_accounting_only':base,'receipt_no':getattr(r,'receipt_no',''),'receipt_date':getattr(r,'receipt_date',''),'signal_date_status':'NOT_CONFIRMED','mcap_status':'NOT_AVAILABLE_KRX_PENDING','modern_oos_protected':True})
    o=pd.DataFrame(rows);o.to_csv(OUT,index=False)
    c=o[o.op_turnaround_yoy];b=o[o.base_a_accounting_only]
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_sequence_checked_accounting_candidates','modern_oos_protected':True,'source_files':[str(x) for x in FILES if x.exists()],'rows':len(o),'unique_corps':int(o.corp_code.nunique()),'op_turnaround_rows':int(len(c)),'base_a_accounting_only_rows':int(len(b)),'ttm_complete_same_basis_rows':int((o.ttm_exact_four_quarters&o.ttm_same_basis).sum()),'turnaround_by_year':c.business_year.value_counts().sort_index().to_dict(),'base_a_by_year':b.business_year.value_counts().sort_index().to_dict(),'important_limitation':'Only accounting screen on 20-corp smoke overlap. Not representative of Korean universe. Final Base A requires historical KRX universe/mcap and candidate signal-date confirmation.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
    if len(c):print(c[['corp_code','company_name','business_year','fiscal_quarter','operating_profit_q','prior_year_same_q_operating_profit','net_income_ttm','equity_q_end','base_a_accounting_only']].to_string(index=False))
if __name__=='__main__':main()
