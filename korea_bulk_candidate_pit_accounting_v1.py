#!/usr/bin/env python3
"""Receipt-specific PIT accounting confirmation for bulk-discovered Korean Development candidates.

Scope is December-FYE 2017-2020 candidates only, because the existing historical-universe quarter labels are
calendar-month based and are reliable for Dec-FYE issuers. For each candidate, earliest original-like periodic
receipts for y-1 and y are fetched via fnlttXbrl.xml, cumulative flows are reconstructed with immediate-predecessor
same-basis discipline, and Base A is re-evaluated from original receipt data. Bulk values are comparison only.
No market returns and no 2021+/2023+ candidate data.
"""
from __future__ import annotations
import io,json,os,re,time,zipfile
from pathlib import Path
from collections import Counter
from datetime import date,datetime,timezone
import pandas as pd,requests
from lxml import etree

SRC=Path('korea_turnaround_bulk_base_a_2017_2020.csv')
API='https://opendart.fss.or.kr/api/fnlttXbrl.xml'
PERIODS=[('Q1',3),('Q2',6),('Q3',9),('Q4',12)];SOURCE={'Q1':'Q1','Q2':'H1','Q3':'Q3','Q4':'FY'};QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
TARGET={'op':'OperatingIncomeLoss','ni':'ProfitLoss','equity':'Equity','cfo':'CashFlowsFromUsedInOperatingActivities','ppe':'PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities','inta':'PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'}
FLOW={'op','ni','cfo','ppe','inta'};CAP={'ppe','inta'}

def ln(t):return str(t).split('}',1)[-1].split(':')[-1]
def txt(e):return ''.join(e.itertext()).strip()
def num(x):
 s=str(x or '').strip().replace(',','').replace('−','-')
 if s in ('','-','—'):return None
 try:return float(s)
 except:return None
def dt(s):
 try:return date.fromisoformat(str(s))
 except:return None
def bdim(ds):
 ms=[str(x.get('member') or '') for x in ds if 'ConsolidatedAndSeparateFinancialStatementsAxis' in str(x.get('dimension') or '')]
 if any('ConsolidatedMember' in m for m in ms):return 'CFS'
 if any('SeparateMember' in m for m in ms):return 'OFS'
 return ''
def extra(ds):return any('ConsolidatedAndSeparateFinancialStatementsAxis' not in str(x.get('dimension') or '') for x in ds)
def parse(raw):
 root=etree.fromstring(raw,parser=etree.XMLParser(recover=True,huge_tree=True));ctx={}
 for c in root.iter():
  if ln(c.tag)!='context':continue
  z={'start':None,'end':None,'instant':None,'dims':[]}
  for x in c.iter():
   n=ln(x.tag)
   if n=='startDate':z['start']=txt(x)
   elif n=='endDate':z['end']=txt(x)
   elif n=='instant':z['instant']=txt(x)
   elif n in ('explicitMember','typedMember'):z['dims'].append({'dimension':x.get('dimension'),'member':txt(x)})
  z['basis']=bdim(z['dims']);z['extra']=extra(z['dims']);ctx[c.get('id') or '']=z
 wanted=set(TARGET.values());facts=[]
 for e in root.iter():
  n=ln(e.tag)
  if n not in wanted:continue
  v=num(txt(e));c=ctx.get(e.get('contextRef') or '',{})
  if v is not None:facts.append({'name':n,'value':v,'start':c.get('start'),'end':c.get('end'),'instant':c.get('instant'),'basis':c.get('basis'),'extra':c.get('extra',False)})
 return facts
def fetch(s,key,rno):
 if not rno:return None,'no_receipt'
 last=''
 for a in range(5):
  try:
   r=s.get(API,params={'crtfc_key':key,'rcept_no':rno},timeout=120);raw=r.content
   if raw[:2]!=b'PK':return None,'no_xbrl_zip'
   with zipfile.ZipFile(io.BytesIO(raw)) as zf:
    ns=[n for n in zf.namelist() if n.lower().endswith('.xbrl')]
    if not ns:return None,'no_instance'
    n=max(ns,key=lambda q:zf.getinfo(q).file_size);return parse(zf.read(n)),'ok'
  except Exception as e:last=str(e);time.sleep(a+1)
 return None,'error:'+last
