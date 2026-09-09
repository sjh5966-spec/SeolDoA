#!/usr/bin/env python3
"""Probe OpenDART original XBRL ZIP availability for 2015 quarterly filings.
Development-only. No KRX prices/returns. No 2021+ or 2023+ data.
"""
from __future__ import annotations
import io, json, os, zipfile
from pathlib import Path
from collections import Counter
import requests

SRC=Path('korea_dart_2015_document_fallback_probe.json')
OUT=Path('korea_dart_2015_xbrl_probe.json')
API='https://opendart.fss.or.kr/api'

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    if not SRC.exists(): raise SystemExit(f'missing {SRC}')
    src=json.loads(SRC.read_text(encoding='utf-8'))
    s=requests.Session(); s.headers.update({'User-Agent':'SeolDoA-DART-2015-XBRL-Probe/1.0'})
    counts=Counter(); detail=[]
    for rec in src.get('detail',[]):
        corp=rec.get('corp_code'); outrec={'corp_code':corp,'quarters':{}}
        for q in ('Q1','H1','Q3'):
            qsrc=(rec.get('quarters') or {}).get(q) or {}
            cands=qsrc.get('candidates') or []
            if not cands:
                outrec['quarters'][q]={'status':'NO_RECEIPT'}; counts[f'{q}_no_receipt']+=1; continue
            chosen=cands[0]; rno=str(chosen.get('rcept_no') or '')
            qr={'rcept_no':rno,'rcept_dt':chosen.get('rcept_dt'),'report_nm':chosen.get('report_nm')}
            try:
                r=s.get(f'{API}/fnlttXbrl.xml',params={'crtfc_key':key,'rcept_no':rno},timeout=120)
                raw=r.content
                qr['http_status']=r.status_code; qr['bytes']=len(raw); qr['zip_magic']=raw[:2]==b'PK'
                if raw[:2]==b'PK':
                    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                        names=zf.namelist()
                        qr['zip_entries']=len(names)
                        qr['entry_names']=names[:80]
                        qr['xbrl_like_entries']=sum(1 for n in names if n.lower().endswith(('.xbrl','.xml','.xsd','.html','.htm')))
                        sample=[]
                        for n in names[:20]:
                            info=zf.getinfo(n)
                            sample.append({'name':n,'size':info.file_size})
                        qr['entry_sample']=sample
                    qr['status']='ZIP_OK'; counts[f'{q}_zip_ok']+=1
                else:
                    txt=raw[:1000].decode('utf-8','replace')
                    qr['status']='NOT_ZIP'; qr['response_head']=txt; counts[f'{q}_not_zip']+=1
            except Exception as e:
                qr['status']='ERROR'; qr['error']=str(e); counts[f'{q}_error']+=1
            outrec['quarters'][q]=qr
        detail.append(outrec)
    out={'research_stage':'development_2015_quarterly_xbrl_probe','modern_oos_protected':True,'corp_count':len(detail),'counts':dict(counts),'detail':detail}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'corp_count':len(detail),'counts':dict(counts)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
