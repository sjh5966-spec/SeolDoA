from pathlib import Path
import csv, math
import duckdb
from scipy.stats import fisher_exact, mannwhitneyu
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'; P=BASE+'stock_prices.parquet'; SH=BASE+'stock_shares_outstanding.parquet'; F=BASE+'stock_sec_filing.parquet'
OUT=Path('holdout_results'); OUT.mkdir(exist_ok=True)
con=duckdb.connect('holdout.duckdb'); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
con.execute(f"""CREATE TABLE q AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE ebit,
MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE net_income,
MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE equity,
MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN item_value END)::DOUBLE fcf
FROM read_parquet('{S}') WHERE period_type='quarterly' AND report_date<>'TTM' AND item_name IN ('ebit','net_income','stockholders_equity','free_cash_flow') AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2022-01-01' AND DATE '2025-12-31' GROUP BY 1,2""")
con.execute("""CREATE TABLE qp AS WITH w AS (SELECT *,LAG(report_date,4) OVER(PARTITION BY symbol ORDER BY report_date) d4,LAG(ebit,4) OVER(PARTITION BY symbol ORDER BY report_date) ebit_yoy,LAG(fcf,4) OVER(PARTITION BY symbol ORDER BY report_date) fcf_yoy,SUM(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni_ttm,COUNT(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni4 FROM q) SELECT *,fcf-fcf_yoy fcf_yoy_change,ebit-ebit_yoy ebit_yoy_change FROM w WHERE ni4=4 AND d4 IS NOT NULL""")
con.execute(f"""CREATE TABLE filings AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,MIN(TRY_CAST(filing_date AS DATE)) filing_date FROM read_parquet('{F}') WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(report_date AS DATE) IS NOT NULL AND TRY_CAST(filing_date AS DATE) IS NOT NULL GROUP BY 1,2""")
con.execute(f"""CREATE TABLE prices AS SELECT symbol,TRY_CAST(report_date AS DATE) d,open::DOUBLE px_open,close::DOUBLE px_close,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2023-01-01' AND DATE '2026-03-31' AND open IS NOT NULL AND close IS NOT NULL""")
con.execute(f"""CREATE TABLE shares AS SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding FROM read_parquet('{SH}') WHERE TRY_CAST(report_date AS DATE) IS NOT NULL AND shares_outstanding>0""")
con.execute("""CREATE TABLE events AS WITH c AS (SELECT q.*,f.filing_date,(SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date ORDER BY s.d DESC LIMIT 1) shares_now,(SELECT p.px_close FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,(SELECT p.rn FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_rn,(SELECT p.px_open FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_price FROM qp q JOIN filings f USING(symbol,report_date) WHERE q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0),e AS (SELECT *,shares_now*signal_close market_cap FROM c WHERE shares_now IS NOT NULL AND signal_close IS NOT NULL AND entry_rn IS NOT NULL AND entry_price>0 AND shares_now*signal_close BETWEEN 10000000 AND 300000000),x AS (SELECT *,CASE WHEN market_cap>0 THEN fcf_yoy_change/market_cap END fcf_to_mcap,CASE WHEN market_cap>0 THEN ebit_yoy_change/market_cap END ebit_to_mcap,CASE WHEN market_cap>0 THEN -ni_ttm/market_cap END ni_loss_to_mcap,(SELECT p.px_close/entry_price-1 FROM prices p WHERE p.symbol=e.symbol AND p.rn=e.entry_rn+20 LIMIT 1) r20d FROM e) SELECT * FROM x WHERE EXTRACT(year FROM report_date) IN (2024,2025) AND fcf_to_mcap IS NOT NULL AND ebit_to_mcap IS NOT NULL AND ni_loss_to_mcap IS NOT NULL AND r20d IS NOT NULL""")
# Build empirical CDFs using 2024 only. Apply those fixed cutpoints to 2025.
train=con.execute("SELECT fcf_to_mcap,ebit_to_mcap,ni_loss_to_mcap FROM events WHERE EXTRACT(year FROM report_date)=2024 ORDER BY 1").fetchall()
fcf_train=sorted([r[0] for r in train]); ebit_train=sorted([r[1] for r in train]); ni_train=sorted([r[2] for r in train])
def pct(v, arr):
    import bisect
    return bisect.bisect_right(arr,v)/len(arr) if arr else None
