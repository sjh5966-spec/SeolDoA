#!/usr/bin/env python3
from __future__ import annotations
import io,json,os,zipfile
from pathlib import Path
from collections import Counter
import requests
from lxml import etree

SRC=Path('korea_dart_2015_document_fallback_probe.json')
OUT=Path('korea_dart_2015_xbrl_fact_smoke.json')
API='https://opendart.fss.or.kr/api/fnlttXbrl.xml'
TARGET={'OperatingIncomeLoss','ProfitLoss','Equity','CashFlowsFromUsedInOperatingActivities','PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities','PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'}
def ln(t): return t.split('}',1)[-1] if isinstance(t,str) and '}' in t else (t.split(':')[-1] if isinstance(t,str) else '')
def txt(e): return ''.join(e.itertext()).strip()
def val(x):
    s=str(x or '').strip().replace(',','').replace('−','-')
    try:return float(s)
    except:return None

def main():
    key=os.environ['DART_API_KEY']; src=json.loads(SRC.read_text(encoding='utf-8'))
    s=requests.Session(); out=[]; counts=Counter()
    for rec in src.get('detail',[])[:3]:
      corp=rec['corp_code']
      for q in ('Q1','H1','Q3'):
        c=((rec.get('quarters') or {}).get(q) or {}).get('candidates') or []
        if not c: continue
        rno=str(c[0]['rcept_no']); r=s.get(API,params={'crtfc_key':key,'rcept_no':rno},timeout=120); raw=r.content
        rr={'corp_code':corp,'quarter':q,'rcept_no':rno,'zip':raw[:2]==b'PK'}
        if raw[:2]!=b'PK': out.append(rr); continue
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
          xn=max([n for n in zf.namelist() if n.lower().endswith('.xbrl')],key=lambda n:zf.getinfo(n).file_size); xb=zf.read(xn)
        root=etree.fromstring(xb,parser=etree.XMLParser(recover=True,huge_tree=True))
        ctx={}
        for cxt in root.iter():
          if ln(cxt.tag)!='context': continue
          z={'start':None,'end':None,'instant':None,'dimensions':[]}
          for x in cxt.iter():
            n=ln(x.tag)
            if n=='startDate': z['start']=txt(x)
            elif n=='endDate': z['end']=txt(x)
            elif n=='instant': z['instant']=txt(x)
            elif n=='explicitMember': z['dimensions'].append({'dimension':x.get('dimension'),'member':txt(x)})
          ctx[cxt.get('id')]=z
        facts=[]
        for e in root.iter():
          n=ln(e.tag)
          if n not in TARGET: continue
          ci=ctx.get(e.get('contextRef'),{})
          facts.append({'name':n,'qname':e.tag,'context':e.get('contextRef'),'value':val(txt(e)),'start':ci.get('start'),'end':ci.get('end'),'instant':ci.get('instant'),'dimensions':ci.get('dimensions',[])})
          counts[n]+=1
        rr.update({'xbrl_entry':xn,'context_count':len(ctx),'facts':facts}); out.append(rr)
    obj={'research_stage':'development_2015_xbrl_fact_smoke','modern_oos_protected':True,'counts':dict(counts),'rows':out}
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'rows':len(out),'counts':dict(counts)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
