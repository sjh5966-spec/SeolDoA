#!/usr/bin/env python3
"""Point-in-time data probe for the Korea turnaround replication.

This is deliberately a data audit, not a return backtest.
KRX and OpenDART are probed independently so a failure in one source does not
hide the status of the other.

Environment:
  DART_API_KEY   optional; required for OpenDART probe
  KOREA_PROBE_DATES comma-separated YYYYMMDD dates (optional)

Outputs (when available):
  korea_probe_krx_universe.csv
  korea_probe_dart_disclosures.csv
  korea_probe_summary.json
"""

from __future__ import annotations

import io
import json
import os
import re
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
            cap = stock.get_market_cap_by_ticker(d, market=market).copy()
            cap.index = cap.index.astype(str)
            for ticker in tickers:
                t = str(ticker)
                try:
                    name = stock.get_market_ticker_name(t)
                except Exception:
                    name = ""
                rec = cap.loc[t] if t in cap.index else None
                rows.append({
                    "asof_date": pd.to_datetime(d, format="%Y%m%d").date().isoformat(),
                    "market": market,
                    "ticker": t,
                    "name_current_lookup": name,
                    "close": None if rec is None else float(rec.get("종가", float("nan"))),
                    "market_cap_krw": None if rec is None else float(rec.get("시가총액", float("nan"))),
                    "shares": None if rec is None else float(rec.get("상장주식수", float("nan"))),
                })
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
    rows = [{child.tag: (child.text or "").strip() for child in item} for item in root.findall("list")]
    return pd.DataFrame(rows)


def probe_dart_independent(key: str) -> tuple[pd.DataFrame, dict]:
    """Validate the key and disclosure endpoint without depending on KRX."""
    corp = load_corp_codes(key)
    listed = corp[corp.get("stock_code", pd.Series(dtype=str)).astype(str).str.fullmatch(r"\d{6}", na=False)].copy()

    # A small market-wide disclosure query validates list.json independently of ticker mapping.
    data = _dart_get_json(
        "list.json",
        key,
        bgn_de="20260901",
        end_de="20260907",
        page_count=100,
    )
    rows = []
    for x in data.get("list", []) or []:
        rows.append({
            "corp_code": x.get("corp_code"),
            "corp_name": x.get("corp_name"),
            "stock_code": x.get("stock_code"),
            "corp_cls": x.get("corp_cls"),
            "report_nm": x.get("report_nm"),
            "rcept_no": x.get("rcept_no"),
            "rcept_dt": x.get("rcept_dt"),
            "flr_nm": x.get("flr_nm"),
            "rm": x.get("rm"),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DART, index=False)
    meta = {
        "dart_corp_codes": int(len(corp)),
        "dart_listed_stock_codes": int(len(listed)),
        "dart_rows": int(len(df)),
        "dart_unique_receipts": int(df["rcept_no"].nunique()) if "rcept_no" in df.columns else 0,
        "dart_probe_window": ["20260901", "20260907"],
    }
    return df, meta


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

    try:
        universe = probe_krx(dates)
        summary["krx_probe_ok"] = True
        summary["krx_rows"] = int(len(universe))
        summary["krx_counts"] = universe.groupby(["asof_date", "market"]).size().rename("n").reset_index().to_dict("records")
    except Exception as exc:
        summary["krx_error_type"] = type(exc).__name__
        summary["krx_error"] = str(exc)[:1000]

    key = os.getenv("DART_API_KEY", "").strip()
    if key:
        try:
            _, meta = probe_dart_independent(key)
            summary.update(meta)
            summary["dart_probe_ok"] = True
        except Exception as exc:
            summary["dart_error_type"] = type(exc).__name__
            summary["dart_error"] = str(exc)[:1000]
    else:
        summary["dart_note"] = "DART_API_KEY not present; OpenDART probe skipped."

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # This audit intentionally exits successfully when one source fails; source-level
    # pass/fail is recorded in the summary so CI can persist evidence for diagnosis.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
