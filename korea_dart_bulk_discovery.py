#!/usr/bin/env python3
import json, re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL="https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
r=requests.get(URL,timeout=60,headers={"User-Agent":"Mozilla/5.0 SeolDoA research"})
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
    buttons.append({
        "tag":b.name,
        "text":" ".join(b.stripped_strings),
        "type":b.get("type"),
        "value":b.get("value"),
        "name":b.get("name"),
        "onclick":b.get("onclick"),
    })

forms=[]
for f in soup.find_all("form"):
    forms.append({
        "action":f.get("action"),
        "method":f.get("method"),
        "id":f.get("id"),
        "name":f.get("name"),
        "inputs":[{"name":x.get("name"),"value":x.get("value"),"type":x.get("type")} for x in f.find_all("input")]
    })

scripts=[]
function_snippets=[]
for s in soup.find_all("script"):
    txt=s.get_text("\n")
    if re.search(r"down|dwld|excel|zip|file",txt,re.I):
        scripts.append(txt[:20000])
    for pat in [r"function\s+download_ext002\s*\(", r"download_ext002\s*=\s*function\s*\("]:
        for m in re.finditer(pat,txt,re.I):
            function_snippets.append(txt[max(0,m.start()-500):min(len(txt),m.start()+8000)])

# Also search raw HTML in case the JS parser changes whitespace/escaping.
for pat in [r"function\s+download_ext002\s*\(", r"download_ext002\s*=\s*function\s*\("]:
    for m in re.finditer(pat,html,re.I):
        function_snippets.append(html[max(0,m.start()-500):min(len(html),m.start()+8000)])

# Capture candidate endpoint strings adjacent to the function name.
endpoint_candidates=[]
for snip in function_snippets:
    for match in re.finditer(r"['\"]([^'\"]*(?:down|dwld|download|file)[^'\"]*)['\"]",snip,re.I):
        value=match.group(1).strip()
        if value and value not in endpoint_candidates:
            endpoint_candidates.append(value)

interesting_lines=[]
for line in html.splitlines():
    if re.search(r"download_ext002|down|dwld|zip|file|fnltt",line,re.I):
        interesting_lines.append(line.strip()[:6000])

out={
    "url":r.url,
    "status":r.status_code,
    "html_length":len(html),
    "anchors":anchors,
    "buttons":buttons,
    "forms":forms,
    "download_ext002_function_snippets":function_snippets,
    "download_endpoint_candidates":endpoint_candidates,
    "scripts_with_download_terms":scripts,
    "interesting_html_lines":interesting_lines[:1200],
}
Path("korea_dart_bulk_discovery.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({
    "status":r.status_code,
    "html_length":len(html),
    "anchors":len(anchors),
    "buttons":len(buttons),
    "forms":len(forms),
    "download_function_snippets":len(function_snippets),
    "download_endpoint_candidates":endpoint_candidates,
    "scripts_with_download_terms":len(scripts),
    "interesting_lines":len(interesting_lines),
},ensure_ascii=False,indent=2))
