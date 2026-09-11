#!/usr/bin/env python3
"""Validation-only wrapper around the frozen quarterly accounting collector v2.1.

2021 is collected Q1-Q4. 2022 is collected Q1-Q3 only because 2022 Q4 annual
figures are disclosed in 2023 and must remain unopened before the OOS gate.
No market data are accessed here.
"""
from pathlib import Path

src = Path('korea_dart_quarterly_collector_v2.py').read_text(encoding='utf-8')
src = src.replace("HISTORICAL_SEED=Path('korea_dart_historical_seed_2015_2020.csv')", "HISTORICAL_SEED=Path('korea_validation_historical_seed_2021_2022.csv')")
src = src.replace("SMOKE_SEED=Path('korea_dart_quarterly_seed_2015_2020.csv')", "SMOKE_SEED=Path('__validation_no_smoke_fallback__.csv')")
src = src.replace(
    "if year<2016 or year>2020: raise SystemExit('v2.1 supports 2016..2020 only; use the receipt-specific 2015 XBRL collector for 2015')",
    "if year<2021 or year>2022: raise SystemExit('validation wrapper supports 2021..2022 only')\n    if year==2022: REPORTS[:] = [x for x in REPORTS if x[0] != 'Q4']"
)
src = src.replace("'research_stage':'development_quarterly_accounting_collection'", "'research_stage':'validation_quarterly_accounting_collection'")
src = src.replace("'modern_oos_protected':True,'year':year", "'modern_oos_protected':True,'validation_only':True,'year':year")
exec(compile(src, 'korea_dart_quarterly_collector_v2.py[validation-wrapper]', 'exec'), {'__name__':'__main__','__file__':'korea_validation_quarterly_collector_v1.py'})
