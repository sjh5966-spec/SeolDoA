#!/usr/bin/env python3
"""2015 Development quarterly accounting reconstruction from original filing XBRL.

PIT source: receipt-specific OpenDART fnlttXbrl.xml ZIPs discovered from original periodic filings.
Selection:
- explicit ConsolidatedMember preferred; SeparateMember fallback; no silent basis mixing.
- current duration fact = longest current-period duration ending at the filing's fiscal-period end.
- equity = current-period instant total Equity with no component-of-equity dimension.
- Q1 direct, Q2=H1-Q1, Q3=9M-H1.
- Q4 is optionally fetched from FY full-financial API and differenced from Q3 on same basis.
- CAPEX standardized PPE/intangible purchase facts; no qualifying standardized fact on an otherwise valid CF context is treated as zero observed spend.
No KRX prices/returns; no signal date assignment; no 2021+/2023+ data.
"""
from __future__ import annotations
import io,json,os,re,time,zipfile
from pathlib import Path
from datetime import date,datetime,timezone
from collections import Counter
import pandas as pd
import requests
from lxml import etree

SRC=Path('korea_dart_2015_document_fallback_probe.json')
OUT=Path('korea_dart_quarterly_xbrl_2015.csv')
SUM=Path('korea_dart_quarterly_xbrl_2015_summary.json')
XBRL_API='https://opendart.fss.or.kr/api/fnlttXbrl.xml'
FULL_API='https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
TARGET={
 'operating_profit':'OperatingIncomeLoss',
 'net_income':'ProfitLoss',
 'equity':'Equity',
 'cfo':'CashFlowsFromUsedInOperatingActivities',
 'capex_ppe':'PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
 'capex_intangible':'PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities',
}
FULL_IDS={
 'operating_profit':'dart_OperatingIncomeLoss','net_income':'ifrs_ProfitLoss','equity':'ifrs_Equity',
 'cfo':'ifrs_CashFlowsFromUsedInOperatingActivities',
 'capex_ppe':'ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
 'capex_intangible':'ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'}
FLOW={'operating_profit','net_income','cfo','capex_ppe','capex_intangible'}

def ln(t):
    if not isinstance(t,str): return ''
    return t.split('}',1)[-1] if '}' in t else t.split(':')[-1]
def txt(e): return ''.join(e.itertext()).strip()
def num(x):
    s=str(x or '').strip().replace(',','').replace('−','-')
    if s in ('','-','—'): return None
    try:return float(s)
    except:return None
def iso(s):
    try:return date.fromisoformat(str(s))
    except:return None
def basis_of_dims(dims):
    members=[str(x.get('member') or '') for x in dims if 'ConsolidatedAndSeparateFinancialStatementsAxis' in str(x.get('dimension') or '')]
    if any('ConsolidatedMember' in m for m in members): return 'CFS'
    if any('SeparateMember' in m for m in members): return 'OFS'
    return ''
def has_extra_dims(dims):
    return any('ConsolidatedAndSeparateFinancialStatementsAxis' not in str(x.get('dimension') or '') for x in dims)

def parse_instance(raw):
    root=etree.fromstring(raw,parser=etree.XMLParser(recover=True,huge_tree=True))
    ctx={}
    for c in root.iter():
        if ln(c.tag)!='context': continue
        r={'start':None,'end':None,'instant':None,'dims':[]}
        for x in c.iter():
            n=ln(x.tag)
            if n=='startDate':r['start']=txt(x)
            elif n=='endDate':r['end']=txt(x)
            elif n=='instant':r['instant']=txt(x)
            elif n in ('explicitMember','typedMember'):r['dims'].append({'dimension':x.get('dimension'),'member':txt(x)})
        r['basis']=basis_of_dims(r['dims']);r['extra_dims']=has_extra_dims(r['dims']);ctx[c.get('id') or '']=r
    facts=[]
    wanted=set(TARGET.values())
    for e in root.iter():
        n=ln(e.tag)
        if n not in wanted: continue
        c=ctx.get(e.get('contextRef') or '',{})
        v=num(txt(e))
        if v is None: continue
        facts.append({'name':n,'value':v,'context':e.get('contextRef'),'start':c.get('start'),'end':c.get('end'),'instant':c.get('instant'),'basis':c.get('basis'),'extra_dims':c.get('extra_dims',False),'dims':c.get('dims',[])})
    return facts

def current_end(facts,q):
    # Among non-extra-dimensional current-year contexts, choose latest endpoint consistent with period label.
    candidates=[]
    for f in facts:
        s=iso(f.get('start')); e=iso(f.get('end')); i=iso(f.get('instant'))
        d=e or i
        if d and d.year==2015: candidates.append(d)
    if not candidates:return None
    month={'Q1':3,'H1':6,'Q3':9}.get(q)
    exact=[d for d in candidates if d.month==month]
    return max(exact) if exact else max(candidates)

