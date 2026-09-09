#!/usr/bin/env python3
"""Build 2017-2020 Development accounting candidates from OpenDART bulk discovery data.
2016 candidates are withheld until full 2015 receipt-XBRL prior-year quarters are available.
Bulk values are NOT PIT-confirmed; all candidates require original-receipt confirmation.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,pandas as pd
SRC=Path('korea_dart_bulk_quarterly_2016_2020.csv')
OUT=Path('korea_turnaround_bulk_candidates_2017_2020.csv')
CAND=Path('korea_turnaround_bulk_base_a_2017_2020.csv')
SUM=Path('korea_turnaround_bulk_candidates_2017_2020_summary.json')
Q={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
def f(x):return float(x) if pd.notna(x) else None
def main():
 d=pd.read_csv(SRC,dtype={'corp_code':str,'stock_code':str});d=d[d.business_year.astype(int).between(2016,2020)].copy();d['corp_code']=d.corp_code.astype(str).str.zfill(8);d['qord']=d.fiscal_quarter.map(Q);d=d[d.qord.notna()];d['seq']=d.business_year.astype(int)*4+d.qord.astype(int)
 d=d.sort_values(['corp_code','seq']).drop_duplicates(['corp_code','seq'],keep='last')
 byseq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)};byyq={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)};rows=[]
 for r in d.itertuples(index=False):
  y=int(r.business_year);q=r.fiscal_quarter;seq=int(r.seq);py=byyq.get((r.corp_code,y-1,q));op=f(r.operating_profit_q);pop=f(py.operating_profit_q) if py is not None else None;eq=f(r.equity_q_end);fcf=f(r.fcf_q);pfcf=f(py.fcf_q) if py is not None else None
  four=[byseq.get((r.corp_code,s)) for s in range(seq-3,seq+1)];exact=all(x is not None for x in four);bases=[str(x.statement_basis or '') for x in four] if exact else [];same=bool(exact and len(set(bases))==1 and bases[0]);nis=[f(x.net_income_q) if x is not None else None for x in four];niok=bool(same and all(x is not None for x in nis));nittm=sum(nis) if niok else None
  turn=bool(y>=2017 and op is not None and pop is not None and op>0 and pop<=0);base=bool(turn and nittm is not None and nittm<0 and eq is not None and eq>0)
  rows.append({'corp_code':r.corp_code,'company_name':r.company_name,'stock_code':r.stock_code,'business_year':y,'fiscal_quarter':q,'statement_basis':r.statement_basis,'operating_profit_q':op,'prior_year_same_q_operating_profit':pop,'op_turnaround_yoy':turn,'net_income_ttm':nittm,'ttm_exact_four_quarters':exact,'ttm_same_basis':same,'equity_q_end':eq,'fcf_q':fcf,'prior_year_same_q_fcf':pfcf,'fcf_yoy_improvement':fcf-pfcf if fcf is not None and pfcf is not None else None,'base_a_accounting_only':base,'pit_value_confirmed':False,'signal_date_status':'NOT_CONFIRMED','source_type':'OPENDART_BULK_DISCOVERY_ONLY','modern_oos_protected':True})
 o=pd.DataFrame(rows);o=o[o.business_year.astype(int).between(2017,2020)].copy();o.to_csv(OUT,index=False);c=o[o.base_a_accounting_only].copy();c.to_csv(CAND,index=False)
 s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_bulk_candidate_discovery','years':[2017,2018,2019,2020],'modern_oos_protected':True,'rows':len(o),'unique_corps':int(o.corp_code.nunique()),'op_turnaround_rows':int(o.op_turnaround_yoy.sum()),'base_a_accounting_only_rows':len(c),'ttm_complete_same_basis_rows':int((o.ttm_exact_four_quarters&o.ttm_same_basis&o.net_income_ttm.notna()).sum()),'turnaround_by_year':o[o.op_turnaround_yoy].business_year.value_counts().sort_index().to_dict(),'base_a_by_year':c.business_year.value_counts().sort_index().to_dict(),'fcf_complete_base_a':int(c.fcf_q.notna().sum()),'fcf_yoy_improvement_complete_base_a':int(c.fcf_yoy_improvement.notna().sum()),'critical_limitation':'Bulk snapshot discovery only. These are NOT final PIT candidates. Original receipt-specific accounting values and earliest signal disclosures must be confirmed before market-return analysis.'}
 SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
