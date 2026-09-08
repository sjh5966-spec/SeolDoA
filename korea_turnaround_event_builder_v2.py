#!/usr/bin/env python3
"""Pre-OOS wrapper for Korea event builder with IS/CIS operating-profit mapping.

This correction is based only on <=2022 accounting data. It does not open or
inspect 2023+ Korean OOS returns.
"""
import re
import korea_turnaround_event_builder as base

_original_exact_label = base.exact_label
_original_canonical_section = base.canonical_section


def exact_label(metric: str, name: str, sj_div: str) -> bool:
    if metric == "operating_profit":
        n = re.sub(r"\s+", "", str(name or ""))
        return sj_div in {"IS", "CIS"} and n in {"영업이익", "영업손실", "영업이익(손실)"}
    return _original_exact_label(metric, name, sj_div)


def canonical_section(metric: str) -> set[str]:
    if metric == "operating_profit":
        return {"IS", "CIS"}
    return _original_canonical_section(metric)


base.exact_label = exact_label
base.canonical_section = canonical_section

if __name__ == "__main__":
    raise SystemExit(base.main())
