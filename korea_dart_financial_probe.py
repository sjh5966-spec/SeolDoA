#!/usr/bin/env python3
"""OpenDART financial-statement probe for the Korea turnaround replication.

This is a schema/accounting audit only. It does NOT compute returns and does NOT
inspect the 2023+ Korean OOS period.

Goals
-----
1. Verify that OpenDART full financial statements can be retrieved for historical
   periodic reports in the preregistered development/validation eras.
2. Check whether consolidated statements are available and distinguish them from
   separate statements.
3. Identify candidate account rows for operating profit, net income, equity,
   operating cash flow, and cash capex without silently hard-coding a single label.
4. Persist raw-ish normalized rows so the later event builder can freeze mappings
   before any modern OOS return analysis.

Environment
-----------
DART_API_KEY        required
KOREA_DART_STOCKS   optional comma-separated six-digit stock codes
KOREA_DART_YEARS    optional comma-separated years; defaults to 2015,2020,2022

Outputs
-------
korea_dart_financial_probe_rows.csv
korea_dart_financial_probe_summary.json
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DART_BASE = "https://opendart.fss.or.kr/api"
OUT_ROWS = Path("korea_dart_financial_probe_rows.csv")
OUT_SUMMARY = Path("korea_dart_financial_probe_summary.json")

DEFAULT_STOCKS = ["005930", "000660", "035720", "068270", "091990"]
DEFAULT_YEARS = [2015, 2020, 2022]
REPORT_CODES = {
    "Q1": "11013",
    "H1": "11012",
    "Q3": "11014",
    "FY": "11011",
}

ACCOUNT_PATTERNS = {
    "operating_profit": [
        r"영업이익",
        r"영업손실",
        r"영업이익\(손실\)",
        r"ProfitLossFromOperatingActivities",
    ],
    "net_income": [
        r"당기순이익",
        r"당기순손실",
        r"분기순이익",
        r"반기순이익",
        r"ProfitLoss",
    ],
    "equity": [
        r"자본총계",
        r"자본의 총계",
        r"Equity",
    ],
    "cfo": [
        r"영업활동.*현금흐름",
        r"영업활동으로 인한 현금흐름",
        r"CashFlowsFromUsedInOperatingActivities",
    ],
    "capex": [
        r"유형자산.*취득",
        r"유형자산의 취득",
        r"무형자산.*취득",
        r"PropertyPlantAndEquipment.*Purchase",
        r"IntangibleAssets.*Purchase",
    ],
}


def _get_json(path: str, key: str, **params) -> dict:
    r = requests.get(f"{DART_BASE}/{path}", params={"crtfc_key": key, **params}, timeout=60)
    r.raise_for_status()
    data = r.json()
    status = str(data.get("status", ""))
    if status not in ("000", "013"):
        raise RuntimeError(f"OpenDART {path} status={status}: {data.get('message')}")
    return data


def _load_corp_codes(key: str) -> pd.DataFrame:
    import io
    import zipfile
    import xml.etree.ElementTree as ET

    r = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        if not names:
            raise RuntimeError("OpenDART corpCode archive was empty")
        raw = zf.read(names[0])
    root = ET.fromstring(raw)
    rows = [{child.tag: (child.text or "").strip() for child in item} for item in root.findall("list")]
    df = pd.DataFrame(rows)
    df["stock_code"] = df.get("stock_code", "").astype(str).str.zfill(6)
    return df[df["stock_code"].str.fullmatch(r"\d{6}", na=False)].copy()


def _parse_stocks() -> list[str]:
    raw = os.getenv("KOREA_DART_STOCKS", "").strip()
    xs = [x.strip() for x in raw.split(",") if x.strip()] if raw else DEFAULT_STOCKS
    out = []
    for x in xs:
        x = x.zfill(6)
        if not re.fullmatch(r"\d{6}", x):
            raise ValueError(f"invalid stock code: {x}")
        out.append(x)
    return out


def _parse_years() -> list[int]:
    raw = os.getenv("KOREA_DART_YEARS", "").strip()
    xs = [int(x.strip()) for x in raw.split(",") if x.strip()] if raw else DEFAULT_YEARS
    for y in xs:
        if y < 2010 or y > 2022:
            raise ValueError("financial probe intentionally restricted to <=2022 to protect modern OOS")
    return xs


def _classify_account(account_nm: str, account_id: str) -> list[str]:
    haystack = f"{account_nm} {account_id}".strip()
    labels = []
    for label, pats in ACCOUNT_PATTERNS.items():
        if any(re.search(p, haystack, flags=re.IGNORECASE) for p in pats):
            labels.append(label)
    return labels


def _fetch_statement(key: str, corp_code: str, year: int, report_code: str, fs_div: str) -> list[dict]:
    data = _get_json(
        "fnlttSinglAcntAll.json",
        key,
        corp_code=corp_code,
        bsns_year=str(year),
        reprt_code=report_code,
        fs_div=fs_div,
    )
    return data.get("list", []) or []


def main() -> int:
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise SystemExit("DART_API_KEY is required")

    stocks = _parse_stocks()
    years = _parse_years()
    corp = _load_corp_codes(key)
    stock_to_corp = corp.drop_duplicates("stock_code").set_index("stock_code")["corp_code"].to_dict()
    stock_to_name = corp.drop_duplicates("stock_code").set_index("stock_code")["corp_name"].to_dict()

    rows: list[dict] = []
    fetch_status: list[dict] = []

    for stock_code in stocks:
        corp_code = stock_to_corp.get(stock_code)
        if not corp_code:
            fetch_status.append({"stock_code": stock_code, "status": "corp_code_missing"})
            continue
        for year in years:
            for period, reprt_code in REPORT_CODES.items():
                for fs_div in ("CFS", "OFS"):
                    try:
                        items = _fetch_statement(key, corp_code, year, reprt_code, fs_div)
                        fetch_status.append(
                            {
                                "stock_code": stock_code,
                                "year": year,
                                "period": period,
                                "fs_div": fs_div,
                                "status": "ok" if items else "no_data",
                                "rows": len(items),
                            }
                        )
                    except Exception as exc:
                        fetch_status.append(
                            {
                                "stock_code": stock_code,
                                "year": year,
                                "period": period,
                                "fs_div": fs_div,
                                "status": "error",
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:300],
                            }
                        )
                        continue

                    for x in items:
                        account_nm = str(x.get("account_nm", ""))
                        account_id = str(x.get("account_id", ""))
                        classes = _classify_account(account_nm, account_id)
                        if not classes:
                            continue
                        rows.append(
                            {
                                "stock_code": stock_code,
                                "corp_code": corp_code,
                                "corp_name": stock_to_name.get(stock_code, ""),
                                "year": year,
                                "period": period,
                                "reprt_code": reprt_code,
                                "fs_div_requested": fs_div,
                                "fs_div_returned": x.get("fs_div"),
                                "sj_div": x.get("sj_div"),
                                "sj_nm": x.get("sj_nm"),
                                "account_id": account_id,
                                "account_nm": account_nm,
                                "account_classes": "|".join(classes),
                                "thstrm_nm": x.get("thstrm_nm"),
                                "thstrm_amount": x.get("thstrm_amount"),
                                "thstrm_add_amount": x.get("thstrm_add_amount"),
                                "frmtrm_nm": x.get("frmtrm_nm"),
                                "frmtrm_amount": x.get("frmtrm_amount"),
                                "frmtrm_add_amount": x.get("frmtrm_add_amount"),
                                "ord": x.get("ord"),
                                "currency": x.get("currency"),
                            }
                        )

    rdf = pd.DataFrame(rows)
    rdf.to_csv(OUT_ROWS, index=False)

    sdf = pd.DataFrame(fetch_status)
    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_stage": "dart_financial_schema_audit_only",
        "modern_oos_protected": True,
        "probe_stocks": stocks,
        "probe_years": years,
        "fetch_attempts": int(len(sdf)),
        "fetch_ok": int((sdf.get("status") == "ok").sum()) if not sdf.empty else 0,
        "fetch_no_data": int((sdf.get("status") == "no_data").sum()) if not sdf.empty else 0,
        "fetch_errors": int((sdf.get("status") == "error").sum()) if not sdf.empty else 0,
        "candidate_account_rows": int(len(rdf)),
        "candidate_account_classes": (
            rdf["account_classes"].value_counts().to_dict() if not rdf.empty else {}
        ),
        "note": "This probe audits account availability only; no Korea return thresholds or OOS returns are inspected.",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
