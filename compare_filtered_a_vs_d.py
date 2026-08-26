from pathlib import Path
import csv,duckdb
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'; P=BASE+'stock_prices.parquet'; SH=BASE+'stock_shares_outstanding.parquet'; F=BASE+'stock_sec_filing.parquet'
OUT=Path('compare_results'); OUT.mkdir(exist_ok=True)
con=duckdb.connect('compare.duckdb'); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
con.execute(f"""CREATE TABLE q AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE ebit,
MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE net_income,
MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE equity,
MAX(CASE WHEN item_name='total_revenue' AND finance_type='income_statement' THEN item_value END)::DOUBLE revenue,
MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN item_value END)::DOUBLE fcf
FROM read_parquet('{S}') WHERE period_type='quarterly' AND report_date<>'TTM' AND item_name IN ('ebit','net_income','stockholders_equity','total_revenue','free_cash_flow') AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2022-01-01' AND DATE '2026-08-26' GROUP BY 1,2""")
con.execute("""CREATE TABLE qp AS WITH w AS (SELECT *,LAG(report_date,4) OVER(PARTITION BY symbol ORDER BY report_date) d4,LAG(ebit,4) OVER(PARTITION BY symbol ORDER BY report_date) ebit_yoy,LAG(fcf,4) OVER(PARTITION BY symbol ORDER BY report_date) fcf_yoy,SUM(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni_ttm,COUNT(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni4 FROM q) SELECT *,fcf-fcf_yoy fcf_yoy_change FROM w WHERE ni4=4 AND d4 IS NOT NULL""")
con.execute(f"""CREATE TABLE filings AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,MIN(TRY_CAST(filing_date AS DATE)) filing_date FROM read_parquet('{F}') WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(report_date AS DATE) IS NOT NULL AND TRY_CAST(filing_date AS DATE) IS NOT NULL GROUP BY 1,2""")
con.execute(f"""CREATE TABLE prices AS SELECT symbol,TRY_CAST(report_date AS DATE) d,open::DOUBLE px_open,close::DOUBLE px_close,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2021-01-01' AND DATE '2026-08-26' AND open IS NOT NULL AND close IS NOT NULL""")
con.execute(f"""CREATE TABLE shares AS SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding FROM read_parquet('{SH}') WHERE TRY_CAST(report_date AS DATE) IS NOT NULL AND shares_outstanding>0""")
con.execute("""CREATE TABLE events0 AS WITH c AS (SELECT q.*,f.filing_date,
CASE WHEN q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0 THEN 'A' WHEN q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm>0 AND q.equity>0 THEN 'D' END signal,
(SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date ORDER BY s.d DESC LIMIT 1) shares_asof,
(SELECT p.px_close FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,
(SELECT p.rn FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_rn,
(SELECT p.px_open FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_price,
(SELECT MIN(f2.filing_date) FROM filings f2 WHERE f2.symbol=q.symbol AND f2.filing_date>f.filing_date) next_filing_date
FROM qp q JOIN filings f USING(symbol,report_date)
WHERE q.ebit>0 AND q.ebit_yoy<=0 AND q.equity>0 AND q.ni_ttm<>0), e AS (SELECT *,shares_asof*signal_close market_cap FROM c WHERE signal IS NOT NULL AND shares_asof IS NOT NULL AND signal_close IS NOT NULL AND entry_rn IS NOT NULL AND entry_price>0 AND shares_asof*signal_close BETWEEN 10000000 AND 300000000)
SELECT e.*,CASE WHEN market_cap>0 THEN fcf_yoy_change/market_cap END fcf_improve_to_mcap,
p20.px_close/e.entry_price-1 r20d,p60.px_close/e.entry_price-1 r60d,p120.px_close/e.entry_price-1 r120d,
(SELECT p.px_close/e.entry_price-1 FROM prices p WHERE p.symbol=e.symbol AND p.d<e.next_filing_date ORDER BY p.d DESC LIMIT 1) r_next_filing
FROM e LEFT JOIN prices p20 ON p20.symbol=e.symbol AND p20.rn=e.entry_rn+20 LEFT JOIN prices p60 ON p60.symbol=e.symbol AND p60.rn=e.entry_rn+60 LEFT JOIN prices p120 ON p120.symbol=e.symbol AND p120.rn=e.entry_rn+120""")
con.execute(f"COPY events0 TO '{OUT/'events_both.csv'}' (HEADER,DELIMITER ',')")
filters=[('base','TRUE'),('mcap80','market_cap>=80000000'),('fcf1','fcf_improve_to_mcap>0.01'),('fcf1_mcap80','fcf_improve_to_mcap>0.01 AND market_cap>=80000000')]
horizons=['r20d','r60d','r120d','r_next_filing']
rows=[]
for fname,cond in filters:
  for yr,yrcond in [('all','TRUE'),('2024_2025',"EXTRACT(year FROM report_date) IN (2024,2025)"),('2024',"EXTRACT(year FROM report_date)=2024"),('2025',"EXTRACT(year FROM report_date)=2025")]:
    for sig in ['A','D']:
      for h in horizons:
        q=f"SELECT COUNT({h}),MEDIAN({h}),AVG({h}),AVG(CASE WHEN {h}>0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE {h} IS NOT NULL),AVG(CASE WHEN {h}>0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE {h} IS NOT NULL),AVG(CASE WHEN {h}<-0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE {h} IS NOT NULL) FROM events0 WHERE signal='{sig}' AND {cond} AND {yrcond}"
        vals=con.execute(q).fetchone(); rows.append((fname,yr,sig,h)+vals)
with open(OUT/'summary.csv','w',newline='') as f:
  w=csv.writer(f);w.writerow(['filter','period','signal','horizon','n','median','mean','win_rate','tail_up20','tail_down20']);w.writerows(rows)
# Same-filter A vs D rank test using DuckDB ranks/correlation-free MW approximated externally later; save raw filtered rows.
for fname,cond in filters:
  con.execute(f"COPY (SELECT * FROM events0 WHERE {cond}) TO '{OUT/f'events_{fname}.csv'}' (HEADER,DELIMITER ',')")
print('SUMMARY')
for r in rows:
  if r[0]=='fcf1_mcap80' and r[1] in ('all','2024_2025'): print(r)
