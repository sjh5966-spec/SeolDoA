#!/usr/bin/env python3
from __future__ import annotations
import json,re
from urllib.parse import urljoin
from pathlib import Path
import requests

PAGES=[
 'https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do',
 'https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do',
]
OUT=Path('korea_dart_bulk_source_inspect.json')

def main():
    s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 SeolDoA research source inspection'
    allhits=[];page_meta=[];fetched_map={};forms=[];snips=[]
    needles=('download','dwld','ext002','zip','fileNm','file_nm','filename','atch','down')
    def scan(label,text,url=''):
        lines=text.splitlines()
        for i,line in enumerate(lines):
            lo=line.lower()
            if any(n.lower() in lo for n in needles):
                allhits.append({'source':label,'url':url,'line':i+1,'text':line.strip()[:3000]})
    for base in PAGES:
        r=s.get(base,timeout=60);r.raise_for_status();html=r.text
        scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)
        inline=re.findall(r'<script[^>]*>(.*?)</script>',html,re.I|re.S)
        page_meta.append({'url':r.url,'status':r.status_code,'bytes':len(r.content),'scripts':scripts})
        scan('html',html,base)
        for i,t in enumerate(inline):scan(f'inline_{i}',t,base)
        for m in re.finditer(r'<form\b([^>]*)>(.*?)</form>',html,re.I|re.S):
            head=m.group(1);body=m.group(2)
            action=re.search(r'action=["\']([^"\']+)',head,re.I);method=re.search(r'method=["\']([^"\']+)',head,re.I)
            names=re.findall(r'<input[^>]+name=["\']([^"\']+)',body,re.I)
            forms.append({'page':base,'action':urljoin(base,action.group(1)) if action else '', 'method':method.group(1) if method else '', 'input_names':names})
        target='2016_1Q_BS_20230119040459.zip'
        for mat in re.finditer(re.escape(target),html):snips.append(html[max(0,mat.start()-1500):mat.end()+1500])
        for src in scripts:
            u=urljoin(base,src)
            if u in fetched_map:continue
            try:
                q=s.get(u,timeout=60);fetched_map[u]={'url':u,'status':q.status_code,'bytes':len(q.content),'content_type':q.headers.get('content-type','')}
                if q.ok:scan('external_js',q.text,u)
            except Exception as e:fetched_map[u]={'url':u,'error':str(e)}
    obj={'pages':page_meta,'fetched_scripts':list(fetched_map.values()),'forms':forms,'hits':allhits[:3000],'target_snippets':snips[:10]}
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pages':page_meta,'fetched':len(fetched_map),'hits':len(allhits),'forms':forms,'target_snippets':len(snips)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