rows=con.execute("SELECT symbol,report_date,market_cap,fcf_to_mcap,ebit_to_mcap,ni_loss_to_mcap,r20d FROM events ORDER BY report_date,symbol").fetchall()
out=[]
for r in rows:
    symbol,report_date,mcap,fcf,ebit,ni,r20=r
    pf,pe,pn=pct(fcf,fcf_train),pct(ebit,ebit_train),pct(ni,ni_train)
    score=(pf+pe+pn)/3
    out.append((symbol,report_date,mcap,fcf,ebit,ni,r20,pf,pe,pn,score))
con.execute("CREATE TABLE scored(symbol VARCHAR, report_date DATE, market_cap DOUBLE, fcf_to_mcap DOUBLE, ebit_to_mcap DOUBLE, ni_loss_to_mcap DOUBLE, r20d DOUBLE, fcf_pct DOUBLE, ebit_pct DOUBLE, ni_pct DOUBLE, shock_score DOUBLE)")
con.executemany("INSERT INTO scored VALUES (?,?,?,?,?,?,?,?,?,?,?)",out)
con.execute(f"COPY scored TO '{OUT/'scored_events.csv'}' (HEADER,DELIMITER ',')")
# Pre-specified score buckets: top 25%, top 20%, top 10% based on fixed [0,1] score scale.
summary=[]
for y in (2024,2025):
  for label,cond in [('all','TRUE'),('top25','shock_score>=0.75'),('top20','shock_score>=0.80'),('top10','shock_score>=0.90')]:
    r=con.execute(f"SELECT COUNT(*),MEDIAN(r20d),AVG(r20d),AVG(CASE WHEN r20d>0.2 THEN 1.0 ELSE 0.0 END),AVG(CASE WHEN r20d>0.5 THEN 1.0 ELSE 0.0 END),AVG(CASE WHEN r20d>1.0 THEN 1.0 ELSE 0.0 END),AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FROM scored WHERE EXTRACT(year FROM report_date)={y} AND {cond}").fetchone()
    summary.append((y,label)+r)
with open(OUT/'bucket_summary.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['year','bucket','n','median_r20','mean_r20','up20','up50','up100','down20']); w.writerows(summary)
# Strict holdout tests for 2025: top25 vs rest and top20 vs rest.
tests=[]
for label,thr in [('top25',0.75),('top20',0.80),('top10',0.90)]:
    a=[r[0] for r in con.execute(f"SELECT r20d FROM scored WHERE EXTRACT(year FROM report_date)=2025 AND shock_score>={thr}").fetchall()]
    b=[r[0] for r in con.execute(f"SELECT r20d FROM scored WHERE EXTRACT(year FROM report_date)=2025 AND shock_score<{thr}").fetchall()]
    mw=mannwhitneyu(a,b,alternative='greater').pvalue if a and b else None
    a50=sum(x>0.5 for x in a); b50=sum(x>0.5 for x in b)
    a100=sum(x>1.0 for x in a); b100=sum(x>1.0 for x in b)
    f50=fisher_exact([[a50,len(a)-a50],[b50,len(b)-b50]],alternative='greater').pvalue if a and b else None
    f100=fisher_exact([[a100,len(a)-a100],[b100,len(b)-b100]],alternative='greater').pvalue if a and b else None
    tests.append((label,len(a),len(b),mw,a50/len(a) if a else None,b50/len(b) if b else None,f50,a100/len(a) if a else None,b100/len(b) if b else None,f100))
with open(OUT/'holdout_tests.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['bucket','n_top','n_rest','mw_one_sided_p','up50_top','up50_rest','fisher_up50_p','up100_top','up100_rest','fisher_up100_p']); w.writerows(tests)
# Deciles on continuous score in 2025 for monotonicity.
dec=con.execute("""WITH z AS (SELECT *,NTILE(10) OVER(ORDER BY shock_score) decile FROM scored WHERE EXTRACT(year FROM report_date)=2025) SELECT decile,COUNT(*),MIN(shock_score),MAX(shock_score),MEDIAN(r20d),AVG(r20d),AVG(CASE WHEN r20d>0.5 THEN 1.0 ELSE 0.0 END),AVG(CASE WHEN r20d>1.0 THEN 1.0 ELSE 0.0 END),AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FROM z GROUP BY 1 ORDER BY 1""").fetchall()
with open(OUT/'holdout_deciles.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['decile','n','score_min','score_max','median_r20','mean_r20','up50','up100','down20']); w.writerows(dec)
print('SUMMARY'); [print(r) for r in summary]
print('HOLDOUT TESTS'); [print(r) for r in tests]
print('2025 DECILES'); [print(r) for r in dec]
