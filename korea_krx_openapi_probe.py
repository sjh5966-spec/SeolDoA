#!/usr/bin/env python3
"""KRX Open API connectivity/schema probe for the Korea pre-OOS study.

Guardrails:
- requires KRX_OPEN_API_KEY from environment; never prints the key
- probes only <= 2022 dates
- no strategy thresholds or post-2022 returns
- writes raw-ish JSON/CSV diagnostics for schema validation
"""
from __future__ import annotations
import json, os
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

KEY = os.getenv("KRX_OPEN_API_KEY", "").strip()
if not KEY:
    raise SystemExit("KRX_OPEN_API_KEY is required")

# Official KRX Open API stock daily endpoints. Override env vars if KRX changes IDs/paths.
BASE = "https://data-dbg.krx.co.kr/svc/apis/sto"
ENDPOINTS = {
    "kospi": os.getenv("KRX_KOSPI_DAILY_PATH", "/stk_bydd_trd"),
    "kosdaq": os.getenv("KRX_KOSDAQ_DAILY_PATH", "/ksq_bydd_trd"),
}
DATES = [x.strip() for x in os.getenv("KRX_PROBE_DATES", "20150105,20200102,20221229").split(",") if x.strip()]
if any(len(d) != 8 or not d.isdigit() or int(d[:4]) > 2022 for d in DATES):
    raise SystemExit("KRX_PROBE_DATES must be YYYYMMDD and <= 2022")

rows=[]; errors=[]
for market, path in ENDPOINTS.items():
    for d in DATES:
        url = BASE + path
        try:
            r=requests.get(url, headers={"AUTH_KEY":KEY}, params={"basDd":d}, timeout=60)
            rec={"market":market,"date":d,"http_status":r.status_code,"content_type":r.headers.get("content-type","")}
            r.raise_for_status()
            payload=r.json()
            data=payload.get("OutBlock_1", []) if isinstance(payload,dict) else []
            rec["rows"]=len(data); rec["keys"]=sorted(data[0].keys()) if data else []
            rows.append(rec)
            for x in data[:5]:
                y={"market":market,"probe_date":d,**x};
                pd.DataFrame([y]).to_csv("korea_krx_openapi_probe_sample.csv", mode="a", header=not Path("korea_krx_openapi_probe_sample.csv").exists(), index=False)
        except Exception as e:
            errors.append({"market":market,"date":d,"error_type":type(e).__name__,"error":str(e)[:300]})

summary={
 "checked_at_utc":datetime.now(timezone.utc).isoformat(),
 "research_stage":"krx_openapi_schema_probe_pre_oos",
 "modern_oos_protected":True,
 "dates":DATES,
 "requests":len(ENDPOINTS)*len(DATES),
 "successful_requests":len(rows),
 "errors":errors,
 "results":rows,
 "note":"Connectivity/schema probe only. Historical survivorship-free universe is not yet certified."
}
Path("korea_krx_openapi_probe_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k!="results"},ensure_ascii=False,indent=2))
if errors:
    raise SystemExit(2)
