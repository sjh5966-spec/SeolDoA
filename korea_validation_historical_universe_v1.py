#!/usr/bin/env python3
"""Validation-only historical DART universe wrapper.

Reuses the frozen Development universe builder while extending only to 2021-2022.
Hard guard: no filing search after 2022-12-31, so 2023+ OOS remains untouched.
"""
from pathlib import Path

src = Path('korea_dart_historical_universe_v1.py').read_text(encoding='utf-8')
src = src.replace(
    "if year<2015 or year>2020: raise SystemExit('year must be 2015..2020')",
    "if year<2021 or year>2022: raise SystemExit('validation wrapper supports 2021..2022 only')"
)
src = src.replace(
    "start=date(year,1,1); end=date(year+1,4,30)",
    "start=date(year,1,1); end=(date(2022,12,31) if year==2022 else date(year+1,4,30))"
)
src = src.replace("'research_stage':'development_historical_dart_universe'", "'research_stage':'validation_historical_dart_universe'")
src = src.replace("'modern_oos_protected':True,'year':year", "'modern_oos_protected':True,'validation_only':True,'year':year")
exec(compile(src, 'korea_dart_historical_universe_v1.py[validation-wrapper]', 'exec'), {'__name__':'__main__','__file__':'korea_validation_historical_universe_v1.py'})
