#!/usr/bin/env python3
from __future__ import annotations
import json,re
from pathlib import Path
import requests

OUT=Path('korea_dart_bulk_source_inspect.json')
URLS=['https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do','https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do']

def snippets(text,pat,radius=2500):
    out=[]
    for m in re.finditer(pat,text,re.I):out.append(text[max(0,m.start()-radius):m.end()+radius])
    return out[:30]

def main():
    s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 SeolDoA research source inspection'
    pages=[]
    for u in URLS:
        r=s.get(u,timeout=30);r.raise_for_status();t=r.text
        pages.append({'url':r.url,'status':r.status_code,'bytes':len(r.content),'script_src':re.findall(r'<script[^>]+src=["\']([^"\']+)',t,re.I),
          'download_ext002_snippets':snippets(t,r'download_ext002'),
          'download_function_snippets':snippets(t,r'function\s+[A-Za-z0-9_]*download[A-Za-z0-9_]*'),
          'action_snippets':snippets(t,r'(?:action|url)\s*[:=]\s*["\'][^"\']*(?:dwld|download)[^"\']*["\']'),
          'known_zip_snippets':snippets(t,r'2016_1Q_(?:BS|PL|CF)_[0-9]+\.zip',1200)})
    OUT.write_text(json.dumps({'pages':pages},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'url':p['url'],'bytes':p['bytes'],'scripts':len(p['script_src']),'ext002':len(p['download_ext002_snippets']),'functions':len(p['download_function_snippets']),'actions':len(p['action_snippets']),'zip':len(p['known_zip_snippets'])} for p in pages],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
