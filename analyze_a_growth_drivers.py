from pathlib import Path
import json
import duckdb

BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'; P=BASE+'stock_prices.parquet'; SH=BASE+'stock_shares_outstanding.parquet'; F=BASE+'stock_sec_filing.parquet'
OUT=Path('growth_results'); OUT.mkdir(exist_ok=True)
con=duckdb.connect('growth.duckdb'); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
con.execute(f"""
CREATE OR REPLACE TABLE q AS
SELECT symbol, TRY_CAST(report_date AS DATE) report_date,
 MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE ebit,
 MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE net_income,
 MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE equity,
 MAX(CASE WHEN item_name='total_revenue' AND finance_type='income_statement' THEN item_value END)::DOUBLE revenue,
 MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN item_value END)::DOUBLE fcf,
 MAX(CASE WHEN item_name='cash_and_cash_equivalents' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE cash,
 MAX(CASE WHEN item_name='total_debt' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE debt,
 MAX(CASE WHEN item_name='interest_expense' AND finance_type='income_statement' THEN item_value END)::DOUBLE interest_expense
FROM read_parquet('{S}')
WHERE period_type='quarterly' AND report_date<>'TTM'
 AND item_name IN ('ebit','net_income','stockholders_equity','total_revenue','free_cash_flow','cash_and_cash_equivalents','total_debt','interest_expense')
 AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2022-01-01' AND DATE '2026-08-26'
GROUP BY 1,2
""")
con.execute("""
CREATE OR REPLACE TABLE qp AS
WITH w AS (
 SELECT *, LAG(report_date,4) OVER(PARTITION BY symbol ORDER BY report_date) d4,
  LAG(ebit,4) OVER(PARTITION BY symbol ORDER BY report_date) ebit_yoy,
  LAG(revenue,4) OVER(PARTITION BY symbol ORDER BY report_date) revenue_yoy_base,
  LAG(revenue,5) OVER(PARTITION BY symbol ORDER BY report_date) revenue_yoy_base_prev,
  LAG(revenue,1) OVER(PARTITION BY symbol ORDER BY report_date) revenue_prev,
  LAG(fcf,4) OVER(PARTITION BY symbol ORDER BY report_date) fcf_yoy,
  LAG(fcf,1) OVER(PARTITION BY symbol ORDER BY report_date) fcf_prev,
  LAG(cash,4) OVER(PARTITION BY symbol ORDER BY report_date) cash_yoy,
  LAG(debt,4) OVER(PARTITION BY symbol ORDER BY report_date) debt_yoy,
  LAG(interest_expense,4) OVER(PARTITION BY symbol ORDER BY report_date) interest_yoy,
  SUM(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni_ttm,
  COUNT(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni4
 FROM q
), x AS (
 SELECT *,
  CASE WHEN revenue_yoy_base IS NOT NULL AND revenue_yoy_base<>0 THEN revenue/revenue_yoy_base-1 END rev_yoy,
  CASE WHEN revenue_yoy_base_prev IS NOT NULL AND revenue_yoy_base_prev<>0 AND revenue_prev IS NOT NULL THEN revenue_prev/revenue_yoy_base_prev-1 END rev_yoy_prev,
  CASE WHEN revenue IS NOT NULL AND revenue<>0 THEN ebit/revenue END ebit_margin,
  CASE WHEN revenue IS NOT NULL AND revenue<>0 AND revenue_yoy_base IS NOT NULL AND revenue_yoy_base<>0 THEN (ebit/revenue)-(ebit_yoy/revenue_yoy_base) END ebit_margin_yoy_change,
  CASE WHEN equity IS NOT NULL AND equity<>0 THEN (ebit-ebit_yoy)/ABS(equity) END ebit_improve_to_equity,
  CASE WHEN revenue IS NOT NULL AND revenue<>0 THEN (ebit-ebit_yoy)/ABS(revenue) END ebit_improve_to_revenue,
  cash-debt net_cash,
  CASE WHEN debt IS NOT NULL AND debt<>0 THEN cash/debt END cash_to_debt,
  CASE WHEN interest_expense IS NOT NULL AND interest_expense<>0 THEN ebit/ABS(interest_expense) END interest_coverage
 FROM w WHERE ni4=4 AND d4 IS NOT NULL
)
SELECT *, rev_yoy-rev_yoy_prev rev_accel, fcf-fcf_yoy fcf_yoy_change, fcf-fcf_prev fcf_qoq_change,
 cash-cash_yoy cash_yoy_change, debt-debt_yoy debt_yoy_change, interest_expense-interest_yoy interest_yoy_change
FROM x
""")
con.execute(f"""
CREATE OR REPLACE TABLE filings AS
SELECT symbol,TRY_CAST(report_date AS DATE) report_date,MIN(TRY_CAST(filing_date AS DATE)) filing_date
FROM read_parquet('{F}') WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(report_date AS DATE) IS NOT NULL AND TRY_CAST(filing_date AS DATE) IS NOT NULL GROUP BY 1,2
""")
con.execute(f"""
CREATE OR REPLACE TABLE prices AS
SELECT symbol,TRY_CAST(report_date AS DATE) d,open::DOUBLE px_open,close::DOUBLE px_close,
 ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn
FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2021-01-01' AND DATE '2026-08-26' AND open IS NOT NULL AND close IS NOT NULL
""")
con.execute(f"""
CREATE OR REPLACE TABLE shares AS
SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding FROM read_parquet('{SH}') WHERE TRY_CAST(report_date AS DATE) IS NOT NULL AND shares_outstanding>0
""")
con.execute("""
CREATE OR REPLACE TABLE a_events AS
WITH c AS (
 SELECT q.*,f.filing_date,
  (SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date ORDER BY s.d DESC LIMIT 1) shares_asof,
  (SELECT p.px_close FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,
  (SELECT p.rn FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_rn,
  (SELECT p.d FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_date,
  (SELECT p.px_open FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_price
 FROM qp q JOIN filings f USING(symbol,report_date)
 WHERE q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0
), e AS (
 SELECT *,shares_asof*signal_close market_cap FROM c
 WHERE shares_asof IS NOT NULL AND signal_close IS NOT NULL AND entry_rn IS NOT NULL AND entry_price>0 AND shares_asof*signal_close BETWEEN 10000000 AND 300000000
)
SELECT e.*,p60.px_close/e.entry_price-1 r60d FROM e LEFT JOIN prices p60 ON p60.symbol=e.symbol AND p60.rn=e.entry_rn+60
""")
features=['rev_yoy','rev_accel','ebit_margin','ebit_margin_yoy_change','ebit_improve_to_equity','ebit_improve_to_revenue','fcf','fcf_yoy_change','fcf_qoq_change','net_cash','cash_to_debt','cash_yoy_change','debt_yoy_change','interest_coverage','interest_yoy_change','market_cap']
parts=[]
for feat in features:
    parts.append(f"""WITH z AS (SELECT '{feat}' feature,{feat} feat_value,r60d,NTILE(4) OVER(ORDER BY {feat}) quartile FROM a_events WHERE {feat} IS NOT NULL AND isfinite({feat}) AND r60d IS NOT NULL)
    SELECT feature,quartile,COUNT(*) n,MIN(feat_value) min_value,MAX(feat_value) max_value,MEDIAN(feat_value) median_feature,MEDIAN(r60d) median_r60d,AVG(r60d) mean_r60d,AVG(CASE WHEN r60d>0 THEN 1.0 ELSE 0.0 END) win_rate FROM z GROUP BY 1,2""")