def choose_basis(facts,end):
    for b in ('CFS','OFS'):
        for f in facts:
            if f['basis']!=b or f['extra_dims']:continue
            if f['name'] not in {TARGET['operating_profit'],TARGET['net_income'],TARGET['equity']}:continue
            d=iso(f.get('end')) or iso(f.get('instant'))
            if d==end:return b
    return ''
def select_duration(facts,name,basis,end):
    xs=[]
    for f in facts:
        if f['name']!=name or f['basis']!=basis or f['extra_dims']:continue
        s=iso(f.get('start')); e=iso(f.get('end'))
        if s and e==end: xs.append((e-s,f))
    if not xs:return None
    maxdur=max(x[0] for x in xs); vals=[x[1] for x in xs if x[0]==maxdur]
    uniq={x['value'] for x in vals}
    if len(uniq)!=1:return None
    return vals[0]
def select_instant(facts,name,basis,end):
    xs=[f for f in facts if f['name']==name and f['basis']==basis and not f['extra_dims'] and iso(f.get('instant'))==end]
    uniq={x['value'] for x in xs}
    if len(uniq)!=1:return None
    return xs[0]
def fetch_xbrl(session,key,rno):
    for a in range(4):
        try:
            r=session.get(XBRL_API,params={'crtfc_key':key,'rcept_no':rno},timeout=120);raw=r.content
            if raw[:2]!=b'PK':return None,'no_xbrl_zip'
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names=[n for n in zf.namelist() if n.lower().endswith('.xbrl')]
                if not names:return None,'no_instance'
                n=max(names,key=lambda x:zf.getinfo(x).file_size)
                return parse_instance(zf.read(n)),'ok'
        except Exception as e:
            last=str(e);time.sleep(a+1)
    return None,'error:'+last

def fy_api(session,key,corp,basis):
    fs=basis
    for a in range(4):
        try:
            r=session.get(FULL_API,params={'crtfc_key':key,'corp_code':corp,'bsns_year':'2015','reprt_code':'11011','fs_div':fs},timeout=60);r.raise_for_status();d=r.json()
            if str(d.get('status'))=='000':return d.get('list') or [],'ok'
            if str(d.get('status'))=='013':return [],'no_data'
            time.sleep(a+1)
        except Exception as e:last=str(e);time.sleep(a+1)
    return [],'error'