def pend(facts,year,month):
 ds=[]
 for f in facts or []:
  if f['extra']:continue
  x=dt(f.get('end')) or dt(f.get('instant'))
  if x and x.year==year and x.month==month:ds.append(x)
 return max(ds) if ds else None
def choose_basis(facts,end):
 for b in ('CFS','OFS'):
  if any(f['basis']==b and not f['extra'] and (dt(f.get('end'))==end or dt(f.get('instant'))==end) for f in facts or []):return b
 return ''
def dur(facts,name,b,end):
 xs=[]
 for f in facts or []:
  if f['name']!=name or f['basis']!=b or f['extra']:continue
  s=dt(f.get('start'));e=dt(f.get('end'))
  if s and e==end:xs.append(((e-s).days,f))
 if not xs:return None
 md=max(x[0] for x in xs);z=[x[1] for x in xs if x[0]==md];vals={x['value'] for x in z};return z[0] if len(vals)==1 else None
def inst(facts,name,b,end):
 z=[f for f in facts or [] if f['name']==name and f['basis']==b and not f['extra'] and dt(f.get('instant'))==end];vals={x['value'] for x in z};return z[0] if len(vals)==1 else None
def main():
 key=os.environ.get('DART_API_KEY','').strip()
 if not key:raise SystemExit('DART_API_KEY required')
 if not SRC.exists():raise SystemExit('bulk candidate file missing')
 c=pd.read_csv(SRC,dtype={'corp_code':str}).copy();c=c[c.business_year.astype(int).between(2017,2020)];c['corp_code']=c.corp_code.astype(str).str.zfill(8);c=c.sort_values(['business_year','corp_code','fiscal_quarter'])
 # Load all historical filing rows, identify Dec-FYE corp-years from true annual A001 at .12, and retain earliest period receipt.
 us=[]
 for y in range(2016,2021):
  p=Path(f'korea_dart_historical_universe_{y}.csv')
  if p.exists():us.append(pd.read_csv(p,dtype=str).fillna(''))
 u=pd.concat(us,ignore_index=True);u['corp_code']=u.corp_code.astype(str).str.zfill(8)
 dec={(r.corp_code,int(r.target_year)) for r in u.itertuples(index=False) if str(r.detail_type)=='A001' and str(r.period)=='FY'}
 ue=u[u.is_earliest_corp_period.astype(str).str.lower().eq('true')] if 'is_earliest_corp_period' in u else u.sort_values(['corp_code','target_year','period','rcept_dt','rcept_no']).drop_duplicates(['corp_code','target_year','period'])
 receipts={(r.corp_code,int(r.target_year),str(r.period)):(str(r.rcept_no),str(r.rcept_dt)) for r in ue.itertuples(index=False)}
 chunk=int(os.environ.get('PIT_ACCOUNTING_CHUNK','0'));size=int(os.environ.get('PIT_ACCOUNTING_CHUNK_SIZE','20'));part=c.iloc[chunk*size:chunk*size+size]
 sess=requests.Session();sess.headers['User-Agent']='SeolDoA-Korea-PIT-Accounting/1.0';cache={};status=Counter();out=[]
 for cr in part.itertuples(index=False):
  corp=cr.corp_code;y=int(cr.business_year);cq=str(cr.fiscal_quarter);isdec=(corp,y) in dec and (corp,y-1) in dec
  rec={'corp_code':corp,'company_name':cr.company_name,'stock_code':getattr(cr,'stock_code',''),'business_year':y,'fiscal_quarter':cq,'bulk_operating_profit_q':cr.operating_profit_q,'bulk_prior_year_same_q_operating_profit':cr.prior_year_same_q_operating_profit,'bulk_net_income_ttm':cr.net_income_ttm,'bulk_equity_q_end':cr.equity_q_end,'december_fye_current_and_prior':isdec,'modern_oos_protected':True}
  if not isdec:rec.update({'pit_accounting_status':'NON_DEC_FYE_PENDING','pit_base_a_confirmed':False});out.append(rec);continue
  qrows={};byseq={}
  for yy in (y-1,y):
   prev={m:None for m in FLOW};pb=None
   for q,month in PERIODS:
    rr=receipts.get((corp,yy,SOURCE[q]),('',''));rno,rd=rr
    ck=(rno,yy,month)
    if ck in cache:facts,st=cache[ck]
    else:facts,st=fetch(sess,key,rno);cache[ck]=(facts,st)
    status[st]+=1;end=pend(facts,yy,month) if facts else None;b=choose_basis(facts,end) if facts and end else ''
    vals={m:None for m in TARGET}
    if facts and b and end:
     for m,n in TARGET.items():
      f=inst(facts,n,b,end) if m=='equity' else dur(facts,n,b,end)
      if f:vals[m]=abs(f['value']) if m in CAP else f['value']
    comparable=(q=='Q1') or bool(b and pb==b);pure={}
    for m in TARGET:
     if m=='equity':pure[m]=vals[m]
     elif q=='Q1':pure[m]=vals[m]
     elif comparable and vals[m] is not None and prev.get(m) is not None:
      d=vals[m]-prev[m];pure[m]=None if m in CAP and d<0 else d
     else:pure[m]=None
    cap=(pure['ppe']+pure['inta']) if pure['ppe'] is not None and pure['inta'] is not None else None;fcf=(pure['cfo']-cap) if pure['cfo'] is not None and cap is not None else None
    z={'year':yy,'quarter':q,'seq':yy*4+QORD[q],'receipt_no':rno,'receipt_date':rd,'source_status':st,'statement_basis':b,'op_q':pure['op'],'ni_q':pure['ni'],'equity':pure['equity'],'cfo_q':pure['cfo'],'capex_q':cap,'fcf_q':fcf};qrows[(yy,q)]=z;byseq[z['seq']]=z
    for m in FLOW:prev[m]=vals[m]
    pb=b or None
  cur=qrows.get((y,cq));prior=qrows.get((y-1,cq));seq=y*4+QORD[cq];four=[byseq.get(s) for s in range(seq-3,seq+1)]
  exact=all(x is not None for x in four);bases=[x['statement_basis'] for x in four] if exact else [];same=bool(exact and len(set(bases))==1 and bases[0]);nis=[x['ni_q'] if x else None for x in four];nittm=sum(nis) if same and all(x is not None for x in nis) else None
  op=cur['op_q'] if cur else None;pop=prior['op_q'] if prior else None;eq=cur['equity'] if cur else None;turn=bool(op is not None and pop is not None and op>0 and pop<=0);base=bool(turn and nittm is not None and nittm<0 and eq is not None and eq>0)
  rec.update({'pit_accounting_status':'CONFIRMED' if base else 'FAILED_OR_INCOMPLETE','pit_operating_profit_q':op,'pit_prior_year_same_q_operating_profit':pop,'pit_net_income_ttm':nittm,'pit_equity_q_end':eq,'pit_fcf_q':cur['fcf_q'] if cur else None,'pit_statement_basis':cur['statement_basis'] if cur else '', 'ttm_same_basis':same,'pit_base_a_confirmed':base,'current_receipt_no':cur['receipt_no'] if cur else '','current_receipt_date':cur['receipt_date'] if cur else '','quarter_audit_json':json.dumps(list(qrows.values()),ensure_ascii=False)})
  out.append(rec)
 o=pd.DataFrame(out);of=Path(f'korea_bulk_candidate_pit_accounting_v1_chunk{chunk:03d}.csv');sf=Path(f'korea_bulk_candidate_pit_accounting_v1_chunk{chunk:03d}_summary.json');o.to_csv(of,index=False)
 sm={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_candidate_receipt_specific_pit_accounting_confirmation','modern_oos_protected':True,'total_bulk_candidates':len(c),'chunk':chunk,'chunk_size':size,'chunk_rows':len(o),'dec_fye_rows':int(o.december_fye_current_and_prior.sum()) if len(o) else 0,'pit_base_a_confirmed':int(o.pit_base_a_confirmed.sum()) if len(o) else 0,'source_status_counts':dict(status),'critical_limitation':'Only December-FYE candidates are confirmed in v1. Signal-date precedence is separate; a candidate must also pass earliest-public-disclosure confirmation before returns are final.'};sf.write_text(json.dumps(sm,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(sm,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
