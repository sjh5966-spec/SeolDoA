import json
import os
from pathlib import Path

import duckdb

BASE = "https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/"
STATEMENT = BASE + "stock_statement.parquet"
PRICES = BASE + "stock_prices.parquet"
SHARES = BASE + "stock_shares_outstanding.parquet"
FILINGS = BASE + "stock_sec_filing.parquet"

OUT = Path("results")
OUT.mkdir(exist_ok=True)

con = duckdb.connect("backtest.duckdb")
con.execute("SET threads=4")
con.execute("SET memory_limit='6GB'")

print("Building normalized quarterly panel...")
con.execute(f"""
CREATE OR REPLACE TABLE q_raw AS
SELECT
  symbol,
  TRY_CAST(report_date AS DATE) AS report_date,
  MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE AS ebit_q,
  MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE AS ni_q,
  MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE AS equity_q
FROM read_parquet('{STATEMENT}')
WHERE period_type='quarterly'
  AND report_date <> 'TTM'
  AND item_name IN ('ebit','net_income','stockholders_equity')
  AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2022-01-01' AND DATE '2026-08-26'
GROUP BY 1,2
HAVING report_date IS NOT NULL
""")

con.execute("""
CREATE OR REPLACE TABLE q_panel AS
WITH w AS (
  SELECT *,
    LAG(report_date,1) OVER (PARTITION BY symbol ORDER BY report_date) AS d1,
    LAG(report_date,2) OVER (PARTITION BY symbol ORDER BY report_date) AS d2,
    LAG(report_date,3) OVER (PARTITION BY symbol ORDER BY report_date) AS d3,
    LAG(report_date,4) OVER (PARTITION BY symbol ORDER BY report_date) AS d4,
    LAG(ebit_q,4) OVER (PARTITION BY symbol ORDER BY report_date) AS ebit_yoy,
    SUM(ni_q) OVER (PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS ni_ttm,
    COUNT(ni_q) OVER (PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS ni4_n
  FROM q_raw
)
SELECT *
FROM w
WHERE ni4_n=4
  AND d3 IS NOT NULL AND d4 IS NOT NULL
  AND date_diff('day', d3, report_date) BETWEEN 240 AND 400
  AND date_diff('day', d4, report_date) BETWEEN 300 AND 450
""")

print("Building original filing table...")
con.execute(f"""
CREATE OR REPLACE TABLE filings AS
SELECT
  symbol,
  TRY_CAST(report_date AS DATE) AS report_date,
  MIN(TRY_CAST(filing_date AS DATE)) AS filing_date,
  ARG_MIN(form_type, TRY_CAST(filing_date AS DATE)) AS form_type,
  ARG_MIN(accession_number, TRY_CAST(filing_date AS DATE)) AS accession_number
FROM read_parquet('{FILINGS}')
WHERE form_type IN ('10-Q','10-K')
  AND TRY_CAST(report_date AS DATE) IS NOT NULL
  AND TRY_CAST(filing_date AS DATE) IS NOT NULL
GROUP BY 1,2
""")

print("Building prices and shares...")
con.execute(f"""
CREATE OR REPLACE TABLE prices AS
SELECT symbol, TRY_CAST(report_date AS DATE) AS d,
       open::DOUBLE AS open, close::DOUBLE AS close,
       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) AS rn
FROM read_parquet('{PRICES}')
WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2021-01-01' AND DATE '2026-08-26'
  AND open IS NOT NULL AND close IS NOT NULL
""")
con.execute(f"""
CREATE OR REPLACE TABLE shares AS
SELECT symbol, TRY_CAST(report_date AS DATE) AS d, shares_outstanding::DOUBLE AS shares_outstanding
FROM read_parquet('{SHARES}')
WHERE TRY_CAST(report_date AS DATE) IS NOT NULL
  AND shares_outstanding IS NOT NULL AND shares_outstanding > 0
""")

print("Generating pre-market-cap signal candidates...")
con.execute("""
CREATE OR REPLACE TABLE candidates_pre_marketcap AS
SELECT
  ROW_NUMBER() OVER () AS event_id,
  q.symbol, q.report_date, f.filing_date, f.form_type, f.accession_number,
  q.ebit_q, q.ebit_yoy, q.ni_q, q.ni_ttm, q.equity_q,
  CASE WHEN q.ni_ttm < 0 THEN 'A' WHEN q.ni_ttm > 0 THEN 'D' END AS signal
FROM q_panel q
JOIN filings f USING(symbol, report_date)
WHERE q.ebit_q > 0
  AND q.ebit_yoy <= 0
  AND q.equity_q > 0
  AND q.ni_ttm <> 0
""")

print("Applying point-in-time market cap and entry rules...")
con.execute("""
CREATE OR REPLACE TABLE events_base AS
WITH x AS (
 SELECT c.*,
   (SELECT s.shares_outstanding FROM shares s
      WHERE s.symbol=c.symbol AND s.d <= c.report_date
      ORDER BY s.d DESC LIMIT 1) AS shares_asof,
   (SELECT p.close FROM prices p
      WHERE p.symbol=c.symbol AND p.d <= c.filing_date
      ORDER BY p.d DESC LIMIT 1) AS signal_close,
   (SELECT p.rn FROM prices p
      WHERE p.symbol=c.symbol AND p.d > c.filing_date
      ORDER BY p.d ASC LIMIT 1) AS entry_rn,
   (SELECT p.d FROM prices p
      WHERE p.symbol=c.symbol AND p.d > c.filing_date
      ORDER BY p.d ASC LIMIT 1) AS entry_date,
   (SELECT p.open FROM prices p
      WHERE p.symbol=c.symbol AND p.d > c.filing_date
      ORDER BY p.d ASC LIMIT 1) AS entry_price,
   (SELECT MIN(f2.filing_date) FROM filings f2
      WHERE f2.symbol=c.symbol AND f2.filing_date > c.filing_date) AS next_filing_date
 FROM candidates_pre_marketcap c
)
SELECT *, shares_asof * signal_close AS market_cap
FROM x
WHERE shares_asof IS NOT NULL AND signal_close IS NOT NULL
  AND entry_rn IS NOT NULL AND entry_price > 0
  AND shares_asof * signal_close BETWEEN 10000000 AND 300000000
""")

