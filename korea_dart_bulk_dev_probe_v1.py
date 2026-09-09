#!/usr/bin/env python3
from __future__ import annotations
import io,json,re,time,zipfile
from pathlib import Path
import pandas as pd
import requests

MAIN='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do'
LIST='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do'
DL='https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm='
OUT=Path('korea_dart_bulk_dev_probe_v1.json')
FALLBACK=[('2016','FQ','BS','2016_1Q_BS_20230119040459.zip')]

def decode(b):
    for enc in ('utf-8-sig','utf-8','cp949','euc-kr'):
        try:return b.decode(enc),enc
        except:pass
    return b.decode('utf-8','replace'),'replace'

def get_retry(s,url,**kw):
    last=''
    for a in range(5):
        try:
            r=s.get(url,timeout=(15,180),**kw);r.raise_for_status();return r
        except Exception as e:last=str(e);time.sleep(2*(a+1))
    raise RuntimeError(last)

def main():
    s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
    pre=[];calls=[]
    try:
        a=get_retry(s,MAIN);pre.append({'page':'main','status':a.status_code,'bytes':len(a.content),'cookies':list(s.cookies.keys())})
        s.headers['Referer']=MAIN
        b=get_retry(s,LIST);pre.append({'page':'list','status':b.status_code,'bytes':len(b.content),'cookies':list(s.cookies.keys())})
        calls=re.findall(r"download_ext002\('([0-9]{4})','([^']+)',\s*'([^']+)',\s*'([^']+\.zip)'\)",b.text)
    except Exception as e:pre.append({'session_setup_error':str(e)})
    targets=[x for x in calls if x[0]=='2016' and x[1]=='FQ' and x[2] in {'BS','PL','CF'}] or FALLBACK
    rec=[]
    s.headers['Referer']=MAIN
    for y,p,role,fn in targets:
        try:r=get_retry(s,DL+fn)
        except Exception as e:
            rec.append({'year':y,'period':p,'role':role,'filename':fn,'request_error':str(e)});continue
        z={'year':y,'period':p,'role':role,'filename':fn,'http_status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type',''),'content_disposition':r.headers.get('content-disposition',''),'zip_magic':r.content[:2]==b'PK','entries':[],'cookies':list(s.cookies.keys())}
        if z['zip_magic']:
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for n in zf.namelist():
                    raw=zf.read(n);txt,enc=decode(raw);entry={'name':n,'bytes':len(raw),'encoding':enc,'line_count':len(txt.splitlines()),'head_lines':txt.splitlines()[:4]}
                    try:
                        df=pd.read_csv(io.StringIO(txt),sep='\t',dtype=str,nrows=5)
                        entry['columns']=list(df.columns);entry['sample_rows']=df.fillna('').head(3).to_dict('records')
                    except Exception as e:entry['parse_error']=str(e)
                    z['entries'].append(entry)
        else:z['response_head']=r.text[:1500]
        rec.append(z)
    obj={'session_setup':pre,'parsed_calls':len(calls),'targets':rec}
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'session_setup':pre,'parsed_calls':len(calls),'targets':[{'role':x.get('role'),'zip':x.get('zip_magic'),'bytes':x.get('bytes'),'entries':len(x.get('entries',[])),'columns':x.get('entries',[{}])[0].get('columns') if x.get('entries') else []} for x in rec]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
