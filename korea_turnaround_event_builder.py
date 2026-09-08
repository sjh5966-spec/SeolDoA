#!/usr/bin/env python3
"""Build pre-OOS Korean quarterly turnaround accounting events from OpenDART.

Research guardrail
------------------
- Hard stop at business year <= 2022.
- No price/return data are requested.
- This builder creates accounting/disclosure events only.
- Historical-universe survivorship is NOT solved here; output carries a universe flag.

Environment
-----------
DART_API_KEY                required
KOREA_EVENT_STOCKS          optional comma-separated 6-digit stock codes
KOREA_EVENT_START_YEAR      default 2015
KOREA_EVENT_END_YEAR        default 2022, may not exceed 2022

Outputs
-------
korea_turnaround_events_pre_oos.csv
korea_turnaround_event_builder_summary.json
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DART_BASE = "https://opendart.fss.or.kr/api"
OUT_EVENTS = Path("korea_turnaround_events_pre_oos.csv")
OUT_SUMMARY = Path("korea_turnaround_event_builder_summary.json")

REPORTS = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011"}
DEFAULT_STOCKS = ["005930", "000660", "035720", "068270", "091990"]

PREFERRED_IDS = {
    "operating_profit": ["dart_OperatingIncomeLoss"],
    "net_income": ["ifrs_ProfitLoss"],
    "equity": ["ifrs_Equity"],
    "cfo": ["ifrs_CashFlowsFromUsedInOperatingActivities"],
    "capex_ppe": ["ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "capex_intangible": ["ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
}


def api_json(path: str, key: str, **params) -> dict:
    r = requests.get(f"{DART_BASE}/{path}", params={"crtfc_key": key, **params}, timeout=60)
    r.raise_for_status()
    d = r.json()
    st = str(d.get("status", ""))
    if st not in ("000", "013"):
        raise RuntimeError(f"OpenDART {path} status={st}: {d.get('message')}")
    return d


def corp_map(key: str) -> pd.DataFrame:
    r = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        raw = zf.read(zf.namelist()[0])
    root = ET.fromstring(raw)
    rows = [{c.tag: (c.text or "").strip() for c in x} for x in root.findall("list")]
    df = pd.DataFrame(rows)
    if "stock_code" not in df:
        return pd.DataFrame(columns=["corp_code", "corp_name", "stock_code"])
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
    return df[df["stock_code"].str.fullmatch(r"\d{6}", na=False)].copy()


def parse_config() -> tuple[list[str], int, int]:
    raw = os.getenv("KOREA_EVENT_STOCKS", "").strip()
    stocks = [x.strip().zfill(6) for x in raw.split(",") if x.strip()] if raw else DEFAULT_STOCKS
    if any(not re.fullmatch(r"\d{6}", x) for x in stocks):
        raise ValueError("KOREA_EVENT_STOCKS must contain six-digit stock codes")
    y0 = int(os.getenv("KOREA_EVENT_START_YEAR", "2015"))
    y1 = int(os.getenv("KOREA_EVENT_END_YEAR", "2022"))
    if y0 < 2010 or y1 > 2022 or y0 > y1:
        raise ValueError("builder is intentionally restricted to 2010..2022 and end_year <= 2022")
    return stocks, y0, y1


def num(x) -> float | None:
    if x is None or str(x).strip() == "":
        return None
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def exact_label(metric: str, name: str, sj_div: str) -> bool:
    n = re.sub(r"\s+", "", str(name or ""))
    if metric == "operating_profit":
        return sj_div == "IS" and n in {"영업이익", "영업손실", "영업이익(손실)"}
    if metric == "net_income":
        return sj_div in {"IS", "CIS"} and n in {
            "당기순이익", "당기순손실", "당기순이익(손실)", "분기순이익", "분기순이익(손실)",
            "반기순이익", "반기순이익(손실)"
        }
    if metric == "equity":
        return sj_div == "BS" and n in {"자본총계", "자본의총계"}
    if metric == "cfo":
        return sj_div == "CF" and ("영업활동" in n and "현금흐름" in n)
    if metric == "capex_ppe":
        return sj_div == "CF" and ("유형자산" in n and "취득" in n)
    if metric == "capex_intangible":
        return sj_div == "CF" and ("무형자산" in n and "취득" in n)
    return False


def canonical_section(metric: str) -> set[str]:
    return {
        "operating_profit": {"IS"}, "net_income": {"IS", "CIS"}, "equity": {"BS"},
        "cfo": {"CF"}, "capex_ppe": {"CF"}, "capex_intangible": {"CF"},
    }[metric]


def choose_metric(items: list[dict], metric: str) -> tuple[dict | None, str]:
    sectioned = [x for x in items if str(x.get("sj_div", "")) in canonical_section(metric)]
    by_id = [x for x in sectioned if str(x.get("account_id", "")) in PREFERRED_IDS[metric]]
    if len(by_id) == 1:
        return by_id[0], "standard_id"
    if len(by_id) > 1:
        exact = [x for x in by_id if exact_label(metric, x.get("account_nm", ""), str(x.get("sj_div", "")))]
        if len(exact) == 1:
            return exact[0], "standard_id_exact_label"
        return None, "ambiguous_standard_id"
    fallback = [x for x in sectioned if exact_label(metric, x.get("account_nm", ""), str(x.get("sj_div", "")))]
    if len(fallback) == 1:
        return fallback[0], "exact_label_fallback"
    if len(fallback) > 1:
        return None, "ambiguous_fallback"
    return None, "missing"


def fetch_statement(key: str, corp_code: str, year: int, reprt_code: str, fs_div: str) -> list[dict]:
    d = api_json("fnlttSinglAcntAll.json", key, corp_code=corp_code, bsns_year=str(year), reprt_code=reprt_code, fs_div=fs_div)
    return d.get("list", []) or []


def amount_for_period(row: dict | None, quarter: str) -> tuple[float | None, str]:
    if row is None:
        return None, "missing"
    # OpenDART flow statements may expose cumulative amount in thstrm_add_amount.
    add = num(row.get("thstrm_add_amount"))
    cur = num(row.get("thstrm_amount"))
    if quarter == "Q1":
        return (cur if cur is not None else add), "reported_q1"
    if add is not None:
        return add, "cumulative_add_amount"
    return cur, "reported_amount_assumed_cumulative"


def latest_disclosure(key: str, corp_code: str, year: int, quarter: str) -> tuple[str | None, str | None, str | None]:
    # Restrict search window around normal reporting season and choose earliest relevant public disclosure.
    windows = {
        "Q1": (f"{year}0401", f"{year}0531"),
        "Q2": (f"{year}0701", f"{year}0831"),
        "Q3": (f"{year}1001", f"{year}1130"),
        "Q4": (f"{year+1}0101", f"{year+1}0430"),
    }
    bgn, end = windows[quarter]
    d = api_json("list.json", key, corp_code=corp_code, bgn_de=bgn, end_de=end, page_count=100)
    xs = d.get("list", []) or []
    relevant = []
    for x in xs:
        nm = str(x.get("report_nm", ""))
        if any(k in nm for k in ["분기보고서", "반기보고서", "사업보고서", "영업(잠정)실적", "잠정실적", "매출액또는손익구조"]):
            relevant.append(x)
    if not relevant:
        return None, None, None
    relevant.sort(key=lambda x: (str(x.get("rcept_dt", "")), str(x.get("rcept_no", ""))))
    x = relevant[0]
    return str(x.get("rcept_dt", "")) or None, str(x.get("rcept_no", "")) or None, str(x.get("report_nm", "")) or None


def main() -> int:
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise SystemExit("DART_API_KEY is required")
    stocks, y0, y1 = parse_config()
    cm = corp_map(key).drop_duplicates("stock_code")
    cmap = cm.set_index("stock_code").to_dict("index")

    cumulative: dict[tuple[str, int, str, str], float | None] = {}
    raw_events: list[dict] = []
    api_errors = 0

    for stock in stocks:
        meta = cmap.get(stock)
        if not meta:
            raw_events.append({"stock_code": stock, "status": "corp_code_missing"})
            continue
        corp_code = meta["corp_code"]
        for year in range(y0, y1 + 1):
            chosen_basis = None
            quarter_rows: dict[str, dict] = {}
            for q, rc in REPORTS.items():
                selected_items = None
                basis_used = None
                for fs_div in ("CFS", "OFS"):
                    try:
                        items = fetch_statement(key, corp_code, year, rc, fs_div)
                    except Exception:
                        api_errors += 1
                        items = []
                    if items:
                        selected_items, basis_used = items, fs_div
                        break
                if not selected_items:
                    quarter_rows[q] = {"basis": None, "metrics": {}, "status": "no_statement"}
                    continue
                if chosen_basis is None:
                    chosen_basis = basis_used
                metrics = {}
                for m in PREFERRED_IDS:
                    row, rule = choose_metric(selected_items, m)
                    val, amount_method = amount_for_period(row, q)
                    metrics[m] = {
                        "value_raw_or_cumulative": val,
                        "selection_rule": rule,
                        "amount_method": amount_method,
                        "account_id": row.get("account_id") if row else None,
                        "account_nm": row.get("account_nm") if row else None,
                        "sj_div": row.get("sj_div") if row else None,
                    }
                    cumulative[(stock, year, q, m)] = val
                quarter_rows[q] = {"basis": basis_used, "metrics": metrics, "status": "ok"}

            prev_cum = {m: None for m in PREFERRED_IDS}
            for q in ("Q1", "Q2", "Q3", "Q4"):
                qr = quarter_rows[q]
                pure: dict[str, float | None] = {}
                for m in PREFERRED_IDS:
                    v = cumulative.get((stock, year, q, m))
                    if m == "equity":
                        pure[m] = v
                    elif q == "Q1":
                        pure[m] = v
                    else:
                        pure[m] = (v - prev_cum[m]) if (v is not None and prev_cum[m] is not None) else None
                    if m != "equity" and v is not None:
                        prev_cum[m] = v
                capex = None
                if pure["capex_ppe"] is not None or pure["capex_intangible"] is not None:
                    capex = (pure["capex_ppe"] or 0.0) + (pure["capex_intangible"] or 0.0)
                fcf = None if pure["cfo"] is None or capex is None else pure["cfo"] - capex
                rdt, rno, rnm = latest_disclosure(key, corp_code, year, q)
                raw_events.append({
                    "stock_code": stock,
                    "corp_code": corp_code,
                    "corp_name": meta.get("corp_name", ""),
                    "business_year": year,
                    "fiscal_quarter": q,
                    "statement_basis": qr.get("basis"),
                    "statement_status": qr.get("status"),
                    "operating_profit_q": pure["operating_profit"],
                    "net_income_q": pure["net_income"],
                    "equity_q_end": pure["equity"],
                    "cfo_q": pure["cfo"],
                    "capex_q": capex,
                    "fcf_q": fcf,
                    "earliest_relevant_disclosure_date": rdt,
                    "earliest_relevant_rcept_no": rno,
                    "earliest_relevant_report_nm": rnm,
                    "universe_source": "configured_stock_list_not_survivorship_free",
                    "modern_oos_protected": True,
                    "metric_selection_json": json.dumps(qr.get("metrics", {}), ensure_ascii=False),
                })

    df = pd.DataFrame(raw_events)
    if not df.empty and "business_year" in df:
        df = df.sort_values(["stock_code", "business_year", "fiscal_quarter"], na_position="last")
        # same-quarter YoY turnaround flag
        keycols = ["stock_code", "fiscal_quarter"]
        df["operating_profit_q_yoy_lag"] = df.groupby(keycols)["operating_profit_q"].shift(1)
        df["statement_basis_yoy_lag"] = df.groupby(keycols)["statement_basis"].shift(1)
        df["basis_comparable_yoy"] = df["statement_basis"].eq(df["statement_basis_yoy_lag"])
        df["op_turnaround_yoy"] = (
            (df["operating_profit_q"] > 0)
            & (df["operating_profit_q_yoy_lag"] <= 0)
            & df["basis_comparable_yoy"]
        )
        # TTM NI only when four sequential quarter values are available.
        df["net_income_ttm"] = df.groupby("stock_code")["net_income_q"].transform(lambda s: s.rolling(4, min_periods=4).sum())
        df["base_a_accounting_only"] = (
            df["op_turnaround_yoy"]
            & (df["net_income_ttm"] < 0)
            & (df["equity_q_end"] > 0)
        )
    df.to_csv(OUT_EVENTS, index=False)

    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_stage": "pre_oos_accounting_event_build",
        "modern_oos_protected": True,
        "start_year": y0,
        "end_year": y1,
        "configured_stocks": stocks,
        "rows": int(len(df)),
        "turnaround_rows": int(df.get("op_turnaround_yoy", pd.Series(dtype=bool)).fillna(False).sum()) if not df.empty else 0,
        "base_a_accounting_only_rows": int(df.get("base_a_accounting_only", pd.Series(dtype=bool)).fillna(False).sum()) if not df.empty else 0,
        "api_errors_caught": int(api_errors),
        "survivorship_free_universe_ready": False,
        "important_limitation": "This output validates accounting-event construction on a configured stock list. It is not yet the historical KOSPI/KOSDAQ survivor-free research universe and contains no returns or market-cap filter.",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
