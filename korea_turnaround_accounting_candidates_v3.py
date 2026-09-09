#!/usr/bin/env python3
"""Full-Development accounting-only turnaround candidate builder.

Consumes completed 2015 receipt-XBRL chunks and 2016-2020 full-financial API chunks.
No KRX/mcap/returns and no signal-date assignment. 2021+ and 2023+ are hard-excluded.
"""
from __future__ import annotations
import glob,json
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd

OUT=Path('korea_turnaround_accounting_candidates_development.csv')
SUM=Path('korea_turnaround_accounting_candidates_development_summary.json')
Q={'Q1':1,'Q2':2,'Q3':3,'Q4':4}

def load():
    paths=[Path(x) for x in glob.glob('korea_dart_quarterly_xbrl_2015_chunk*.csv')]
    paths += [Path(x) for x in glob.glob('korea_dart_quarterly_v2_20*_chunk*.csv')]
    frames=[]
    for p in sorted(set(paths)):
        # Ignore historical smoke files not produced by the final collectors when filename collides only by year.
        try:d=pd.read_csv(p,dtype={'corp_code':str})
        except Exception:continue
        if not {'corp_code','business_year','fiscal_quarter','operating_profit_q','net_income_q','equity_q_end'}.issubset(d.columns):continue
        d['source_file']=p.name;frames.append(d)
    if not frames:raise SystemExit('no final Development quarterly chunk inputs')
    d=pd.concat(frames,ignore_index=True,sort=False)
    d['business_year']=pd.to_numeric(d.business_year,errors='coerce')
    d=d[d.business_year.between(2015,2020)].copy()
    d['corp_code']=d.corp_code.astype(str).str.zfill(8);d['qord']=d.fiscal_quarter.map(Q);d=d[d.qord.notna()].copy()
    d['seq']=d.business_year.astype(int)*4+d.qord.astype(int)
    d['source_priority']=d.source_file.str.contains('xbrl_2015_chunk').astype(int)*2 + d.source_file.str.contains('quarterly_v2_').astype(int)
    # Chunk outputs should not overlap; if they do, preserve final-source preference and flag duplicate count later.
    d['duplicate_corp_quarter_count']=d.groupby(['corp_code','seq'])['corp_code'].transform('size')
    d=d.sort_values(['corp_code','seq','source_priority','source_file']).drop_duplicates(['corp_code','seq'],keep='last')
    return d,sorted(set(x for f in frames for x in f.source_file.unique()))

def n(x):
    try:return float(x) if pd.notna(x) else None
    except:return None

def main():
    d,sources=load(); keyed={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)};byseq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)}
    rows=[]
    for r in d.itertuples(index=False):
        corp=r.corp_code;y=int(r.business_year);q=r.fiscal_quarter;seq=int(r.seq);py=keyed.get((corp,y-1,q))
        op=n(r.operating_profit_q);pop=n(py.operating_profit_q) if py is not None else None;eq=n(r.equity_q_end);fcf=n(getattr(r,'fcf_q',None));pfcf=n(getattr(py,'fcf_q',None)) if py is not None else None
        four=[byseq.get((corp,s)) for s in range(seq-3,seq+1)];exact=all(x is not None for x in four)
        bases=[str(getattr(x,'statement_basis','') or '') for x in four] if exact else [];same_basis=bool(exact and bases and len(set(bases))==1 and bases[0])
        ni=[n(getattr(x,'net_income_q',None)) if x is not None else None for x in four];ni_ok=bool(same_basis and all(x is not None for x in ni));ni_ttm=sum(ni) if ni_ok else None
        turn=bool(op is not None and pop is not None and op>0 and pop<=0);base=bool(turn and ni_ttm is not None and ni_ttm<0 and eq is not None and eq>0)
        rows.append({'corp_code':corp,'company_name':str(getattr(r,'company_name','') or ''),'business_year':y,'fiscal_quarter':q,'statement_basis':str(getattr(r,'statement_basis','') or ''),
          'operating_profit_q':op,'prior_year_same_q_operating_profit':pop,'prior_year_same_q_available':pop is not None,'op_turnaround_yoy':turn,
          'net_income_ttm':ni_ttm,'ttm_exact_four_quarters':exact,'ttm_same_basis':same_basis,'ttm_net_income_valid':ni_ok,'equity_q_end':eq,
          'fcf_q':fcf,'prior_year_same_q_fcf':pfcf,'fcf_yoy_improvement':fcf-pfcf if fcf is not None and pfcf is not None else None,
          'base_a_accounting_only':base,'receipt_no':str(getattr(r,'receipt_no','') or ''),'receipt_date':str(getattr(r,'receipt_date','') or ''),
          'duplicate_corp_quarter_count':int(getattr(r,'duplicate_corp_quarter_count',1)),'source_file':str(getattr(r,'source_file','')),
          'signal_date_status':'NOT_CONFIRMED_CANDIDATE_ONLY','mcap_status':'NOT_AVAILABLE_KRX_PENDING','modern_oos_protected':True})
    o=pd.DataFrame(rows).sort_values(['business_year','fiscal_quarter','corp_code']);o.to_csv(OUT,index=False)
    c=o[o.op_turnaround_yoy];b=o[o.base_a_accounting_only]
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_full_accounting_candidate_build','modern_oos_protected':True,
       'source_files':sources,'rows':int(len(o)),'unique_corps':int(o.corp_code.nunique()),'years':sorted(int(x) for x in o.business_year.unique()),
       'duplicate_corp_quarter_rows':int((o.duplicate_corp_quarter_count>1).sum()),'prior_year_same_q_available_rows':int(o.prior_year_same_q_available.sum()),
       'ttm_net_income_valid_rows':int(o.ttm_net_income_valid.sum()),'op_turnaround_rows':int(len(c)),'base_a_accounting_only_rows':int(len(b)),
       'turnaround_by_year':{str(k):int(v) for k,v in c.business_year.value_counts().sort_index().items()},'base_a_by_year':{str(k):int(v) for k,v in b.business_year.value_counts().sort_index().items()},
       'important_limitation':'Accounting-only Development screen. Final Base A still requires PIT KRX market cap/tradability and candidate-specific earliest signal disclosure confirmation.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
