import duckdb
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
files={
 'statements':BASE+'stock_statement.parquet',
 'prices':BASE+'stock_prices.parquet',
 'shares':BASE+'stock_shares_outstanding.parquet',
 'filings':BASE+'stock_sec_filing.parquet',
}
con=duckdb.connect(); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
print('GLOBAL COVERAGE')
print('statements', con.execute(f"SELECT MIN(TRY_CAST(report_date AS DATE)),MAX(TRY_CAST(report_date AS DATE)),COUNT(*) FROM read_parquet('{files['statements']}') WHERE report_date<>'TTM'").fetchone())
print('quarterly statements', con.execute(f"SELECT MIN(TRY_CAST(report_date AS DATE)),MAX(TRY_CAST(report_date AS DATE)),COUNT(*) FROM read_parquet('{files['statements']}') WHERE report_date<>'TTM' AND period_type='quarterly'").fetchone())
print('prices', con.execute(f"SELECT MIN(TRY_CAST(report_date AS DATE)),MAX(TRY_CAST(report_date AS DATE)),COUNT(*) FROM read_parquet('{files['prices']}')").fetchone())
print('shares', con.execute(f"SELECT MIN(TRY_CAST(report_date AS DATE)),MAX(TRY_CAST(report_date AS DATE)),COUNT(*) FROM read_parquet('{files['shares']}')").fetchone())
print('filings', con.execute(f"SELECT MIN(TRY_CAST(filing_date AS DATE)),MAX(TRY_CAST(filing_date AS DATE)),COUNT(*) FROM read_parquet('{files['filings']}')").fetchone())
print('\nREQUIRED ITEM COVERAGE')
for item,ft in [('ebit','income_statement'),('net_income','income_statement'),('stockholders_equity','balance_sheet'),('free_cash_flow','cash_flow')]:
    r=con.execute(f"SELECT MIN(TRY_CAST(report_date AS DATE)),MAX(TRY_CAST(report_date AS DATE)),COUNT(*),COUNT(DISTINCT symbol) FROM read_parquet('{files['statements']}') WHERE report_date<>'TTM' AND period_type='quarterly' AND item_name=? AND finance_type=?",[item,ft]).fetchone()
    print(item,r)
print('\nYEARLY REQUIRED-ITEM COUNTS')
q=f"""WITH s AS (
SELECT symbol,TRY_CAST(report_date AS DATE) d,
MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN 1 ELSE 0 END) has_ebit,
MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN 1 ELSE 0 END) has_ni,
MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN 1 ELSE 0 END) has_eq,
MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN 1 ELSE 0 END) has_fcf
FROM read_parquet('{files['statements']}')
WHERE report_date<>'TTM' AND period_type='quarterly' AND item_name IN ('ebit','net_income','stockholders_equity','free_cash_flow')
GROUP BY 1,2)
SELECT EXTRACT(year FROM d)::INT y,COUNT(*) quarters,COUNT(DISTINCT symbol) symbols,
SUM(CASE WHEN has_ebit=1 AND has_ni=1 AND has_eq=1 AND has_fcf=1 THEN 1 ELSE 0 END) complete_quarters
FROM s GROUP BY 1 ORDER BY 1"""
for r in con.execute(q).fetchall(): print(r)
print('\nFILING YEAR COUNTS')
for r in con.execute(f"SELECT EXTRACT(year FROM TRY_CAST(filing_date AS DATE))::INT y,COUNT(*),COUNT(DISTINCT symbol) FROM read_parquet('{files['filings']}') WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(filing_date AS DATE) IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall(): print(r)