print("Computing forward returns...")
con.execute("""
CREATE OR REPLACE TABLE events AS
SELECT e.*,
  p20.d AS d20,  p20.close/e.entry_price - 1 AS r20d,
  p60.d AS d60,  p60.close/e.entry_price - 1 AS r60d,
  p120.d AS d120, p120.close/e.entry_price - 1 AS r120d,
  p250.d AS d250, p250.close/e.entry_price - 1 AS r250d,
  (SELECT p.close/e.entry_price - 1 FROM prices p
     WHERE p.symbol=e.symbol AND e.next_filing_date IS NOT NULL AND p.d < e.next_filing_date
     ORDER BY p.d DESC LIMIT 1) AS r_next_filing
FROM events_base e
LEFT JOIN prices p20  ON p20.symbol=e.symbol  AND p20.rn=e.entry_rn+20
LEFT JOIN prices p60  ON p60.symbol=e.symbol  AND p60.rn=e.entry_rn+60
LEFT JOIN prices p120 ON p120.symbol=e.symbol AND p120.rn=e.entry_rn+120
LEFT JOIN prices p250 ON p250.symbol=e.symbol AND p250.rn=e.entry_rn+250
""")

summary_sql = """
SELECT signal,
  COUNT(*) AS n_events,
  COUNT(r60d) AS n_r60,
  MEDIAN(r20d) AS median_r20d,
  MEDIAN(r60d) AS median_r60d,
  MEDIAN(r_next_filing) AS median_r_next_filing,
  MEDIAN(r120d) AS median_r120d,
  MEDIAN(r250d) AS median_r250d,
  AVG(CASE WHEN r60d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE r60d IS NOT NULL) AS win_rate_r60,
  AVG(CASE WHEN r60d >= 0.20 THEN 1.0 ELSE 0.0 END) FILTER (WHERE r60d IS NOT NULL) AS tail_up_20_r60,
  AVG(CASE WHEN r60d <= -0.20 THEN 1.0 ELSE 0.0 END) FILTER (WHERE r60d IS NOT NULL) AS tail_down_20_r60,
  QUANTILE_CONT(r60d,0.10) AS q10_r60,
  QUANTILE_CONT(r60d,0.25) AS q25_r60,
  QUANTILE_CONT(r60d,0.50) AS q50_r60,
  QUANTILE_CONT(r60d,0.75) AS q75_r60,
  QUANTILE_CONT(r60d,0.90) AS q90_r60
FROM events
GROUP BY signal
ORDER BY signal
"""
summary = con.execute(summary_sql).fetchall()
summary_cols = [d[0] for d in con.description]

con.execute(f"COPY candidates_pre_marketcap TO '{OUT / 'candidates_pre_marketcap.csv'}' (HEADER, DELIMITER ',')")
con.execute(f"COPY events TO '{OUT / 'events.csv'}' (HEADER, DELIMITER ',')")
con.execute(f"COPY ({summary_sql}) TO '{OUT / 'summary.csv'}' (HEADER, DELIMITER ',')")

counts = dict(con.execute("SELECT signal, COUNT(*) FROM events GROUP BY 1").fetchall())
pre_counts = dict(con.execute("SELECT signal, COUNT(*) FROM candidates_pre_marketcap GROUP BY 1").fetchall())
coverage = con.execute("SELECT MIN(report_date), MAX(report_date), COUNT(DISTINCT symbol), COUNT(*) FROM events").fetchone()

diagnostics = {
    "data_source": "defeatbeta/yahoo-finance-data",
    "quarterly_source_start": "2022",
    "rules": {
        "market_cap": "$10M-$300M at filing using latest close <= filing date x latest shares <= fiscal report date",
        "signal_A": "EBIT_Q>0, EBIT_Q-4<=0, NI_TTM<0, Equity_Q>0",
        "signal_D": "same but NI_TTM>0",
        "filings": "original 10-Q/10-K only; amendments excluded",
        "entry": "next trading day open after filing date",
        "next_filing_return": "entry open to last close strictly before next original 10-Q/10-K filing",
    },
    "pre_marketcap_counts": pre_counts,
    "final_counts": counts,
    "coverage": {
        "min_report_date": str(coverage[0]) if coverage[0] else None,
        "max_report_date": str(coverage[1]) if coverage[1] else None,
        "distinct_symbols": coverage[2],
        "events": coverage[3],
    },
    "summary_columns": summary_cols,
    "summary_rows": [list(map(lambda x: float(x) if isinstance(x, (int,float)) and not isinstance(x,bool) else x, r)) for r in summary],
}
with open(OUT / "diagnostics.json", "w") as f:
    json.dump(diagnostics, f, indent=2, default=str)

print("SUMMARY")
print(summary_cols)
for r in summary:
    print(r)
print("DIAGNOSTICS", json.dumps(diagnostics, default=str))
