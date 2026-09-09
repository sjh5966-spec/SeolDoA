#!/usr/bin/env python3
import json, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

URL="https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
HEADERS={"User-Agent":"Mozilla/5.0 SeolDoA research"}
r=requests.get(URL,timeout=60,headers=HEADERS); r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")

sources=[]; snippets=[]; endpoints=[]
pat=re.compile(r"function\s+download_ext002\s*\(([^)]*)\)\s*\{",re.I)
for tag in soup.find_all("script"):
    src=tag.get("src")
    if src:
        u=urljoin(URL,src)
        try:
            jr=requests.get(u,timeout=60,headers=HEADERS)
            txt=jr.text if jr.ok else ""
            sources.append({"url":u,"status":jr.status_code,"length":len(txt),"contains":"download_ext002" in txt})
        except Exception as e:
            sources.append({"url":u,"error":str(e)}); txt=""
    else:
        u="inline"; txt=tag.get_text("\n")
    m=pat.search(txt)
    if m:
        start=m.start(); body=txt[start:start+6000]
        snippets.append({"source":u,"text":body})
        for em in re.finditer(r"['\"]([^'\"]*(?:down|dwld|download|file|zip)[^'\"]*)['\"]",body,re.I):
            v=em.group(1).strip()
            if v and v not in endpoints: endpoints.append(v)

# Keep only development-era bulk call metadata; never inspect/download 2023+ payloads.
calls=[]
rx=re.compile(r"download_ext002\('(20\d{2})','(FQ|HY|TQ|FY)',\s*'(BS|PL|CF|CE)',\s*'([^']+\.zip)'\)")
for a in soup.find_all("a",onclick=True):
    m=rx.search(a.get("onclick", ""))
    if not m: continue
    y=int(m.group(1))
    if 2015 <= y <= 2020:
        calls.append({"year":y,"period":m.group(2),"statement":m.group(3),"filename":m.group(4)})

full={"url":r.url,"status":r.status_code,"script_sources":sources,"download_ext002_function_snippets":snippets,"download_endpoint_candidates":endpoints,"development_calls":calls}
Path("korea_dart_bulk_discovery.json").write_text(json.dumps(full,ensure_ascii=False,indent=2),encoding="utf-8")
compact={"status":r.status_code,"sources_with_download_ext002":[x.get("url") for x in sources if x.get("contains")],"download_endpoint_candidates":endpoints,"function_snippets":snippets[:2],"development_call_count":len(calls),"counts_by_year":{str(y):sum(1 for x in calls if x['year']==y) for y in range(2015,2021)}}
Path("korea_dart_bulk_endpoint_summary.json").write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(compact,ensure_ascii=False,indent=2))