summary_sql=' UNION ALL '.join(parts)
con.execute(f"COPY ({summary_sql}) TO '{OUT/'feature_quartiles.csv'}' (HEADER,DELIMITER ',')")
corr_rows=[]
for feat in features:
    q=f"""WITH z AS (SELECT {feat} x,r60d y FROM a_events WHERE {feat} IS NOT NULL AND isfinite({feat}) AND r60d IS NOT NULL), r AS (SELECT RANK() OVER(ORDER BY x)::DOUBLE rx,RANK() OVER(ORDER BY y)::DOUBLE ry FROM z) SELECT COUNT(*),CORR(rx,ry) FROM r"""
    n,rho=con.execute(q).fetchone(); corr_rows.append((feat,n,rho))
con.execute("CREATE OR REPLACE TABLE corr(feature VARCHAR,n BIGINT,spearman_rho DOUBLE)"); con.executemany("INSERT INTO corr VALUES (?,?,?)",corr_rows)
con.execute(f"COPY corr TO '{OUT/'feature_correlations.csv'}' (HEADER,DELIMITER ',')")
con.execute("""
CREATE OR REPLACE TABLE combos AS
SELECT CASE WHEN rev_accel>0 THEN 1 ELSE 0 END rev_accel_pos, CASE WHEN ebit_margin_yoy_change>0 THEN 1 ELSE 0 END margin_expand,
 CASE WHEN fcf_yoy_change>0 THEN 1 ELSE 0 END fcf_improve, CASE WHEN net_cash>0 THEN 1 ELSE 0 END net_cash_pos,
 COUNT(*) n,COUNT(r60d) n_r60,MEDIAN(r60d) median_r60d,AVG(r60d) mean_r60d,
 AVG(CASE WHEN r60d>0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r60d IS NOT NULL) win_rate
FROM a_events WHERE rev_accel IS NOT NULL AND ebit_margin_yoy_change IS NOT NULL AND fcf_yoy_change IS NOT NULL AND net_cash IS NOT NULL GROUP BY 1,2,3,4
""")
con.execute(f"COPY combos TO '{OUT/'predefined_combos.csv'}' (HEADER,DELIMITER ',')"); con.execute(f"COPY a_events TO '{OUT/'a_events_enriched.csv'}' (HEADER,DELIMITER ',')")
meta={'n_a':con.execute('SELECT COUNT(*) FROM a_events').fetchone()[0],'n_r60':con.execute('SELECT COUNT(r60d) FROM a_events').fetchone()[0],'features':features}
with open(OUT/'meta.json','w') as f: json.dump(meta,f,indent=2)
print('META',meta); print('CORR'); [print(r) for r in corr_rows]; print('TOP COMBOS'); [print(r) for r in con.execute('SELECT * FROM combos WHERE n_r60>=10 ORDER BY median_r60d DESC LIMIT 12').fetchall()]
