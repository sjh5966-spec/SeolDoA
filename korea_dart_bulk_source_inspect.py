#!/usr/bin/env python3
from __future__ import annotations
import json,re
from urllib.parse import urljoin
from pathlib import Path
import requests

BASE='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do'
OUT=Path('korea_dart_bulk_source_inspect.json')

def main():
    s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 SeolDoA research source inspection'
    r=s.get(BASE,timeout=60);r.raise_for_status();html=r.text
    scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)
    inline=re.findall(r'<script[^>]*>(.*?)</script>',html,re.I|re.S)
    needles=('download','dwld','ext002','zip','fileNm','file_nm','filename','atch','down')
    hits=[]
    def scan(label,text,url=''):
        lines=text.splitlines()
        for i,line in enumerate(lines):
            lo=line.lower()
            if any(n.lower() in lo for n in needles):
                hits.append({'source':label,'url':url,'line':i+1,'text':line.strip()[:2000]})
    scan('html',html,BASE)
    for i,t in enumerate(inline):scan(f'inline_{i}',t,BASE)
    fetched=[]
    for src in scripts:
        u=urljoin(BASE,src)
        try:
            q=s.get(u,timeout=60); fetched.append({'url':u,'status':q.status_code,'bytes':len(q.content),'content_type':q.headers.get('content-type','')})
            if q.ok:scan('external_js',q.text,u)
        except Exception as e:fetched.append({'url':u,'error':str(e)})
    forms=[]
    for m in re.finditer(r'<form\b([^>]*)>(.*?)</form>',html,re.I|re.S):
        head=m.group(1);body=m.group(2)
        action=re.search(r'action=["\']([^"\']+)',head,re.I);method=re.search(r'method=["\']([^"\']+)',head,re.I)
        names=re.findall(r'<input[^>]+name=["\']([^"\']+)',body,re.I)
        forms.append({'action':urljoin(BASE,action.group(1)) if action else '', 'method':method.group(1) if method else '', 'input_names':names})
    # capture surrounding snippets for known 2016 filename if server renders it
    target='2016_1Q_BS_20230119040459.zip';snips=[]
    for mat in re.finditer(re.escape(target),html): snips.append(html[max(0,mat.start()-1000):mat.end()+1000])
    obj={'status':r.status_code,'url':r.url,'html_bytes':len(r.content),'scripts':scripts,'fetched_scripts':fetched,'forms':forms,'hits':hits[:1000],'target_snippets':snips[:10]}
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'html_bytes':len(r.content),'scripts':len(scripts),'fetched':len(fetched),'hits':len(hits),'forms':forms,'target_snippets':len(snips)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
