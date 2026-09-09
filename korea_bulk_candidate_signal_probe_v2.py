#!/usr/bin/env python3
"""Chunked original-DART signal-content probe for bulk-discovered Korea Development candidates.

This does NOT trust bulk snapshot values as PIT truth. It searches the candidate issuer's public disclosures
around the fiscal quarter and inspects original document ZIPs for operating-profit evidence. The output
provides an earliest-content candidate; accounting PIT values still require original-receipt XBRL confirmation.
No 2021+ candidate events or 2023+ data are accessed.
"""
from __future__ import annotations
import io,json,os,re,time,zipfile
from pathlib import Path
from collections import Counter
import pandas as pd,requests

SRC=Path('korea_turnaround_bulk_base_a_2017_2020.csv')
API='https://opendart.fss.or.kr/api'
TITLE_HINTS=('잠정','영업(잠정)','매출액또는손익구조','실적','분기보고서','반기보고서','사업보고서')

def getj(s,key,path,**p):
 for a in range(5):
  try:
   r=s.get(f'{API}/{path}',params={'crtfc_key':key,**p},timeout=60);r.raise_for_status();d=r.json();st=str(d.get('status',''))
   if st in ('000','013'):return d
   if st=='020':time.sleep(3*(a+1));continue
   return d
  except Exception:
   time.sleep(a+1)
 return {'status':'request_failed','list':[]}
def dec(b):
 for e in ('utf-8','cp949','euc-kr'):
  try:return b.decode(e)
  except:pass
 return b.decode('utf-8','replace')
def inspect(s,key,rno,target):
 r=s.get(f'{API}/document.xml',params={'crtfc_key':key,'rcept_no':rno},timeout=120);raw=r.content;z={'http_status':r.status_code,'bytes':len(raw),'zip_magic':raw[:2]==b'PK'}
 if raw[:2]!=b'PK':return z
 hits=[];digits=re.sub(r'[^0-9]','',str(int(abs(target)))) if target is not None else ''
 with zipfile.ZipFile(io.BytesIO(raw)) as zf:
  for n in zf.namelist():
   if not n.lower().endswith(('.xml','.html','.htm','.txt')):continue
   try:t=dec(zf.read(n))
   except:continue
   plain=re.sub(r'<[^>]+>',' ',t);plain=re.sub(r'\s+',' ',plain)
   poss=[plain.find(k) for k in ('영업이익','영업손실','영업손익') if plain.find(k)>=0]
   if not poss:continue
   p=min(poss);compact=re.sub(r'[^0-9]','',plain);hits.append({'entry':n,'exact_abs_amount_digits':bool(digits and digits in compact),'snippet':plain[max(0,p-180):p+420]})
 z['op_label_entries']=len(hits);z['exact_amount_entries']=sum(x['exact_abs_amount_digits'] for x in hits);z['hits']=hits[:6];return z
def main():
 key=os.environ.get('DART_API_KEY','').strip()
 if not key:raise SystemExit('DART_API_KEY required')
 if not SRC.exists():raise SystemExit('bulk Base A candidate file missing')
 d=pd.read_csv(SRC,dtype={'corp_code':str}).copy();d=d[d.business_year.astype(int).between(2017,2020)].sort_values(['business_year','corp_code','fiscal_quarter'])
 chunk=int(os.environ.get('SIGNAL_CHUNK','0'));size=int(os.environ.get('SIGNAL_CHUNK_SIZE','25'));part=d.iloc[chunk*size:chunk*size+size]
 s=requests.Session();s.headers['User-Agent']='SeolDoA-Korea-Candidate-Signal/2.0';detail=[];cnt=Counter()
 for r in part.itertuples(index=False):
  corp=str(r.corp_code).zfill(8);y=int(r.business_year);q=str(r.fiscal_quarter);op=float(r.operating_profit_q)
  # Broad search starts at quarter start; final event must still actually communicate that quarter's information.
  dates={'Q1':(f'{y}0101',f'{y}0630'),'Q2':(f'{y}0401',f'{y}0930'),'Q3':(f'{y}0701',f'{y}1231'),'Q4':(f'{y}1001',f'{y+1}0430')};b,e=dates[q]
  lj=getj(s,key,'list.json',corp_code=corp,bgn_de=b,end_de=e,page_count='100');items=[]
  for x in lj.get('list') or []:
   title=str(x.get('report_nm') or '')
   if any(h in title for h in TITLE_HINTS):items.append({'rcept_no':str(x.get('rcept_no') or ''),'rcept_dt':str(x.get('rcept_dt') or ''),'report_nm':title,'corp_cls':x.get('corp_cls')})
  items=sorted(items,key=lambda x:(x['rcept_dt'],x['rcept_no']));ins=[]
  for x in items[:20]:
   z=dict(x)
   try:z['document']=inspect(s,key,x['rcept_no'],op);cnt['documents_checked']+=1
   except Exception as ex:z['document']={'error':str(ex)};cnt['document_errors']+=1
   ins.append(z)
  # Exact amount is stronger. A label-only earlier disclosure is retained but not treated as exact confirmation.
  exact=[x for x in ins if (x.get('document') or {}).get('exact_amount_entries',0)>0]
  label=[x for x in ins if (x.get('document') or {}).get('op_label_entries',0)>0]
  chosen=exact[0] if exact else (label[0] if label else None)
  detail.append({'corp_code':corp,'company_name':r.company_name,'business_year':y,'fiscal_quarter':q,'target_bulk_op_q':op,'candidate_titles':len(items),'inspected':ins,'earliest_op_content_candidate':({'rcept_no':chosen['rcept_no'],'rcept_dt':chosen['rcept_dt'],'report_nm':chosen['report_nm'],'exact_amount_match':chosen in exact} if chosen else None),'pit_accounting_confirmed':False,'signal_date_status':'CONTENT_CANDIDATE_NOT_FINAL'})
  cnt['candidates']+=1;cnt['with_label']+=bool(label);cnt['with_exact']+=bool(exact)
 out=Path(f'korea_bulk_candidate_signal_probe_v2_chunk{chunk:03d}.json');obj={'research_stage':'development_bulk_candidate_original_disclosure_probe','modern_oos_protected':True,'chunk':chunk,'chunk_size':size,'total_candidates':len(d),'counts':dict(cnt),'detail':detail,'critical_limitation':'Bulk target amounts can reflect later corrections. Exact amount match is evidence, not final PIT accounting confirmation; original receipt-specific XBRL/account sequence must also pass.'};out.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'total_candidates':len(d),'chunk':chunk,'counts':dict(cnt)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
