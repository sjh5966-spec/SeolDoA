#!/usr/bin/env python3
"""V2 FINAL OOS historical filing universe wrapper.

IMPORTANT: this file was added only after KOREA_TURNAROUND_V2_FINAL_PREOOS_LOCK.md
was committed. It opens the one-time frozen OOS signal window 2023-01-01..2025-12-31.
Target fiscal years 2022..2025 are needed because annual FY 2022 disclosures occur in 2023.
FY 2025 annual disclosures in 2026 are intentionally excluded from the primary OOS.
"""
from pathlib import Path

src = Path('korea_dart_historical_universe_v1.py').read_text(encoding='utf-8')
src = src.replace(
    "if year<2015 or year>2020: raise SystemExit('year must be 2015..2020')",
    "if year<2022 or year>2025: raise SystemExit('V2 OOS wrapper supports fiscal years 2022..2025 only')"
)
src = src.replace(
    "start=date(year,1,1); end=date(year+1,4,30)",
    "start=date(year,1,1); end=(date(2025,12,31) if year==2025 else date(year+1,4,30))"
)
src = src.replace("'research_stage':'development_historical_dart_universe'", "'research_stage':'v2_final_oos_historical_dart_universe'")
src = src.replace("'modern_oos_protected':True,'year':year", "'modern_oos_protected':False,'v2_final_oos':True,'year':year")
exec(compile(src, 'korea_dart_historical_universe_v1.py[v2-oos-wrapper]', 'exec'), {'__name__':'__main__','__file__':'korea_turnaround_v2_oos_historical_universe.py'})
