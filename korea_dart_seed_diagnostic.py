#!/usr/bin/env python3
from __future__ import annotations
import io, json, os, zipfile, xml.etree.ElementTree as ET
from pathlib import Path
from collections import Counter
import pandas as pd, requests

BASE='https://opendart.fss.or.kr/api'
SEED=Path('korea_dart_quarterly_seed_2015_2020.csv')
OUT=Path('korea_dart_seed_diagnostic_2015.json')
REPORTS={'Q1':'11013','H1':'11012','Q3':'11014','FY':'11011'}

def get_json(session,key,path,**params):
    r=session.get(f'{BASE}/{path}',params={'crtfc_key':key,**params},timeout=60)
    r.raise_for_status(); d=r.json(); return str(d.get('status','')), d.get('list',[]) or [], d.get('message','')

def load_registry(session,key):
    r=session.get(f'{BASE}/corpCode.xml',params={'crtfc_key':key},timeout=60); r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        raw=zf.read(zf.namelist()[0])
    root=ET.fromstring(raw)
    rows=[]
    for item in root.findall('list'):
        d={c.tag:(c.text or '').strip() for c in item}; rows.append(d)
    return rows

def norm_name(x):
    return ''.join(str(x or '').split()).replace('주식회사','').replace('(주)','').replace('㈜','')

def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    seed=pd.read_csv(SEED,dtype=str).fillna('')
    seed=seed[seed['fiscal_year'].eq('2015')].head(20)
    s=requests.Session(); s.headers.update({'User-Agent':'SeolDoA-DART-Seed-Diagnostic/1.0'})
    reg=load_registry(s,key)
    by_code={x.get('corp_code',''):x for x in reg}
    by_name={}
    for x in reg: by_name.setdefault(norm_name(x.get('corp_name','')),[]).append(x)
    detail=[]; counts=Counter()
    for _,r in seed.iterrows():
        seed_code=str(r['corp_code']).zfill(8); nm=str(r['company_name'])
        regrow=by_code.get(seed_code)
        name_matches=by_name.get(norm_name(nm),[])
        resolved=seed_code if regrow else (name_matches[0].get('corp_code','') if len(name_matches)==1 else '')
        rec={'seed_corp_code':seed_code,'company_name':nm,'seed_code_in_registry':bool(regrow),'registry_name':regrow.get('corp_name','') if regrow else '',
             'exact_name_match_count':len(name_matches),'resolved_corp_code':resolved,'resolved_differs':bool(resolved and resolved!=seed_code),'reports':{}}
        counts['seed_code_in_registry' if regrow else 'seed_code_missing_registry']+=1
        if resolved:
            for label,code in REPORTS.items():
                for fs in ('CFS','OFS'):
                    st,items,msg=get_json(s,key,'fnlttSinglAcntAll.json',corp_code=resolved,bsns_year='2015',reprt_code=code,fs_div=fs)
                    rec['reports'][f'{label}_{fs}']={'status':st,'rows':len(items),'message':msg}
                    counts[f'{label}_{fs}_status_{st}']+=1
                    if items: counts[f'{label}_any_data']+=1; break
        detail.append(rec)
    out={'research_stage':'development_seed_identifier_diagnostic','modern_oos_protected':True,'year':2015,'seed_rows':len(detail),'counts':dict(counts),'detail':detail}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'seed_rows':len(detail),'counts':dict(counts)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
