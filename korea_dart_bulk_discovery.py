#!/usr/bin/env python3
import json, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

URL="https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
HEADERS={"User-Agent":"Mozilla/5.0 SeolDoA research"}
r=requests.get(URL,timeout=60,headers=HEADERS)
r.raise_for_status()
html=r.text
soup=BeautifulSoup(html,"html.parser")

anchors=[]
for a in soup.find_all("a"):
    text=" ".join(a.stripped_strings)
    href=a.get("href")
    onclick=a.get("onclick")
    if text or href or onclick:
        anchors.append({"text":text,"href":href,"onclick":onclick})

buttons=[]
for b in soup.find_all(["button","input"]):
    buttons.append({"tag":b.name,"text":" ".join(b.stripped_strings),"type":b.get("type"),"value":b.get("value"),"name":b.get("name"),"onclick":b.get("onclick")})

forms=[]
for f in soup.find_all("form"):
    forms.append({"action":f.get("action"),"method":f.get("method"),"id":f.get("id"),"name":f.get("name"),"inputs":[{"name":x.get("name"),"value":x.get("value"),"type":x.get("type")} for x in f.find_all("input")]})

patterns=[r"function\s+download_ext002\s*\(", r"download_ext002\s*=\s*function\s*\("]
function_snippets=[]
endpoint_candidates=[]
script_sources=[]
scripts=[]

def inspect_js(label, txt):
    if re.search(r"down|dwld|excel|zip|file",txt,re.I):
        scripts.append({"source":label,"text":txt[:30000]})
    for pat in patterns:
        for m in re.finditer(pat,txt,re.I):
            snip=txt[max(0,m.start()-1000):min(len(txt),m.start()+10000)]
            function_snippets.append({"source":label,"text":snip})
            for em in re.finditer(r"['\"]([^'\"]*(?:down|dwld|download|file)[^'\"]*)['\"]",snip,re.I):
                v=em.group(1).strip()
                if v and v not in endpoint_candidates: endpoint_candidates.append(v)

for s in soup.find_all("script"):
    src=s.get("src")
    if src:
        full=urljoin(URL,src)
        rec={"src":src,"url":full}
        try:
            jr=requests.get(full,timeout=60,headers=HEADERS)
            rec["status"]=jr.status_code
            rec["length"]=len(jr.text)
            rec["contains_download_ext002"]="download_ext002" in jr.text
            if jr.ok: inspect_js(full,jr.text)
        except Exception as e:
            rec["error"]=str(e)
        script_sources.append(rec)
    else:
        inspect_js("inline",s.get_text("\n"))

inspect_js("raw_html",html)

interesting_lines=[]
for line in html.splitlines():
    if re.search(r"download_ext002|down|dwld|zip|file|fnltt",line,re.I):
        interesting_lines.append(line.strip()[:6000])

out={"url":r.url,"status":r.status_code,"html_length":len(html),"anchors":anchors,"buttons":buttons,"forms":forms,
     "script_sources":script_sources,"download_ext002_function_snippets":function_snippets,
     "download_endpoint_candidates":endpoint_candidates,"scripts_with_download_terms":scripts,
     "interesting_html_lines":interesting_lines[:1200]}
Path("korea_dart_bulk_discovery.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"status":r.status_code,"html_length":len(html),"script_sources":len(script_sources),
                  "sources_with_download_ext002":[x.get("url") for x in script_sources if x.get("contains_download_ext002")],
                  "download_function_snippets":len(function_snippets),"download_endpoint_candidates":endpoint_candidates},ensure_ascii=False,indent=2))
