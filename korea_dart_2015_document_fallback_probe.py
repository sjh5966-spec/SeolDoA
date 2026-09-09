#!/usr/bin/env python3
"""Probe original OpenDART filing ZIPs for 2015 quarterly reports.
Development-only; no prices/returns and no 2021+ data.
"""
from __future__ import annotations
import io, json, os, re, zipfile
from pathlib import Path
from collections import Counter
import requests

API='https://opendart.fss.or.kr/api'
OUT=Path('korea_dart_2015_document_fallback_probe.json')
CORP_CODES=['00100601','00100717','00100957','00101044','00101220','00101257','00101336','00101488','00101549','00101628','00101664','00101752','00102113','00102618','00102751','00102760','00102858','00103006','00103042','00103130']

# Historical DART uses generic '분기보고서' for both Q1 and Q3. Prefer fiscal-period text in report_nm;
# use receipt windows only as a fallback. Keep candidate lists for PIT audit.
PERIOD_RX={
    'Q1': re.compile(r'\(\s*2015[.\-/]?0?3\s*\)'),
    'H1': re.compile(r'\(\s*2015[.\-/]?0?6\s*\)'),
    'Q3': re.compile(r'\(\s*2015[.\-/]?0?9\s*\)'),
}
WINDOWS={
    'Q1': ('20150401','20150630'),
    'H1': ('20150701','20150930'),
    'Q3': ('20151001','20151231'),
}

def getj(s,key,path,**params):
    r=s.get(f'{API}/{path}',params={'crtfc_key':key,**params},timeout=60)
    r.raise_for_status(); return r.json()

def is_kind(q, report_nm):
    nm=str(report_nm or '')
    return ('반기보고서' in nm) if q=='H1' else ('분기보고서' in nm and '반기보고서' not in nm)

def classify(items,q):
    kind=[x for x in items if is_kind(q,x.get('report_nm'))]
    exact=[x for x in kind if PERIOD_RX[q].search(str(x.get('report_nm','')))]
    if exact:
        return sorted(exact,key=lambda x:str(x.get('rcept_no',''))), 'period_text'
    lo,hi=WINDOWS[q]
    win=[x for x in kind if lo <= str(x.get('rcept_dt','')) <= hi]
    return sorted(win,key=lambda x:str(x.get('rcept_no',''))), ('receipt_window' if win else 'none')

def decode_head(b):
    for enc in ('utf-8','cp949','euc-kr'):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return ''

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    s=requests.Session(); s.headers.update({'User-Agent':'SeolDoA-DART-2015-Document-Probe/1.1'})
    detail=[]; counts=Counter()
    for corp in CORP_CODES:
        d=getj(s,key,'list.json',corp_code=corp,bgn_de='20150101',end_de='20160531',page_count='100')
        items=d.get('list',[]) or []
        rec={'corp_code':corp,'list_status':d.get('status'),'list_rows':len(items),'quarters':{}}
        counts[f'list_status_{d.get("status")}']+=1
        for q in ('Q1','H1','Q3'):
            matches,method=classify(items,q)
            qrec={'match_method':method,'match_count':len(matches),'candidates':[{'rcept_no':x.get('rcept_no'),'rcept_dt':x.get('rcept_dt'),'report_nm':x.get('report_nm')} for x in matches[:20]]}
            if matches:
                chosen=matches[0]; rno=str(chosen.get('rcept_no',''))
                try:
                    rr=s.get(f'{API}/document.xml',params={'crtfc_key':key,'rcept_no':rno},timeout=120)
                    raw=rr.content; qrec['chosen_rcept_no']=rno; qrec['chosen_rcept_dt']=chosen.get('rcept_dt'); qrec['chosen_report_nm']=chosen.get('report_nm')
                    qrec['document_http']=rr.status_code; qrec['document_bytes']=len(raw); qrec['zip_magic']=raw[:2]==b'PK'
                    if raw[:2]==b'PK':
                        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                            names=zf.namelist(); qrec['zip_entries']=len(names); qrec['entry_names']=names[:30]
                            qrec['entry_samples']=[{'name':n,'head':decode_head(zf.read(n)[:4000])[:600]} for n in names[:8]]
                        counts[f'{q}_zip_ok']+=1
                    else: counts[f'{q}_document_not_zip']+=1
                except Exception as e:
                    qrec['document_error']=str(e); counts[f'{q}_document_error']+=1
            else: counts[f'{q}_no_match']+=1
            rec['quarters'][q]=qrec
        detail.append(rec)
    out={'research_stage':'development_2015_original_document_fallback_probe','version':'1.1','modern_oos_protected':True,'corp_count':len(CORP_CODES),'counts':dict(counts),'detail':detail}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'corp_count':len(CORP_CODES),'counts':dict(counts)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
