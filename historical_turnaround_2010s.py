from pathlib import Path
import csv, json
import duckdb
OUT=Path('historical_results'); OUT.mkdir(exist_ok=True)
con=duckdb.connect('historical.duckdb')
con.execute("INSTALL httpfs; LOAD httpfs")
con.execute("SET s3_region='us-east-1'"); con.execute("SET s3_url_style='path'"); con.execute("SET s3_endpoint='s3.amazonaws.com'")
con.execute("SET threads=4"); con.execute("SET memory_limit='7GB'")
DP='s3://dataset.secdatabase.com/sec_financial_statements/parquet/20200930/data_point/*'
SUB='s3://dataset.secdatabase.com/sec_financial_statements/parquet/20200930/company_submission/*'
HF='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
P=HF+'stock_prices.parquet'; SH=HF+'stock_shares_outstanding.parquet'; HF_F=HF+'stock_sec_filing.parquet'
con.execute(f"""CREATE TABLE subs AS SELECT * EXCLUDE(rn) FROM (
 SELECT cik,accession_number_int,company_name,filing_date,document_type,document_period_end_date report_date,
 document_fiscal_year_focus fiscal_year,document_fiscal_period_focus fiscal_period,
 ROW_NUMBER() OVER(PARTITION BY cik,document_type,document_period_end_date ORDER BY filing_date,accession_number_int) rn
 FROM read_parquet('{SUB}') WHERE document_type IN ('10-Q','10-K') AND COALESCE(amendment_flag,false)=false
 AND filing_date BETWEEN DATE '2009-01-01' AND DATE '2020-09-30' AND document_period_end_date IS NOT NULL) WHERE rn=1""")
