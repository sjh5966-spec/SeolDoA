#!/usr/bin/env python3
"""Scalable 2015 Development accounting collector from receipt-specific OpenDART XBRL.

Uses the reconstructed historical DART filing universe, never current membership.
Q1/H1/Q3/FY all come from the earliest original-like periodic receipt for the target period.
Pure quarters require the immediately preceding cumulative period on the same CFS/OFS basis.
CAPEX cumulative acquisition cash spending is sign-normalized before differencing; negative deltas are missing.
Missing CAPEX facts remain missing. No KRX, returns, signal dates, 2021+, or 2023+ OOS data.
"""
from __future__ import annotations
import io,json,os,time,zipfile
from pathlib import Path
from datetime import date,datetime,timezone
from collections import Counter
import pandas as pd
import requests
from lxml import etree

UNIVERSE=Path('korea_dart_historical_universe_2015.csv')
API='https://opendart.fss.or.kr/api/fnlttXbrl.xml'
PERIODS=[('Q1',3),('Q2',6),('Q3',9),('Q4',12)]
PERIOD_SOURCE={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'}
TARGET={
 'operating_profit':'OperatingIncomeLoss',
 'net_income':'ProfitLoss',
 'equity':'Equity',
 'cfo':'CashFlowsFromUsedInOperatingActivities',
 'capex_ppe':'PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
 'capex_intangible':'PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities',
}
FLOW={'operating_profit','net_income','cfo','capex_ppe','capex_intangible'}
CAPEX={'capex_ppe','capex_intangible'}

def ln(t):
    if not isinstance(t,str): return ''
    return t.split('}',1)[-1] if '}' in t else t.split(':')[-1]
def text(e): return ''.join(e.itertext()).strip()
def number(x):
    s=str(x or '').strip().replace(',','').replace('−','-')
    if s in ('','-','—'): return None
    try:return float(s)
    except:return None
def dte(s):
    try:return date.fromisoformat(str(s))
    except:return None
def basis_from_dims(dims):
    members=[str(x.get('member') or '') for x in dims if 'ConsolidatedAndSeparateFinancialStatementsAxis' in str(x.get('dimension') or '')]
    if any('ConsolidatedMember' in m for m in members): return 'CFS'
    if any('SeparateMember' in m for m in members): return 'OFS'
    return ''
def extra_dims(dims):
    return any('ConsolidatedAndSeparateFinancialStatementsAxis' not in str(x.get('dimension') or '') for x in dims)

def parse_instance(raw):
    root=etree.fromstring(raw,parser=etree.XMLParser(recover=True,huge_tree=True))
    contexts={}
    for c in root.iter():
        if ln(c.tag)!='context': continue
        r={'start':None,'end':None,'instant':None,'dims':[]}
        for x in c.iter():
            n=ln(x.tag)
            if n=='startDate':r['start']=text(x)
            elif n=='endDate':r['end']=text(x)
            elif n=='instant':r['instant']=text(x)
            elif n in ('explicitMember','typedMember'):r['dims'].append({'dimension':x.get('dimension'),'member':text(x)})
        r['basis']=basis_from_dims(r['dims']);r['extra_dims']=extra_dims(r['dims']);contexts[c.get('id') or '']=r
    wanted=set(TARGET.values()); facts=[]
    for e in root.iter():
        n=ln(e.tag)
        if n not in wanted: continue
        v=number(text(e))
        if v is None: continue
        c=contexts.get(e.get('contextRef') or '',{})
        facts.append({'name':n,'value':v,'start':c.get('start'),'end':c.get('end'),'instant':c.get('instant'),'basis':c.get('basis'),'extra_dims':c.get('extra_dims',False)})
    return facts

def fetch_xbrl(session,key,rno):
    if not rno:return None,'no_receipt'
    last=''
    for attempt in range(4):
        try:
            r=session.get(API,params={'crtfc_key':key,'rcept_no':rno},timeout=120);raw=r.content
            if raw[:2]!=b'PK': return None,'no_xbrl_zip'
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names=[n for n in zf.namelist() if n.lower().endswith('.xbrl')]
                if not names:return None,'no_instance'
                n=max(names,key=lambda x:zf.getinfo(x).file_size)
                return parse_instance(zf.read(n)),'ok'
        except Exception as e:
            last=str(e);time.sleep(attempt+1)
    return None,'error:'+last

def period_end(facts,month):
    ds=[]
    for f in facts:
        if f['extra_dims']:continue
        x=dte(f.get('end')) or dte(f.get('instant'))
        if x and x.year==2015 and x.month==month:ds.append(x)
    return max(ds) if ds else None

def available_basis(facts,end):
    for b in ('CFS','OFS'):
        for f in facts:
            if f['basis']==b and not f['extra_dims'] and (dte(f.get('end'))==end or dte(f.get('instant'))==end): return b
    return ''
def duration_fact(facts,name,basis,end):
    xs=[]
    for f in facts:
        if f['name']!=name or f['basis']!=basis or f['extra_dims']:continue
        s=dte(f.get('start'));e=dte(f.get('end'))
        if s and e==end:xs.append(((e-s).days,f))
    if not xs:return None
    maxdur=max(x[0] for x in xs);chosen=[x[1] for x in xs if x[0]==maxdur]
    vals={x['value'] for x in chosen}
    return chosen[0] if len(vals)==1 else None
def instant_fact(facts,name,basis,end):
    xs=[f for f in facts if f['name']==name and f['basis']==basis and not f['extra_dims'] and dte(f.get('instant'))==end]
    vals={x['value'] for x in xs}
    return xs[0] if len(vals)==1 else None

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY required')
    if not UNIVERSE.exists():raise SystemExit(f'missing {UNIVERSE}')
    chunk=int(os.environ.get('DART_2015_XBRL_CHUNK','0'));size=int(os.environ.get('DART_2015_XBRL_CHUNK_SIZE','50'))
    if chunk<0 or size<1 or size>300:raise SystemExit('invalid chunk settings')
    u=pd.read_csv(UNIVERSE,dtype=str).fillna('')
    if 'is_earliest_corp_period' in u.columns:
        u=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')].copy()
    else:
        u=u.sort_values(['corp_code','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','period'],keep='first')
    u=u[u.period.isin(['Q1','H1','Q3','FY'])]
    corps=sorted(u.corp_code.astype(str).str.zfill(8).unique())
    chosen=corps[chunk*size:chunk*size+size]
    by={(str(r.corp_code).zfill(8),str(r.period)):r for _,r in u.iterrows() if str(r.corp_code).zfill(8) in set(chosen)}
    session=requests.Session();session.headers.update({'User-Agent':'SeolDoA-2015-PIT-XBRL-Historical/2.0'})
    rows=[];status=Counter();basis_counts=Counter();neg_capex=0
    for corp in chosen:
        prev={m:None for m in FLOW};prev_basis=None
        anyrow=next((r for (c,_),r in by.items() if c==corp),None)
        cname=anyrow.get('corp_name','') if anyrow is not None else ''
        stock=anyrow.get('stock_code','') if anyrow is not None else ''
        cls=anyrow.get('corp_cls','') if anyrow is not None else ''
        for q,month in PERIODS:
            src=by.get((corp,PERIOD_SOURCE[q]));rno=str(src.get('rcept_no','')) if src is not None else '';rd=str(src.get('rcept_dt','')) if src is not None else ''
            facts,st=fetch_xbrl(session,key,rno);status[f'{q}_{st}']+=1
            basis='';end=None;vals={m:None for m in TARGET};methods={m:'missing' for m in TARGET}
            if facts:
                end=period_end(facts,month);basis=available_basis(facts,end);basis_counts[basis]+=1
                for m,n in TARGET.items():
                    f=instant_fact(facts,n,basis,end) if m=='equity' else duration_fact(facts,n,basis,end)
                    if f:
                        v=f['value'];vals[m]=abs(v) if m in CAPEX else v;methods[m]='receipt_xbrl_fact'
            comparable=(q=='Q1') or bool(basis and prev_basis==basis)
            pure={};pure_method={}
            for m in TARGET:
                cur=vals[m]
                if m=='equity':pure[m]=cur;pure_method[m]='instant'
                elif q=='Q1':pure[m]=cur;pure_method[m]='direct_q1' if cur is not None else 'missing'
                else:
                    pv=prev.get(m)
                    if comparable and cur is not None and pv is not None:
                        d=cur-pv
                        if m in CAPEX and d<0:
                            pure[m]=None;pure_method[m]='negative_normalized_capex_delta_missing';neg_capex+=1
                        else:pure[m]=d;pure_method[m]='cumulative_difference'
                    else:pure[m]=None;pure_method[m]='missing_immediate_predecessor_or_basis_change'
            capex=(pure['capex_ppe']+pure['capex_intangible']) if pure['capex_ppe'] is not None and pure['capex_intangible'] is not None else None
            fcf=(pure['cfo']-capex) if pure['cfo'] is not None and capex is not None else None
            rows.append({'corp_code':corp,'company_name':cname,'stock_code':stock,'corp_cls':cls,'business_year':2015,'fiscal_quarter':q,
              'receipt_no':rno,'receipt_date':rd,'source_status':st,'source_type':'EARLIEST_PERIODIC_RECEIPT_XBRL','statement_basis':basis,'period_end':str(end) if end else '',
              'basis_comparable_to_immediate_predecessor':comparable,'operating_profit_cumulative':vals['operating_profit'],'operating_profit_q':pure['operating_profit'],
              'net_income_cumulative':vals['net_income'],'net_income_q':pure['net_income'],'equity_q_end':vals['equity'],'cfo_cumulative':vals['cfo'],'cfo_q':pure['cfo'],
              'capex_ppe_cumulative_spend':vals['capex_ppe'],'capex_ppe_q_spend':pure['capex_ppe'],'capex_intangible_cumulative_spend':vals['capex_intangible'],
              'capex_intangible_q_spend':pure['capex_intangible'],'capex_q_spend':capex,'fcf_q':fcf,'op_pure_method':pure_method['operating_profit'],
              'ni_pure_method':pure_method['net_income'],'cfo_pure_method':pure_method['cfo'],'capex_ppe_pure_method':pure_method['capex_ppe'],
              'capex_intangible_pure_method':pure_method['capex_intangible'],'signal_date_status':'NOT_ASSIGNED_ACCOUNTING_STAGE','modern_oos_protected':True})
            # Immediate-predecessor discipline: a missing period/metric must break the chain.
            for m in FLOW:prev[m]=vals[m]
            prev_basis=basis or None
    df=pd.DataFrame(rows)
    out=Path(f'korea_dart_quarterly_xbrl_2015_chunk{chunk:03d}.csv');summ=Path(f'korea_dart_quarterly_xbrl_2015_chunk{chunk:03d}_summary.json')
    df.to_csv(out,index=False)
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_2015_historical_pit_xbrl_collection','collector_version':'2.0','modern_oos_protected':True,
       'historical_universe_corps':len(corps),'chunk':chunk,'chunk_size':size,'chunk_corps':len(chosen),'output_rows':len(df),'source_status_counts':dict(status),
       'basis_counts':dict(basis_counts),'negative_normalized_capex_delta_cases':neg_capex,'op_q_populated':int(df.operating_profit_q.notna().sum()) if not df.empty else 0,
       'ni_q_populated':int(df.net_income_q.notna().sum()) if not df.empty else 0,'cfo_q_populated':int(df.cfo_q.notna().sum()) if not df.empty else 0,
       'fcf_q_populated':int(df.fcf_q.notna().sum()) if not df.empty else 0,'signal_dates_assigned':0,
       'important_limitation':'Accounting PIT reconstruction only. Earliest signal disclosure can precede the periodic report and must be confirmed candidate-only. KRX universe/mcap/tradability remain separate.'}
    summ.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