def fy_metric(items,m):
    sect={'operating_profit':{'IS','CIS'},'net_income':{'IS','CIS'},'equity':{'BS'},'cfo':{'CF'},'capex_ppe':{'CF'},'capex_intangible':{'CF'}}[m]
    xs=[x for x in items if str(x.get('sj_div') or '') in sect and str(x.get('account_id') or '')==FULL_IDS[m]]
    if m.startswith('capex_'):
        vals=[];seen=set()
        for x in xs:
            k=(x.get('account_id'),x.get('account_nm'),x.get('thstrm_amount'))
            if k in seen:continue
            seen.add(k);v=num(x.get('thstrm_amount'))
            if v is not None:vals.append(v)
        return sum(vals) if vals else 0.0
    if len(xs)==1:return num(xs[0].get('thstrm_amount'))
    # exact standardized duplicates with same value are acceptable
    vals={num(x.get('thstrm_amount')) for x in xs if num(x.get('thstrm_amount')) is not None}
    return next(iter(vals)) if len(vals)==1 else None

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY required')
    src=json.loads(SRC.read_text(encoding='utf-8'));session=requests.Session();session.headers.update({'User-Agent':'SeolDoA-2015-PIT-XBRL-Collector/1.0'})
    rows=[];status=Counter();basis_counts=Counter()
    for rec in src.get('detail',[]):
        corp=str(rec.get('corp_code') or '').zfill(8);prev={m:None for m in FLOW};prev_basis=None;company=''
        for q in ('Q1','H1','Q3'):
            qs=(rec.get('quarters') or {}).get(q) or {};cands=qs.get('candidates') or []
            rno=str(cands[0].get('rcept_no') or '') if cands else '';rd=str(cands[0].get('rcept_dt') or '') if cands else ''
            facts,st=fetch_xbrl(session,key,rno) if rno else (None,'no_receipt');status[q+'_'+st]+=1
            if not facts:
                rows.append({'corp_code':corp,'business_year':2015,'fiscal_quarter':{'Q1':'Q1','H1':'Q2','Q3':'Q3'}[q],'receipt_no':rno,'receipt_date':rd,'source_status':st,'statement_basis':'','modern_oos_protected':True});continue
            end=current_end(facts,q);basis=choose_basis(facts,end);basis_counts[basis]+=1
            vals={}
            for m,n in TARGET.items():
                f=select_instant(facts,n,basis,end) if m=='equity' else select_duration(facts,n,basis,end)
                vals[m]=f['value'] if f else (0.0 if m.startswith('capex_') and select_duration(facts,TARGET['cfo'],basis,end) else None)
            comparable=(q=='Q1') or (basis and prev_basis==basis)
            pure={}
            for m in FLOW:
                if q=='Q1':pure[m]=vals[m]
                elif comparable and vals[m] is not None and prev[m] is not None:pure[m]=vals[m]-prev[m]
                else:pure[m]=None
            ppe=abs(pure['capex_ppe']) if pure['capex_ppe'] is not None else None;inta=abs(pure['capex_intangible']) if pure['capex_intangible'] is not None else None;capex=ppe+inta if ppe is not None and inta is not None else None
            rows.append({'corp_code':corp,'business_year':2015,'fiscal_quarter':{'Q1':'Q1','H1':'Q2','Q3':'Q3'}[q],'receipt_no':rno,'receipt_date':rd,'source_status':st,'statement_basis':basis,'period_end':str(end) if end else '',
              'operating_profit_cumulative':vals['operating_profit'],'operating_profit_q':pure['operating_profit'],'net_income_cumulative':vals['net_income'],'net_income_q':pure['net_income'],'equity_q_end':vals['equity'],'cfo_cumulative':vals['cfo'],'cfo_q':pure['cfo'],'capex_ppe_cumulative':vals['capex_ppe'],'capex_ppe_q_spend':ppe,'capex_intangible_cumulative':vals['capex_intangible'],'capex_intangible_q_spend':inta,'capex_q_spend':capex,'fcf_q':pure['cfo']-capex if pure['cfo'] is not None and capex is not None else None,'basis_comparable_to_immediate_predecessor':bool(comparable),'signal_date_status':'NOT_ASSIGNED_ACCOUNTING_STAGE','source_type':'ORIGINAL_RECEIPT_XBRL','modern_oos_protected':True})
            for m in FLOW:
                if vals[m] is not None:prev[m]=vals[m]
            if basis:prev_basis=basis
        # Q4 from FY full API, only on same basis as Q3; accounting snapshot, not signal-date source.
        basis=prev_basis or 'CFS';items,st=fy_api(session,key,corp,basis);status['Q4_'+st]+=1
        vals={m:fy_metric(items,m) for m in TARGET} if items else {m:None for m in TARGET}
        comparable=bool(items and prev_basis==basis)
        pure={m:(vals[m]-prev[m] if comparable and vals[m] is not None and prev[m] is not None else None) for m in FLOW}
        ppe=abs(pure['capex_ppe']) if pure['capex_ppe'] is not None else None;inta=abs(pure['capex_intangible']) if pure['capex_intangible'] is not None else None;capex=ppe+inta if ppe is not None and inta is not None else None
        rows.append({'corp_code':corp,'business_year':2015,'fiscal_quarter':'Q4','receipt_no':'','receipt_date':'','source_status':st,'statement_basis':basis,
          'operating_profit_cumulative':vals['operating_profit'],'operating_profit_q':pure['operating_profit'],'net_income_cumulative':vals['net_income'],'net_income_q':pure['net_income'],'equity_q_end':vals['equity'],'cfo_cumulative':vals['cfo'],'cfo_q':pure['cfo'],'capex_ppe_cumulative':vals['capex_ppe'],'capex_ppe_q_spend':ppe,'capex_intangible_cumulative':vals['capex_intangible'],'capex_intangible_q_spend':inta,'capex_q_spend':capex,'fcf_q':pure['cfo']-capex if pure['cfo'] is not None and capex is not None else None,'basis_comparable_to_immediate_predecessor':comparable,'signal_date_status':'NOT_ASSIGNED_ACCOUNTING_STAGE','source_type':'FY_FULL_API_ACCOUNTING_ONLY','modern_oos_protected':True})
    df=pd.DataFrame(rows);df.to_csv(OUT,index=False)
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_2015_pit_xbrl_accounting_collection','modern_oos_protected':True,'corp_count':len(src.get('detail',[])),'output_rows':len(df),'source_status_counts':dict(status),'basis_counts':dict(basis_counts),'op_q_populated':int(df.get('operating_profit_q',pd.Series(dtype=float)).notna().sum()),'ni_q_populated':int(df.get('net_income_q',pd.Series(dtype=float)).notna().sum()),'cfo_q_populated':int(df.get('cfo_q',pd.Series(dtype=float)).notna().sum()),'fcf_q_populated':int(df.get('fcf_q',pd.Series(dtype=float)).notna().sum()),'q4_op_populated':int(df.loc[df.fiscal_quarter.eq('Q4'),'operating_profit_q'].notna().sum()),'signal_dates_assigned':0,'important_limitation':'2015 sample collector. Q1-Q3 are receipt-specific PIT XBRL; Q4 uses FY full API accounting snapshot and still requires candidate-only original filing/disclosure confirmation.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
