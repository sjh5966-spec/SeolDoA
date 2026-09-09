#!/usr/bin/env python3
import json, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

PAGE="https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
BASE="https://opendart.fss.or.kr"
HEADERS={"User-Agent":"Mozilla/5.0 SeolDoA research","Referer":PAGE}
r=requests.get(PAGE,timeout=60,headers=HEADERS); r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")

# Development metadata only. Never download 2021+ payloads here.
rx=re.compile(r"download_ext002\('(20\d{2})','(FQ|HY|TQ|FY)',\s*'(BS|PL|CF|CE)',\s*'([^']+\.zip)'\)")
calls=[]
for a in soup.find_all("a",onclick=True):
    m=rx.search(a.get("onclick", ""))
    if not m: continue
    y=int(m.group(1))
    if 2015 <= y <= 2020:
        calls.append({"year":y,"period":m.group(2),"statement":m.group(3),"filename":m.group(4)})

sample=next(x for x in calls if x["year"]==2016 and x["period"]=="FQ" and x["statement"]=="BS")
y=str(sample["year"]); p=sample["period"]; s=sample["statement"]; f=sample["filename"]

paths=[
 "/disclosureinfo/fnltt/dwld/download.do",
 "/disclosureinfo/fnltt/dwld/downloadExt.do",
 "/disclosureinfo/fnltt/dwld/downloadExt002.do",
 "/disclosureinfo/fnltt/dwld/ext002.do",
 "/disclosureinfo/fnltt/dwld/file.do",
 "/disclosureinfo/fnltt/dwld/excelDownload.do",
 "/disclosureinfo/fnltt/dwld/downloadFile.do",
 "/disclosureinfo/fnltt/dwld/downloadZip.do",
 "/disclosureinfo/fnltt/dwld/fileDownload.do",
]
params_variants=[
 {"year":y,"reprtCode":p,"fsDiv":s,"fileName":f},
 {"year":y,"reprt_code":p,"fs_div":s,"file_nm":f},
 {"bsns_year":y,"reprt_code":p,"sj_div":s,"file_nm":f},
 {"bsns_year":y,"reprtCode":p,"sjDiv":s,"fileName":f},
 {"year":y,"reportType":p,"statementType":s,"fileName":f},
 {"year":y,"reprtCode":p,"sjDiv":s,"fileName":f},
 {"fileName":f},
 {"file_nm":f},
 {"filename":f},
]

results=[]; winner=None
session=requests.Session(); session.headers.update(HEADERS)
# Establish cookies/session first.
session.get(PAGE,timeout=60)
for path in paths:
    url=urljoin(BASE,path)
    for params in params_variants:
        for method in ("GET","POST"):
            try:
                if method=="GET":
                    rr=session.get(url,params=params,timeout=30,allow_redirects=True)
                else:
                    rr=session.post(url,data=params,timeout=30,allow_redirects=True)
                head=rr.content[:8]
                ct=rr.headers.get("content-type","")
                cd=rr.headers.get("content-disposition","")
                ok=head.startswith(b"PK")
                rec={"method":method,"url":url,"params":params,"status":rr.status_code,"bytes":len(rr.content),"content_type":ct,"content_disposition":cd,"head_hex":head.hex(),"zip_magic":ok}
                results.append(rec)
                if ok:
                    winner=rec
                    break
            except Exception as e:
                results.append({"method":method,"url":url,"params":params,"error":str(e),"zip_magic":False})
        if winner: break
    if winner: break

# Also inspect any inline script strings around download_ext002 calls for endpoint hints.
inline_hints=[]
for tag in soup.find_all("script"):
    txt=tag.get_text("\n")
    if re.search(r"download_ext002|fnltt/dwld|\.do",txt,re.I):
        for line in txt.splitlines():
            if re.search(r"download_ext002|fnltt/dwld|download|dwld",line,re.I):
                inline_hints.append(line.strip()[:3000])

compact={
 "status":r.status_code,
 "development_call_count":len(calls),
 "counts_by_year":{str(yy):sum(1 for x in calls if x['year']==yy) for yy in range(2015,2021)},
 "sample":sample,
 "winner":winner,
 "attempt_count":len(results),
 "inline_hints":inline_hints[:100],
 "top_attempts":results[:30] if winner is None else [x for x in results if x.get("zip_magic") or x.get("status") in (200,302)][:50],
}
Path("korea_dart_bulk_endpoint_summary.json").write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding="utf-8")
Path("korea_dart_bulk_discovery.json").write_text(json.dumps({"development_calls":calls,"probe_results":results,"winner":winner},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(compact,ensure_ascii=False,indent=2))
