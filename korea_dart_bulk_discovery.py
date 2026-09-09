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
for s in soup.find_all("script"):
    txt=s.get_text("\n")
    if re.search(r"down|dwld|excel|zip|file",txt,re.I):
        scripts.append(txt[:12000])

interesting_lines=[]
for line in html.splitlines():
    if re.search(r"down|dwld|zip|file|fnltt",line,re.I):
        interesting_lines.append(line.strip()[:4000])

out={
    "url":r.url,
    "status":r.status_code,
    "html_length":len(html),
    "anchors":anchors,
    "buttons":buttons,
    "forms":forms,
    "scripts_with_download_terms":scripts,
    "interesting_html_lines":interesting_lines[:1000],
}
Path("korea_dart_bulk_discovery.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({
    "status":r.status_code,
    "html_length":len(html),
    "anchors":len(anchors),
    "buttons":len(buttons),
    "forms":len(forms),
    "scripts_with_download_terms":len(scripts),
    "interesting_lines":len(interesting_lines),
},ensure_ascii=False,indent=2))