# Conservative standardized fallbacks only. We avoid company-specific extension tags.
tags=[
'OperatingIncomeLoss','NetIncomeLoss','StockholdersEquity','StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
'NetCashProvidedByUsedInOperatingActivities','NetCashProvidedByUsedInOperatingActivitiesContinuingOperations',
'PaymentsToAcquirePropertyPlantAndEquipment','PaymentsToAcquireOtherPropertyPlantAndEquipment','PaymentsToAcquirePropertyAndEquipment',
'PaymentsToAcquirePropertyPlantEquipmentAndSoftware','PaymentsToAcquirePropertyEquipmentAndSoftware',
'PaymentsForAdditionsToPropertyPlantAndEquipment','PaymentsToAcquireProductiveAssets']
taglist=','.join("'"+x+"'" for x in tags)
con.execute(f"""CREATE TABLE facts AS SELECT cik,accession_number_int,filing_date,datapoint_name,start_date,end_date,period_month,numeric_value,unit
FROM read_parquet('{DP}') WHERE datapoint_name IN ({taglist}) AND segment_hash IS NULL AND unit='USD'
AND filing_date BETWEEN DATE '2009-01-01' AND DATE '2020-09-30'""")
# Build one row per Q filing. Prefer primary tags, then standardized fallbacks.
con.execute("""CREATE TABLE q10 AS
SELECT s.cik,s.accession_number_int,s.company_name,s.filing_date,s.report_date,s.fiscal_year,s.fiscal_period,
 COALESCE(
  arg_min(f.numeric_value,ABS(COALESCE(f.period_month,999)-3)) FILTER(WHERE f.datapoint_name='OperatingIncomeLoss' AND f.end_date=s.report_date AND f.period_month BETWEEN 2 AND 4)
 ) ebit_q,
 COALESCE(
  arg_min(f.numeric_value,ABS(COALESCE(f.period_month,999)-3)) FILTER(WHERE f.datapoint_name='NetIncomeLoss' AND f.end_date=s.report_date AND f.period_month BETWEEN 2 AND 4)
 ) ni_q,
 arg_min(f.numeric_value,ABS(COALESCE(f.period_month,999)-(CASE s.fiscal_period WHEN 'Q1' THEN 3 WHEN 'Q2' THEN 6 WHEN 'Q3' THEN 9 END))) FILTER(WHERE f.datapoint_name='NetIncomeLoss' AND f.end_date=s.report_date AND f.period_month BETWEEN (CASE s.fiscal_period WHEN 'Q1' THEN 2 WHEN 'Q2' THEN 5 WHEN 'Q3' THEN 8 END) AND (CASE s.fiscal_period WHEN 'Q1' THEN 4 WHEN 'Q2' THEN 7 WHEN 'Q3' THEN 10 END)) ni_ytd,
 COALESCE(
  arg_min(f.numeric_value,ABS(COALESCE(f.period_month,999)-(CASE s.fiscal_period WHEN 'Q1' THEN 3 WHEN 'Q2' THEN 6 WHEN 'Q3' THEN 9 END))) FILTER(WHERE f.datapoint_name='NetCashProvidedByUsedInOperatingActivities' AND f.end_date=s.report_date AND f.period_month BETWEEN (CASE s.fiscal_period WHEN 'Q1' THEN 2 WHEN 'Q2' THEN 5 WHEN 'Q3' THEN 8 END) AND (CASE s.fiscal_period WHEN 'Q1' THEN 4 WHEN 'Q2' THEN 7 WHEN 'Q3' THEN 10 END)),
  arg_min(f.numeric_value,ABS(COALESCE(f.period_month,999)-(CASE s.fiscal_period WHEN 'Q1' THEN 3 WHEN 'Q2' THEN 6 WHEN 'Q3' THEN 9 END))) FILTER(WHERE f.datapoint_name='NetCashProvidedByUsedInOperatingActivitiesContinuingOperations' AND f.end_date=s.report_date AND f.period_month BETWEEN (CASE s.fiscal_period WHEN 'Q1' THEN 2 WHEN 'Q2' THEN 5 WHEN 'Q3' THEN 8 END) AND (CASE s.fiscal_period WHEN 'Q1' THEN 4 WHEN 'Q2' THEN 7 WHEN 'Q3' THEN 10 END))
 ) cfo_ytd,
 COALESCE(
  arg_min(ABS(f.numeric_value),ABS(COALESCE(f.period_month,999)-(CASE s.fiscal_period WHEN 'Q1' THEN 3 WHEN 'Q2' THEN 6 WHEN 'Q3' THEN 9 END))) FILTER(WHERE f.datapoint_name='PaymentsToAcquirePropertyPlantAndEquipment' AND f.end_date=s.report_date AND f.period_month BETWEEN (CASE s.fiscal_period WHEN 'Q1' THEN 2 WHEN 'Q2' THEN 5 WHEN 'Q3' THEN 8 END) AND (CASE s.fiscal_period WHEN 'Q1' THEN 4 WHEN 'Q2' THEN 7 WHEN 'Q3' THEN 10 END)),
  arg_min(ABS(f.numeric_value),ABS(COALESCE(f.period_month,999)-(CASE s.fiscal_period WHEN 'Q1' THEN 3 WHEN 'Q2' THEN 6 WHEN 'Q3' THEN 9 END))) FILTER(WHERE f.datapoint_name IN ('PaymentsToAcquireOtherPropertyPlantAndEquipment','PaymentsToAcquirePropertyAndEquipment','PaymentsToAcquirePropertyPlantEquipmentAndSoftware','PaymentsToAcquirePropertyEquipmentAndSoftware','PaymentsForAdditionsToPropertyPlantAndEquipment','PaymentsToAcquireProductiveAssets') AND f.end_date=s.report_date AND f.period_month BETWEEN (CASE s.fiscal_period WHEN 'Q1' THEN 2 WHEN 'Q2' THEN 5 WHEN 'Q3' THEN 8 END) AND (CASE s.fiscal_period WHEN 'Q1' THEN 4 WHEN 'Q2' THEN 7 WHEN 'Q3' THEN 10 END))
 ) capex_ytd,
 COALESCE(
  max(f.numeric_value) FILTER(WHERE f.datapoint_name='StockholdersEquity' AND f.end_date=s.report_date AND f.start_date IS NULL),
  max(f.numeric_value) FILTER(WHERE f.datapoint_name='StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest' AND f.end_date=s.report_date AND f.start_date IS NULL)
 ) equity
FROM subs s LEFT JOIN facts f USING(cik,accession_number_int)
WHERE s.document_type='10-Q' AND s.fiscal_period IN ('Q1','Q2','Q3') AND s.fiscal_year IS NOT NULL GROUP BY ALL""")
con.execute("""CREATE TABLE annual_ni AS SELECT s.cik,s.fiscal_year,s.filing_date,s.report_date,
 arg_min(f.numeric_value,ABS(COALESCE(f.period_month,999)-12)) FILTER(WHERE f.datapoint_name='NetIncomeLoss' AND f.end_date=s.report_date AND f.period_month BETWEEN 11 AND 13) ni_annual
FROM subs s LEFT JOIN facts f USING(cik,accession_number_int) WHERE s.document_type='10-K' AND s.fiscal_year IS NOT NULL GROUP BY ALL""")
con.execute("""CREATE TABLE qpanel AS WITH z AS (
 SELECT q.*,LAG(cfo_ytd) OVER(PARTITION BY cik,fiscal_year ORDER BY CASE fiscal_period WHEN 'Q1' THEN 1 WHEN 'Q2' THEN 2 WHEN 'Q3' THEN 3 END) prev_cfo_ytd,
 LAG(capex_ytd) OVER(PARTITION BY cik,fiscal_year ORDER BY CASE fiscal_period WHEN 'Q1' THEN 1 WHEN 'Q2' THEN 2 WHEN 'Q3' THEN 3 END) prev_capex_ytd FROM q10 q),x AS (
 SELECT *,CASE WHEN fiscal_period='Q1' THEN cfo_ytd-capex_ytd WHEN prev_cfo_ytd IS NOT NULL AND prev_capex_ytd IS NOT NULL THEN (cfo_ytd-prev_cfo_ytd)-(capex_ytd-prev_capex_ytd) END fcf_q FROM z)
SELECT x.*,py.ebit_q ebit_yoy,py.fcf_q fcf_yoy,py.ni_ytd ni_ytd_yoy,a.ni_annual prev_annual_ni,
 CASE WHEN a.ni_annual IS NOT NULL AND x.ni_ytd IS NOT NULL AND py.ni_ytd IS NOT NULL THEN a.ni_annual+x.ni_ytd-py.ni_ytd END ni_ttm
FROM x LEFT JOIN x py ON py.cik=x.cik AND py.fiscal_year=x.fiscal_year-1 AND py.fiscal_period=x.fiscal_period
LEFT JOIN annual_ni a ON a.cik=x.cik AND a.fiscal_year=x.fiscal_year-1 AND a.filing_date<x.filing_date
QUALIFY ROW_NUMBER() OVER(PARTITION BY x.cik,x.fiscal_year,x.fiscal_period ORDER BY a.filing_date DESC NULLS LAST)=1""")
con.execute(f"""CREATE TABLE hff AS SELECT TRY_CAST(cik AS BIGINT) cik,symbol,TRY_CAST(filing_date AS DATE) filing_date FROM read_parquet('{HF_F}') WHERE TRY_CAST(cik AS BIGINT) IS NOT NULL AND symbol IS NOT NULL AND TRY_CAST(filing_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2021-12-31'""")
con.execute(f"""CREATE TABLE prices AS SELECT symbol,TRY_CAST(report_date AS DATE) d,open::DOUBLE px_open,close::DOUBLE px_close,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2021-12-31' AND open IS NOT NULL AND close IS NOT NULL""")
con.execute(f"""CREATE TABLE shares AS SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding FROM read_parquet('{SH}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2021-12-31' AND shares_outstanding>0""")
con.execute("""CREATE TABLE events0 AS WITH e AS (
 SELECT q.*,(SELECT h.symbol FROM hff h WHERE h.cik=q.cik ORDER BY ABS(DATE_DIFF('day',h.filing_date,q.filing_date)) ASC LIMIT 1) symbol FROM qpanel q
 WHERE q.ebit_q>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0 AND q.fcf_q IS NOT NULL AND q.fcf_yoy IS NOT NULL),m AS (
 SELECT e.*,(SELECT s.shares_outstanding FROM shares s WHERE s.symbol=e.symbol AND s.d<=e.report_date ORDER BY s.d DESC LIMIT 1) shares_asof,
 (SELECT p.px_close FROM prices p WHERE p.symbol=e.symbol AND p.d<=e.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,
 (SELECT p.rn FROM prices p WHERE p.symbol=e.symbol AND p.d>e.filing_date ORDER BY p.d ASC LIMIT 1) entry_rn,
 (SELECT p.px_open FROM prices p WHERE p.symbol=e.symbol AND p.d>e.filing_date ORDER BY p.d ASC LIMIT 1) entry_price FROM e),v AS (
 SELECT *,shares_asof*signal_close market_cap FROM m WHERE symbol IS NOT NULL AND shares_asof IS NOT NULL AND signal_close IS NOT NULL AND entry_rn IS NOT NULL AND entry_price>0)
SELECT v.*,(fcf_q-fcf_yoy)/market_cap fcf_improve_to_mcap,(ebit_q-ebit_yoy)/market_cap ebit_improve_to_mcap,(-ni_ttm)/market_cap ni_loss_to_mcap,p20.px_close/v.entry_price-1 r20d
FROM v LEFT JOIN prices p20 ON p20.symbol=v.symbol AND p20.rn=v.entry_rn+20 WHERE market_cap BETWEEN 10000000 AND 300000000""")
con.execute("""CREATE TABLE events AS SELECT *,
 (CASE WHEN market_cap<80000000 THEN 1 ELSE 0 END + CASE WHEN fcf_improve_to_mcap>0.01 THEN 1 ELSE 0 END + CASE WHEN ebit_improve_to_mcap>0.05 THEN 1 ELSE 0 END + CASE WHEN ni_loss_to_mcap>0.10 THEN 1 ELSE 0 END) tail_score FROM events0""")
