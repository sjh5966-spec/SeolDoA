#!/usr/bin/env python3
from __future__ import annotations
import io,json,re,zipfile
from pathlib import Path
import pandas as pd
import requests

LIST='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do'
DL='https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm='
OUT=Path('korea_dart_bulk_dev_probe_v1.json')

def decode(b):
    for enc in ('utf-8-sig','utf-8','cp949','euc-kr'):
        try:return b.decode(enc),enc
        except:pass
    return b.decode('utf-8','replace'),'replace'

def main():
    s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 SeolDoA bulk financial research'
    h=s.get(LIST,timeout=60);h.raise_for_status()
    calls=re.findall(r"download_ext002\('([0-9]{4})','([^']+)',\s*'([^']+)',\s*'([^']+\.zip)'\)",h.text)
    targets=[]
    for y,p,role,fn in calls:
        if y=='2016' and p=='FQ' and role in {'BS','PL','CF'}:targets.append((y,p,role,fn))
    rec=[]
    for y,p,role,fn in targets:
        r=s.get(DL+fn,timeout=120);r.raise_for_status();z={'year':y,'period':p,'role':role,'filename':fn,'http_status':r.status_code,'bytes':len(r.content),'zip_magic':r.content[:2]==b'PK','entries':[]}
        if r.content[:2]==b'PK':
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for n in zf.namelist():
                    raw=zf.read(n);txt,enc=decode(raw);lines=txt.splitlines()
                    entry={'name':n,'bytes':len(raw),'encoding':enc,'line_count':len(lines),'head_lines':lines[:4]}
                    try:
                        df=pd.read_csv(io.StringIO(txt),sep='\t',dtype=str,nrows=5)
                        entry['columns']=list(df.columns);entry['sample_rows']=df.fillna('').head(2).to_dict('records')
                    except Exception as e:entry['parse_error']=str(e)
                    z['entries'].append(entry)
        else:z['response_head']=r.text[:1000]
        rec.append(z)
    OUT.write_text(json.dumps({'list_status':h.status_code,'call_count':len(calls),'targets':rec},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'call_count':len(calls),'targets':[{'role':x['role'],'zip':x['zip_magic'],'bytes':x['bytes'],'entries':len(x['entries']),'columns':x['entries'][0].get('columns') if x['entries'] else []} for x in rec]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
