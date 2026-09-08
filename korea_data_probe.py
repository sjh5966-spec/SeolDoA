#!/usr/bin/env python3
"""Point-in-time data probe for the Korea turnaround replication.

This is deliberately a data audit, not a return backtest.
It tests whether we can reconstruct historical KRX universes/prices and OpenDART
filing metadata without silently using today's survivor set.

Environment:
  DART_API_KEY   optional for KRX-only probe; required for OpenDART probe
  KOREA_PROBE_DATES comma-separated YYYYMMDD dates (optional)

Outputs:
  korea_probe_krx_universe.csv
  korea_probe_dart_disclosures.csv (only when DART_API_KEY is present)
  korea_probe_summary.json
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from pykrx import stock

OUT_UNIVERSE = Path("korea_probe_krx_universe.csv")
OUT_DART = Path("korea_probe_dart_disclosures.csv")
OUT_SUMMARY = Path("korea_probe_summary.json")

DEFAULT_PROBE_DATES = ["20151230", "20201230", "20221229", "20260904"]
DART_BASE = "https://opendart.fss.or.kr/api"


def _probe_dates() -> list[str]:
    raw = os.getenv("KOREA_PROBE_DATES", "").strip()
    dates = [x.strip().replace("-", "") for x in raw.split(",") if x.strip()] if raw else DEFAULT_PROBE_DATES
    for d in dates:
        if not re.fullmatch(r"\d{8}", d):
            raise ValueError(f"invalid probe date: {d}")
    return dates


def probe_krx(dates: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for d in dates:
        for market in ("KOSPI", "KOSDAQ"):
            tickers = stock.get_market_ticker_list(d, market=market)
            cap = stock.get_market_cap_by_ticker(d, market=market)
            cap = cap.copy()
            cap.index = cap.index.astype(str)
            for ticker in tickers:
                t = str(ticker)
                try:
                    name = stock.get_market_ticker_name(t)
                except Exception:
                    name = ""
                rec = cap.loc[t] if t in cap.index else None
                rows.append(
                    {
                        "asof_date": pd.to_datetime(d, format="%Y%m%d").date().isoformat(),
                        "market": market,
                        "ticker": t,
                        "name_current_lookup": name,
                        "close": None if rec is None else float(rec.get("종가", float("nan"))),
                        "market_cap_krw": None if rec is None else float(rec.get("시가총액", float("nan"))),
                        "shares": None if rec is None else float(rec.get("상장주식수", float("nan"))),
                    }
                )
    df = pd.DataFrame(rows)
    df.to_csv(OUT_UNIVERSE, index=False)
    return df


def _dart_get_json(path: str, key: str, **params) -> dict:
    q = {"crtfc_key": key, **params}
    r = requests.get(f"{DART_BASE}/{path}", params=q, timeout=60)
    r.raise_for_status()
    data = r.json()
    status = data.get("status")
    if status not in (None, "000", "013"):
        raise RuntimeError(f"OpenDART {path} status={status}: {data.get('message')}")
    return data


def load_corp_codes(key: str) -> pd.DataFrame:
    r = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        if not names:
            raise RuntimeError("OpenDART corpCode archive was empty")
        raw = zf.read(names[0])
    import xml.etree.ElementTree as ET

    root = ET.fromstring(raw)
    rows = []
    for item in root.findall("list"):
        rows.append({child.tag: (child.text or "").strip() for child in item})
    df = pd.DataFrame(rows)
    if "stock_code" in df.columns:
        df = df[df["stock_code"].astype(str).str.fullmatch(r"\d{6}", na=False)].copy()
    return df


def probe_dart(key: str, universe: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    """Probe a small deterministic issuer sample from each historical snapshot.

    We intentionally sample the smallest positive-market-cap names at each snapshot,
    because the final strategy is expected to focus on small/micro caps.
    """
    corp = load_corp_codes(key)
    ticker_to_corp = corp.set_index("stock_code")["corp_code"].to_dict()
    samples = []
    for d in dates:
        iso = pd.to_datetime(d, format="%Y%m%d").date().isoformat()
        sub = universe[(universe["asof_date"] == iso) & universe["market_cap_krw"].notna() & (universe["market_cap_krw"] > 0)]
        sub = sub.sort_values("market_cap_krw").head(5)
        for _, row in sub.iterrows():
            ticker = str(row["ticker"]).zfill(6)
            corp_code = ticker_to_corp.get(ticker)
            if not corp_code:
                continue
            year = int(d[:4])
            begin = f"{year}0101"
            end = f"{year}1231"
            data = _dart_get_json(
                "list.json",
                key,
                corp_code=corp_code,
                bgn_de=begin,
                end_de=end,
                page_count=100,
            )
            for x in data.get("list", []) or []:
                report_nm = str(x.get("report_nm", ""))
                # Keep periodic reports and earnings-related preliminary/management result disclosures.
                if not any(k in report_nm for k in ("사업보고서", "반기보고서", "분기보고서", "영업(잠정)실적", "잠정실적", "매출액또는손익구조")):
                    continue
                samples.append(
                    {
                        "snapshot_date": iso,
                        "ticker": ticker,
                        "corp_code": corp_code,
                        "corp_name": x.get("corp_name"),
                        "corp_cls": x.get("corp_cls"),
                        "report_nm": report_nm,
                        "rcept_no": x.get("rcept_no"),
                        "rcept_dt": x.get("rcept_dt"),
                        "flr_nm": x.get("flr_nm"),
                        "rm": x.get("rm"),
                    }
                )
    df = pd.DataFrame(samples)
    df.to_csv(OUT_DART, index=False)
    return df


def main() -> int:
    dates = _probe_dates()
    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "probe_dates": dates,
        "research_stage": "data_audit_only",
        "krx_probe_ok": False,
        "dart_probe_ok": False,
        "dart_api_key_present": bool(os.getenv("DART_API_KEY", "").strip()),
    }

    universe = probe_krx(dates)
    summary["krx_probe_ok"] = True
    summary["krx_rows"] = int(len(universe))
    summary["krx_counts"] = (
        universe.groupby(["asof_date", "market"]).size().rename("n").reset_index().to_dict("records")
    )

    key = os.getenv("DART_API_KEY", "").strip()
    if key:
        ddf = probe_dart(key, universe, dates)
        summary["dart_probe_ok"] = True
        summary["dart_rows"] = int(len(ddf))
        summary["dart_unique_receipts"] = int(ddf["rcept_no"].nunique()) if "rcept_no" in ddf.columns else 0
    else:
        summary["dart_note"] = "DART_API_KEY not present; KRX point-in-time universe probe completed, OpenDART probe skipped."

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