con.execute(f"COPY events TO '{OUT/'historical_events.csv'}' (HEADER,DELIMITER ',')")
rows=con.execute("""SELECT EXTRACT(year FROM report_date)::INT AS yr,CASE WHEN tail_score=4 THEN 'score4' ELSE 'rest' END grp,COUNT(r20d) n,MEDIAN(r20d) median_r20,AVG(r20d) mean_r20,
AVG(CASE WHEN r20d>0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) win_rate,AVG(CASE WHEN r20d>0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) up20,
AVG(CASE WHEN r20d>0.5 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) up50,AVG(CASE WHEN r20d>1.0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) up100,
AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) down20 FROM events GROUP BY 1,2 ORDER BY 1,2""").fetchall()
with open(OUT/'year_summary.csv','w',newline='') as f:
 w=csv.writer(f); w.writerow(['year','group','n','median_r20','mean_r20','win_rate','up20','up50','up100','down20']); w.writerows(rows)
agg=con.execute("""SELECT CASE WHEN tail_score=4 THEN 'score4' ELSE 'rest' END grp,COUNT(r20d),MEDIAN(r20d),AVG(r20d),AVG(CASE WHEN r20d>0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d>0.5 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d>1.0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) FROM events GROUP BY 1 ORDER BY 1""").fetchall()
with open(OUT/'aggregate_summary.csv','w',newline='') as f:
 w=csv.writer(f); w.writerow(['group','n','median_r20','mean_r20','up20','up50','up100','down20']); w.writerows(agg)
coverage=con.execute("SELECT MIN(report_date),MAX(report_date),COUNT(*),COUNT(DISTINCT symbol),COUNT(*) FILTER(WHERE tail_score=4) FROM events").fetchone()
qcov=con.execute("SELECT COUNT(*),COUNT(*) FILTER(WHERE cfo_ytd IS NOT NULL),COUNT(*) FILTER(WHERE capex_ytd IS NOT NULL),COUNT(*) FILTER(WHERE equity IS NOT NULL) FROM q10").fetchone()
meta={'coverage':[str(coverage[0]),str(coverage[1])],'events':coverage[2],'symbols':coverage[3],'score4_events':coverage[4],'q10_coverage':{'total':qcov[0],'cfo':qcov[1],'capex':qcov[2],'equity':qcov[3]},'method':'Q1-Q3; frozen thresholds; conservative standardized XBRL fallback tags only; FCF derived from YTD; TTM NI reconstructed point-in-time'}
with open(OUT/'meta.json','w') as f: json.dump(meta,f,indent=2)
print('META',meta); print('AGG'); [print(r) for r in agg]; print('YEAR'); [print(r) for r in rows]
