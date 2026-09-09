#!/usr/bin/env python3
"""Candidate-only earliest DART disclosure probe for Development accounting candidates.
No KRX prices/returns. Searches only 2015-2020 accounting candidates and preserves receipt audit trail.
"""
from __future__ import annotations
import io,json,os,re,zipfile,time
from pathlib import Path
from collections import Counter
import pandas as pd
import requests

SRC=Path('korea_turnaround_accounting_candidates_v2.csv')
OUT=Path('korea_candidate_signal_probe_v1.json')
API='https://opendart.fss.or.kr/api'
TITLE_HINTS=('잠정','영업(잠정)','매출액또는손익구조','실적','분기보고서','반기보고서','사업보고서')

def getj(s,key,path,**p):
    for a in range(4):
        r=s.get(f'{API}/{path}',params={'crtfc_key':key,**p},timeout=60);r.raise_for_status();d=r.json();st=str(d.get('status',''))
        if st in ('000','013'):return d
        if st=='020':time.sleep(2*(a+1));continue
        return d
    return {'status':'retry_exhausted','list':[]}
def normtxt(b):
    for enc in ('utf-8','cp949','euc-kr'):
        try:return b.decode(enc)
        except:pass
    return b.decode('utf-8','replace')
def inspect_doc(s,key,rno,target_op):
    r=s.get(f'{API}/document.xml',params={'crtfc_key':key,'rcept_no':rno},timeout=120);raw=r.content
    rec={'http_status':r.status_code,'bytes':len(raw),'zip_magic':raw[:2]==b'PK'}
    if raw[:2]!=b'PK':rec['response_head']=normtxt(raw[:1200]);return rec
    hits=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        rec['entries']=len(zf.namelist())
        for n in zf.namelist():
            if not n.lower().endswith(('.xml','.html','.htm','.txt')):continue
            try:t=normtxt(zf.read(n))
            except:continue
            plain=re.sub(r'<[^>]+>',' ',t);plain=re.sub(r'\s+',' ',plain)
            has_op='영업이익' in plain or '영업손실' in plain or '영업손익' in plain
            # Exact amount can differ by unit/rounding in preliminary disclosures; keep both exact and label evidence.
            digits=re.sub(r'[^0-9-]','',str(int(abs(target_op)))) if target_op is not None else ''
            compact=re.sub(r'[^0-9-]','',plain)
            exact_amount=bool(digits and digits in compact)
            if has_op:
                pos=min([p for p in (plain.find('영업이익'),plain.find('영업손실'),plain.find('영업손익')) if p>=0] or [0])
                hits.append({'entry':n,'has_op_label':True,'exact_abs_amount_digits':exact_amount,'snippet':plain[max(0,pos-220):pos+500]})
        rec['op_label_entries']=len(hits);rec['exact_amount_entries']=sum(1 for x in hits if x['exact_abs_amount_digits']);rec['hits']=hits[:20]
    return rec

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY required')
    d=pd.read_csv(SRC,dtype={'corp_code':str});d=d[d.base_a_accounting_only.eq(True)].copy()
    d=d[d.business_year.astype(int).between(2015,2020)]
    s=requests.Session();s.headers.update({'User-Agent':'SeolDoA-Candidate-Signal-Probe/1.0'})
    detail=[];counts=Counter()
    for r in d.itertuples(index=False):
        corp=str(r.corp_code).zfill(8);y=int(r.business_year);q=str(r.fiscal_quarter);op=float(r.operating_profit_q)
        # Search from quarter start through 90 days after quarter end; broad enough for preliminary + periodic filing.
        qdates={'Q1':(f'{y}0101',f'{y}0630'),'Q2':(f'{y}0401',f'{y}0930'),'Q3':(f'{y}0701',f'{y}1231'),'Q4':(f'{y}1001',f'{y+1}0430')}
        b,e=qdates[q];lj=getj(s,key,'list.json',corp_code=corp,bgn_de=b,end_de=e,page_count='100')
        items=lj.get('list') or [];cands=[]
        for x in items:
            title=str(x.get('report_nm') or '')
            if not any(h in title for h in TITLE_HINTS):continue
            cands.append({'rcept_no':str(x.get('rcept_no') or ''),'rcept_dt':str(x.get('rcept_dt') or ''),'report_nm':title,'corp_cls':x.get('corp_cls'),'flr_nm':x.get('flr_nm')})
        cands=sorted(cands,key=lambda x:(x['rcept_dt'],x['rcept_no']))
        inspected=[]
        for x in cands[:30]:
            z=dict(x)
            try:z['document']=inspect_doc(s,key,x['rcept_no'],op);counts['documents_checked']+=1
            except Exception as ex:z['document']={'error':str(ex)};counts['document_errors']+=1
            inspected.append(z)
        # Confirmation hierarchy: earliest title/doc containing op-profit label; exact amount strengthens but is not required yet.
        label_hits=[x for x in inspected if (x.get('document') or {}).get('op_label_entries',0)>0]
        exact_hits=[x for x in label_hits if (x.get('document') or {}).get('exact_amount_entries',0)>0]
        chosen=(exact_hits[0] if exact_hits else (label_hits[0] if label_hits else None))
        detail.append({'corp_code':corp,'company_name':getattr(r,'company_name',''),'business_year':y,'fiscal_quarter':q,'target_operating_profit_q':op,'list_status':lj.get('status'),'candidate_titles':len(cands),'inspected':inspected,'earliest_op_label_candidate':{'rcept_no':chosen['rcept_no'],'rcept_dt':chosen['rcept_dt'],'report_nm':chosen['report_nm'],'exact_amount_match':chosen in exact_hits} if chosen else None,'signal_date_status':'CANDIDATE_ONLY_CONTENT_PROBE_NOT_FINAL'})
        counts['base_a_candidates']+=1;counts['with_op_label_candidate']+=bool(chosen);counts['with_exact_amount_candidate']+=bool(exact_hits)
    obj={'research_stage':'development_candidate_only_signal_content_probe','modern_oos_protected':True,'counts':dict(counts),'detail':detail,'important_limitation':'This probe narrows earliest disclosure candidates using original DART document content. Final signal date requires verifying the disclosure actually communicates the relevant pure-quarter operating-profit information and handling corrections/preliminary-vs-periodic precedence.'}
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'counts':dict(counts),'signals':[x.get('earliest_op_label_candidate') for x in detail]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
