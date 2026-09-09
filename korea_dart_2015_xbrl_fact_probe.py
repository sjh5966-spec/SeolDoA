#!/usr/bin/env python3
"""Inspect preferred accounting facts and contexts in 2015 quarterly XBRL originals.
Development-only; no prices/returns; no 2021+ or 2023+ data.
"""
from __future__ import annotations
import io,json,os,re,zipfile
from pathlib import Path
from collections import Counter
import requests
from lxml import etree

SRC=Path('korea_dart_2015_document_fallback_probe.json')
OUT=Path('korea_dart_2015_xbrl_fact_probe.json')
API='https://opendart.fss.or.kr/api/fnlttXbrl.xml'
TARGET_LOCALNAMES={
 'OperatingIncomeLoss','ProfitLoss','Equity','CashFlowsFromUsedInOperatingActivities',
 'PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
 'PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'
}

def ln(tag):
    if not isinstance(tag,str): return ''
    return tag.split('}',1)[-1] if '}' in tag else tag.split(':')[-1]

def text(el): return ''.join(el.itertext()).strip()

def context_info(root):
    out={}
    for c in root.iter():
        if ln(c.tag)!='context': continue
        cid=c.get('id') or ''
        rec={'id':cid,'start':None,'end':None,'instant':None,'dimensions':[]}
        for x in c.iter():
            n=ln(x.tag)
            if n=='startDate': rec['start']=text(x)
            elif n=='endDate': rec['end']=text(x)
            elif n=='instant': rec['instant']=text(x)
            elif n in ('explicitMember','typedMember'):
                rec['dimensions'].append({'dimension':x.get('dimension'),'member':text(x)[:250]})
        out[cid]=rec
    return out

def parse_num(s):
    s=str(s or '').strip().replace(',','').replace('−','-')
    if s in ('','-','—'): return None
    try: return float(s)
    except: return None

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    src=json.loads(SRC.read_text(encoding='utf-8'))
    s=requests.Session(); s.headers.update({'User-Agent':'SeolDoA-DART-XBRL-Fact-Probe/1.0'})
    detail=[]; counts=Counter()
    for rec in src.get('detail',[]):
        corp=rec.get('corp_code'); rr={'corp_code':corp,'quarters':{}}
        for q in ('Q1','H1','Q3'):
            qs=(rec.get('quarters') or {}).get(q) or {}; cands=qs.get('candidates') or []
            if not cands:
                rr['quarters'][q]={'status':'NO_RECEIPT'}; counts[f'{q}_no_receipt']+=1; continue
            chosen=cands[0]; rno=str(chosen.get('rcept_no') or '')
            qr={'rcept_no':rno,'rcept_dt':chosen.get('rcept_dt'),'report_nm':chosen.get('report_nm')}
            try:
                r=s.get(API,params={'crtfc_key':key,'rcept_no':rno},timeout=120); raw=r.content
                if raw[:2]!=b'PK':
                    qr['status']='NO_XBRL_ZIP'; qr['response_head']=raw[:500].decode('utf-8','replace'); counts[f'{q}_no_zip']+=1
                else:
                    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                        xbrls=[n for n in zf.namelist() if n.lower().endswith('.xbrl')]
                        if not xbrls: raise RuntimeError('no .xbrl instance')
                        # Prefer largest instance if multiple.
                        xn=max(xbrls,key=lambda n:zf.getinfo(n).file_size)
                        xb=zf.read(xn)
                    root=etree.fromstring(xb,parser=etree.XMLParser(recover=True,huge_tree=True))
                    ctx=context_info(root); facts=[]; local_counts=Counter()
                    for el in root.iter():
                        n=ln(el.tag)
                        if n not in TARGET_LOCALNAMES: continue
                        val=parse_num(text(el)); cid=el.get('contextRef') or ''
                        c=ctx.get(cid,{})
                        recf={'local_name':n,'qname':el.tag,'context_id':cid,'value':val,'decimals':el.get('decimals'),
                              'start':c.get('start'),'end':c.get('end'),'instant':c.get('instant'),'dimensions':c.get('dimensions',[])}
                        facts.append(recf); local_counts[n]+=1
                    qr.update({'status':'OK','xbrl_entry':xn,'xbrl_bytes':len(xb),'context_count':len(ctx),
                               'fact_count':len(facts),'target_fact_counts':dict(local_counts),'facts':facts[:300]})
                    counts[f'{q}_ok']+=1
                    for k,v in local_counts.items(): counts[f'fact_{k}']+=v
            except Exception as e:
                qr['status']='ERROR'; qr['error']=str(e); counts[f'{q}_error']+=1
            rr['quarters'][q]=qr
        detail.append(rr)
    out={'research_stage':'development_2015_xbrl_fact_schema_probe','modern_oos_protected':True,'corp_count':len(detail),'counts':dict(counts),'detail':detail}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'corp_count':len(detail),'counts':dict(counts)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
