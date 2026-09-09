#!/usr/bin/env python3
"""Probe original OpenDART filing ZIPs for 2015 quarterly reports.
Development-only; no prices/returns and no 2021+ data.
"""
from __future__ import annotations
import io, json, os, re, zipfile
from pathlib import Path
from collections import Counter
import pandas as pd
import requests

API='https://opendart.fss.or.kr/api'
SEED=Path('korea_dart_quarterly_seed_2015_2020.csv')
OUT=Path('korea_dart_2015_document_fallback_probe.json')
TARGETS={'Q1':'1분기보고서','H1':'반기보고서','Q3':'3분기보고서'}

def getj(s,key,path,**params):
    r=s.get(f'{API}/{path}',params={'crtfc_key':key,**params},timeout=60)
    r.raise_for_status(); return r.json()

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    seed=pd.read_csv(SEED,dtype=str).fillna('')
    # If the current smoke seed is not 2015, use the known 2015 diagnostic corp list.
    corp_codes=['00100601','00100717','00100957','00101044','00101220','00101257','00101336','00101488','00101549','00101628','00101664','00101752','00102113','00102618','00102751','00102760','00102858','00103006','00103042','00103130']
    s=requests.Session(); s.headers.update({'User-Agent':'SeolDoA-DART-2015-Document-Probe/1.0'})
    detail=[]; counts=Counter()
    for corp in corp_codes:
        d=getj(s,key,'list.json',corp_code=corp,bgn_de='20150101',end_de='20160531',page_count='100')
        items=d.get('list',[]) or []
        rec={'corp_code':corp,'list_status':d.get('status'),'list_rows':len(items),'quarters':{}}
        counts[f'list_status_{d.get("status")}']+=1
        for q,label in TARGETS.items():
            matches=[x for x in items if label in str(x.get('report_nm','')) and '2015' not in '']
            # Prefer the earliest receipt carrying the target periodic-report label; retain all candidates for audit.
            matches=sorted(matches,key=lambda x:str(x.get('rcept_no','')))
            qrec={'match_count':len(matches),'candidates':[{'rcept_no':x.get('rcept_no'),'rcept_dt':x.get('rcept_dt'),'report_nm':x.get('report_nm')} for x in matches[:20]]}
            if matches:
                chosen=matches[0]; rno=str(chosen.get('rcept_no',''))
                try:
                    rr=s.get(f'{API}/document.xml',params={'crtfc_key':key,'rcept_no':rno},timeout=120)
                    raw=rr.content; qrec['document_http']=rr.status_code; qrec['document_bytes']=len(raw); qrec['zip_magic']=raw[:2]==b'PK'
                    if raw[:2]==b'PK':
                        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                            names=zf.namelist(); qrec['zip_entries']=len(names); qrec['entry_names']=names[:30]
                            sample=[]
                            for n in names[:10]:
                                try:
                                    b=zf.read(n)[:4000]
                                    txt=None
                                    for enc in ('utf-8','cp949','euc-kr'):
                                        try: txt=b.decode(enc); break
                                        except UnicodeDecodeError: pass
                                    sample.append({'name':n,'head':(txt or '')[:600]})
                                except Exception as e: sample.append({'name':n,'error':str(e)})
                            qrec['entry_samples']=sample
                        counts[f'{q}_zip_ok']+=1
                    else:
                        counts[f'{q}_document_not_zip']+=1
                except Exception as e:
                    qrec['document_error']=str(e); counts[f'{q}_document_error']+=1
            else: counts[f'{q}_no_match']+=1
            rec['quarters'][q]=qrec
        detail.append(rec)
    out={'research_stage':'development_2015_original_document_fallback_probe','modern_oos_protected':True,'corp_count':len(corp_codes),'counts':dict(counts),'detail':detail}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'corp_count':len(corp_codes),'counts':dict(counts)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
