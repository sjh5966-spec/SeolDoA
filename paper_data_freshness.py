from pathlib import Path
from datetime import datetime, timezone, date
import json, os
import duckdb

BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'
P=BASE+'stock_prices.parquet'
F=BASE+'stock_sec_filing.parquet'
OUT=Path('paper_data_freshness.json')
START=date.fromisoformat(os.environ.get('PAPER_START_DATE','2026-09-07'))

con=duckdb.connect()
con.execute('INSTALL httpfs; LOAD httpfs')
con.execute("SET threads=4; SET memory_limit='4GB'")

max_statement=con.execute(f"SELECT MAX(TRY_CAST(report_date AS DATE)) FROM read_parquet('{S}') WHERE report_date<>'TTM'").fetchone()[0]
max_filing=con.execute(f"SELECT MAX(TRY_CAST(filing_date AS DATE)) FROM read_parquet('{F}') WHERE TRY_CAST(filing_date AS DATE) IS NOT NULL").fetchone()[0]
max_price=con.execute(f"SELECT MAX(TRY_CAST(report_date AS DATE)) FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) IS NOT NULL").fetchone()[0]
filing_cols=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{F}') LIMIT 1").fetchdf()['column_name'].tolist()
ts_candidates=['acceptance_datetime','accepted_datetime','filing_datetime','filed_at','accepted_at','acceptance_time','filing_time']
ts_col=next((c for c in ts_candidates if c in filing_cols),None)

filing_covers_start = bool(max_filing and max_filing >= START)
statement_covers_start = bool(max_statement and max_statement >= START)
price_covers_start = bool(max_price and max_price >= START)
# A zero-signal result is operationally conclusive only when both fundamentals and filings
# have reached the paper period. Prices may legitimately lag the current calendar by non-trading days.
zero_signal_interpretation = 'conclusive_for_available_source' if filing_covers_start and statement_covers_start else 'nonconclusive_source_not_yet_covering_paper_start'

status={
  'checked_at_utc': datetime.now(timezone.utc).isoformat(),
  'paper_start_date': START.isoformat(),
  'max_statement_report_date': max_statement.isoformat() if max_statement else None,
  'max_filing_date': max_filing.isoformat() if max_filing else None,
  'max_price_date': max_price.isoformat() if max_price else None,
  'filing_timestamp_column': ts_col,
  'filing_covers_paper_start': filing_covers_start,
  'statement_covers_paper_start': statement_covers_start,
  'price_covers_paper_start': price_covers_start,
  'zero_signal_interpretation': zero_signal_interpretation,
}
OUT.write_text(json.dumps(status,indent=2)+'\n')
print(json.dumps(status,indent=2))
