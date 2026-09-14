#!/usr/bin/env python3
"""V2 FINAL OOS accounting collector wrapper, created after the final pre-OOS lock.

Fiscal years 2022..2025 are collected. FY2025 Q4 is excluded because its disclosure
would be in 2026, outside the frozen primary OOS signal window ending 2025-12-31.
"""
from pathlib import Path

src = Path('korea_dart_quarterly_collector_v2.py').read_text(encoding='utf-8')
src = src.replace("HISTORICAL_SEED=Path('korea_dart_historical_seed_2015_2020.csv')", "HISTORICAL_SEED=Path('korea_turnaround_v2_oos_seed_2022_2025.csv')")
src = src.replace("SMOKE_SEED=Path('korea_dart_quarterly_seed_2015_2020.csv')", "SMOKE_SEED=Path('__v2_oos_no_smoke_fallback__.csv')")
src = src.replace(
    "if year<2016 or year>2020: raise SystemExit('v2.1 supports 2016..2020 only; use the receipt-specific 2015 XBRL collector for 2015')",
    "if year<2022 or year>2025: raise SystemExit('V2 final OOS wrapper supports 2022..2025 only')\n    if year==2025: REPORTS[:] = [x for x in REPORTS if x[0] != 'Q4']"
)
src = src.replace("'research_stage':'development_quarterly_accounting_collection'", "'research_stage':'v2_final_oos_quarterly_accounting_collection'")
src = src.replace("'modern_oos_protected':True,'year':year", "'modern_oos_protected':False,'v2_final_oos':True,'year':year")
exec(compile(src, 'korea_dart_quarterly_collector_v2.py[v2-oos-wrapper]', 'exec'), {'__name__':'__main__','__file__':'korea_turnaround_v2_oos_quarterly_collector.py'})
