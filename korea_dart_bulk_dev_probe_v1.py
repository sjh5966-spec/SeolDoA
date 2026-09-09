#!/usr/bin/env python3
from __future__ import annotations
import io,json,time,zipfile
from pathlib import Path
import pandas as pd
import requests

DL='https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm='
OUT=Path('korea_dart_bulk_dev_probe_v1.json')
# Known filename captured from the official bulk list source. Skip list.do so a transient list timeout cannot block endpoint proof.
TARGETS=[('2016','FQ','BS','2016_1Q_BS_20230119040459.zip')]

def decode(b):
    for enc in ('utf-8-sig','utf-8','cp949','euc-kr'):
        try:return b.decode(enc),enc
        except:pass
    return b.decode('utf-8','replace'),'replace'

def get_retry(s,url):
    last=''
    for a in range(5):
        try:
            r=s.get(url,timeout=(20,180));r.raise_for_status();return r
        except Exception as e:
            last=str(e);time.sleep(2*(a+1))
    raise RuntimeError(last)

def main():
    s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 SeolDoA bulk financial research','Referer':'https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do'})
    rec=[]
    for y,p,role,fn in TARGETS:
        r=get_retry(s,DL+fn);z={'year':y,'period':p,'role':role,'filename':fn,'http_status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type',''),'content_disposition':r.headers.get('content-disposition',''),'zip_magic':r.content[:2]==b'PK','entries':[]}
        if r.content[:2]==b'PK':
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for n in zf.namelist():
                    raw=zf.read(n);txt,enc=decode(raw);lines=txt.splitlines();entry={'name':n,'bytes':len(raw),'encoding':enc,'line_count':len(lines),'head_lines':lines[:4]}
                    try:
                        df=pd.read_csv(io.StringIO(txt),sep='\t',dtype=str,nrows=5)
                        entry['columns']=list(df.columns);entry['sample_rows']=df.fillna('').head(3).to_dict('records')
                    except Exception as e:entry['parse_error']=str(e)
                    z['entries'].append(entry)
        else:z['response_head']=r.text[:1500]
        rec.append(z)
    OUT.write_text(json.dumps({'direct_endpoint':DL,'targets':rec},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'targets':[{'role':x['role'],'zip':x['zip_magic'],'bytes':x['bytes'],'content_type':x['content_type'],'entries':len(x['entries']),'columns':x['entries'][0].get('columns') if x['entries'] else []} for x in rec]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
