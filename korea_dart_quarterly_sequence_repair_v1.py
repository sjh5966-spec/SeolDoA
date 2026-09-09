#!/usr/bin/env python3
"""Repair/validate pure-quarter sequences from DART accounting outputs.
Development-only. Enforces immediate predecessor semantics exactly.
"""
from __future__ import annotations
import glob,json
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd

QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
FLOW=[('operating_profit','operating_profit_cumulative','operating_profit_q'),('net_income','net_income_cumulative','net_income_q'),('cfo','cfo_cumulative','cfo_q')]
CAP=[('ppe','capex_ppe_cumulative','capex_ppe_q_spend'),('intangible','capex_intangible_cumulative','capex_intangible_q_spend')]

def repair(path):
    d=pd.read_csv(path,dtype={'corp_code':str})
    if d.empty:return d,{}
    d['corp_code']=d['corp_code'].astype(str).str.zfill(8);d['_q']=d['fiscal_quarter'].map(QORD)
    d=d.sort_values(['corp_code','business_year','_q']).copy()
    changed=0; broken=0; negcap=0
    for (corp,year),idxs in d.groupby(['corp_code','business_year']).groups.items():
        idxs=list(d.loc[idxs].sort_values('_q').index)
        byq={int(d.at[i,'_q']):i for i in idxs if pd.notna(d.at[i,'_q'])}
        for qn,i in sorted(byq.items()):
            basis=str(d.at[i,'statement_basis']) if 'statement_basis' in d.columns and pd.notna(d.at[i,'statement_basis']) else ''
            pi=byq.get(qn-1)
            pbasis=(str(d.at[pi,'statement_basis']) if pi is not None and 'statement_basis' in d.columns and pd.notna(d.at[pi,'statement_basis']) else '')
            comparable=(qn==1) or (pi is not None and basis!='' and pbasis==basis)
            if 'basis_comparable_to_immediate_predecessor' in d.columns:d.at[i,'basis_comparable_to_immediate_predecessor']=bool(comparable)
            for _,cumcol,qcol in FLOW:
                if cumcol not in d.columns or qcol not in d.columns:continue
                cur=d.at[i,cumcol]
                new=None
                if qn==1:new=cur if pd.notna(cur) else None
                elif comparable and pi is not None:
                    prev=d.at[pi,cumcol]
                    if pd.notna(cur) and pd.notna(prev):new=float(cur)-float(prev)
                    else:broken+=1
                old=d.at[i,qcol]
                if (pd.isna(old) and new is not None) or (pd.notna(old) and (new is None or abs(float(old)-float(new))>1e-9)):
                    changed+=1
                d.at[i,qcol]=new
            spends=[]
            for _,cumcol,scol in CAP:
                if cumcol not in d.columns or scol not in d.columns:continue
                cur=d.at[i,cumcol];sp=None
                if qn==1:
                    if pd.notna(cur):sp=abs(float(cur))
                elif comparable and pi is not None:
                    prev=d.at[pi,cumcol]
                    if pd.notna(cur) and pd.notna(prev):
                        delta=abs(float(cur))-abs(float(prev))
                        if delta>=-1e-6:sp=max(0.0,delta)
                        else:negcap+=1;sp=None
                    else:broken+=1
                old=d.at[i,scol]
                if (pd.isna(old) and sp is not None) or (pd.notna(old) and (sp is None or abs(float(old)-float(sp))>1e-9)):changed+=1
                d.at[i,scol]=sp;spends.append(sp)
            if 'capex_q_spend' in d.columns:
                cap=(sum(spends) if len(spends)==2 and all(x is not None for x in spends) else None);d.at[i,'capex_q_spend']=cap
                if 'fcf_q' in d.columns:
                    cfo=d.at[i,'cfo_q'];d.at[i,'fcf_q']=(float(cfo)-cap if pd.notna(cfo) and cap is not None else None)
    d=d.drop(columns=['_q'])
    return d,{'changed_cells':changed,'missing_immediate_predecessor_metric_cases':broken,'negative_normalized_capex_delta_cases':negcap}

def main():
    inputs=sorted(glob.glob('korea_dart_quarterly_v2_20??_chunk*.csv'))
    if Path('korea_dart_quarterly_xbrl_2015.csv').exists():inputs.append('korea_dart_quarterly_xbrl_2015.csv')
    if not inputs:raise SystemExit('No quarterly accounting files found')
    reports=[]
    for f in inputs:
        d,stats=repair(f);out=Path(f).with_name(Path(f).stem+'_sequence_checked.csv');d.to_csv(out,index=False)
        stats.update({'input':f,'output':str(out),'rows':len(d),'op_q_populated':int(d.operating_profit_q.notna().sum()) if 'operating_profit_q' in d else 0,'fcf_q_populated':int(d.fcf_q.notna().sum()) if 'fcf_q' in d else 0});reports.append(stats)
    obj={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_sequence_validation','modern_oos_protected':True,'reports':reports,'rule':'Q2/Q3/Q4 require the immediately preceding quarter cumulative metric on the same statement basis. CAPEX cumulative values are sign-normalized before differencing; negative normalized deltas are missing, never absolute-valued.'}
    Path('korea_dart_quarterly_sequence_repair_summary.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(obj,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
