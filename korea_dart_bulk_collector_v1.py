#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from collections import Counter
from playwright.sync_api import sync_playwright

PAGE = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
START_YEAR = 2016
END_YEAR = 2020
ALLOWED_PERIODS = {"FQ", "HY", "TQ", "FY"}
ALLOWED_STATEMENTS = {"BS", "PL", "CF"}
OUT_DIR = Path("korea_dart_bulk_raw_2016_2020")
MANIFEST = Path("korea_dart_bulk_manifest_2016_2020.csv")
SUMMARY = Path("korea_dart_bulk_collection_summary.json")
SCHEMA = Path("korea_dart_bulk_schema_samples.json")

CALL_RX = re.compile(
    r"download_ext002\('(20\d{2})','(FQ|HY|TQ|FY)',\s*'(BS|PL|CF|CE)',\s*'([^']+\.zip)'\)"
)


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", errors="replace")


def inspect_zip(path: Path) -> dict:
    rec = {"zip_ok": False, "entry_count": 0, "entries": [], "sample_header": [], "sample_columns": []}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            rec["zip_ok"] = True
            rec["entry_count"] = len(names)
            rec["entries"] = names[:20]
            text_names = [n for n in names if n.lower().endswith((".txt", ".tsv", ".csv"))]
            if text_names:
                raw = zf.read(text_names[0])
                txt = decode_text(raw)
                lines = txt.splitlines()
                rec["sample_header"] = lines[:3]
                if lines:
                    rec["sample_columns"] = lines[0].split("\t")
    except Exception as e:
        rec["error"] = str(e)
    return rec


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    rows = []
    schema_samples = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.goto(PAGE, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(1500)

        anchors = page.locator("a[onclick*='download_ext002']")
        calls = []
        for i in range(anchors.count()):
            onclick = anchors.nth(i).get_attribute("onclick") or ""
            m = CALL_RX.search(onclick)
            if not m:
                continue
            year = int(m.group(1))
            period, stmt, filename = m.group(2), m.group(3), m.group(4)
            # Hard Development guardrail: never download 2021+ here.
            if START_YEAR <= year <= END_YEAR and period in ALLOWED_PERIODS and stmt in ALLOWED_STATEMENTS:
                calls.append((year, period, stmt, filename))

        calls = sorted(set(calls))
        expected = (END_YEAR - START_YEAR + 1) * 4 * 3
        if len(calls) != expected:
            raise RuntimeError(f"Expected {expected} development bulk calls, found {len(calls)}")

        for idx, (year, period, stmt, filename) in enumerate(calls, 1):
            target = OUT_DIR / filename
            status = "cached"
            error = ""
            if not target.exists() or target.stat().st_size == 0:
                try:
                    with page.expect_download(timeout=120000) as di:
                        page.evaluate(
                            "([y,p,s,f]) => download_ext002(y,p,s,f)",
                            [str(year), period, stmt, filename],
                        )
                    download = di.value
                    download.save_as(str(target))
                    status = "downloaded"
                except Exception as e:
                    status = "download_error"
                    error = str(e)

            inspection = inspect_zip(target) if target.exists() else {"zip_ok": False, "entry_count": 0}
            if inspection.get("zip_ok") and f"{period}_{stmt}" not in schema_samples:
                schema_samples[f"{period}_{stmt}"] = {
                    "year": year,
                    "filename": filename,
                    "entries": inspection.get("entries"),
                    "sample_header": inspection.get("sample_header"),
                    "sample_columns": inspection.get("sample_columns"),
                }

            rows.append({
                "year": year,
                "period": period,
                "statement": stmt,
                "filename": filename,
                "status": status,
                "bytes": target.stat().st_size if target.exists() else 0,
                "zip_ok": bool(inspection.get("zip_ok")),
                "entry_count": int(inspection.get("entry_count", 0)),
                "error": error or inspection.get("error", ""),
            })
            print(f"[{idx:02d}/{len(calls)}] {year} {period} {stmt}: {status}, zip_ok={inspection.get('zip_ok')}")

        browser.close()

    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    SCHEMA.write_text(json.dumps(schema_samples, ensure_ascii=False, indent=2), encoding="utf-8")
    statuses = Counter(r["status"] for r in rows)
    summary = {
        "research_stage": "development_bulk_financial_collection",
        "development_only": True,
        "start_year": START_YEAR,
        "end_year": END_YEAR,
        "modern_oos_protected": True,
        "expected_files": 60,
        "manifest_rows": len(rows),
        "zip_ok": sum(bool(r["zip_ok"]) for r in rows),
        "download_errors": sum(r["status"] == "download_error" for r in rows),
        "status_counts": dict(statuses),
        "total_bytes": sum(int(r["bytes"]) for r in rows),
        "schema_sample_groups": sorted(schema_samples),
        "important_note": "Bulk files are current downloadable snapshots and may reflect later corrections; use for accounting reconstruction/QC, then confirm candidate PIT values and signal date from original disclosure.",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["zip_ok"] != 60 or summary["download_errors"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
