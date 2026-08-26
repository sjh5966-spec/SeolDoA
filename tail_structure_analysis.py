from pathlib import Path
import csv, math
import duckdb
from scipy.stats import mannwhitneyu, fisher_exact

BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'; P=BASE+'stock_prices.parquet'; SH=BASE+'stock_shares_outstanding.parquet'; F=BASE+'stock_sec_filing.parquet'
OUT=Path('tail_results'); OUT.mkdir(exist_ok=True)
con=duckdb.connect('tail.duckdb'); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")

con.execute(f"""CREATE TABLE q AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE ebit,
MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE net_income,
MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE equity,
MAX(CASE WHEN item_name='total_revenue' AND finance_type='income_statement' THEN item_value END)::DOUBLE revenue,
MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN item_value END)::DOUBLE fcf
FROM read_parquet('{S}') WHERE period_type='quarterly' AND report_date<>'TTM'
AND item_name IN ('ebit','net_income','stockholders_equity','total_revenue','free_cash_flow')
AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2022-01-01' AND DATE '2026-08-26' GROUP BY 1,2""")

con.execute("""CREATE TABLE qp AS WITH w AS (SELECT *,
LAG(report_date,4) OVER(PARTITION BY symbol ORDER BY report_date) d4,
LAG(ebit,4) OVER(PARTITION BY symbol ORDER BY report_date) ebit_yoy,
LAG(fcf,4) OVER(PARTITION BY symbol ORDER BY report_date) fcf_yoy,
SUM(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni_ttm,
COUNT(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni4
FROM q) SELECT *,fcf-fcf_yoy fcf_yoy_change,ebit-ebit_yoy ebit_yoy_change FROM w WHERE ni4=4 AND d4 IS NOT NULL""")

con.execute(f"""CREATE TABLE filings AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
MIN(TRY_CAST(filing_date AS DATE)) filing_date,ARG_MIN(company_name,TRY_CAST(filing_date AS DATE)) company_name
FROM read_parquet('{F}') WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(report_date AS DATE) IS NOT NULL AND TRY_CAST(filing_date AS DATE) IS NOT NULL GROUP BY 1,2""")

con.execute(f"""CREATE TABLE prices AS SELECT symbol,TRY_CAST(report_date AS DATE) d,
open::DOUBLE px_open,close::DOUBLE px_close,volume::DOUBLE volume,
ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn
FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2021-01-01' AND DATE '2026-08-26' AND open IS NOT NULL AND close IS NOT NULL""")

con.execute(f"""CREATE TABLE shares AS SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding
FROM read_parquet('{SH}') WHERE TRY_CAST(report_date AS DATE) IS NOT NULL AND shares_outstanding>0""")

con.execute("""CREATE TABLE events AS WITH c AS (SELECT q.*,f.filing_date,f.company_name,
(SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date ORDER BY s.d DESC LIMIT 1) shares_now,
(SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date-INTERVAL 365 DAY ORDER BY s.d DESC LIMIT 1) shares_1y,
(SELECT p.px_close FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,
(SELECT p.rn FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_rn,
(SELECT p.rn FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_rn,
(SELECT p.d FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_date,
(SELECT p.px_open FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_price
FROM qp q JOIN filings f USING(symbol,report_date)
WHERE q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0),
e AS (SELECT *,shares_now*signal_close market_cap FROM c WHERE shares_now IS NOT NULL AND signal_close IS NOT NULL AND signal_rn IS NOT NULL AND entry_rn IS NOT NULL AND entry_price>0 AND shares_now*signal_close BETWEEN 10000000 AND 300000000),
x AS (SELECT e.*,
CASE WHEN market_cap>0 THEN fcf_yoy_change/market_cap END fcf_improve_to_mcap,
CASE WHEN market_cap>0 THEN ebit_yoy_change/market_cap END ebit_improve_to_mcap,
CASE WHEN market_cap>0 THEN -ni_ttm/market_cap END ni_loss_to_mcap,
CASE WHEN shares_1y>0 THEN shares_now/shares_1y-1 END dilution_1y,
CASE WHEN entry_price>0 THEN entry_price/signal_close-1 END gap,
(SELECT p.px_close FROM prices p WHERE p.symbol=e.symbol AND p.rn=e.signal_rn-20) pre20_base,
(SELECT p.px_close FROM prices p WHERE p.symbol=e.symbol AND p.rn=e.signal_rn-60) pre60_base,
(SELECT MAX(p.px_close) FROM prices p WHERE p.symbol=e.symbol AND p.rn BETWEEN e.signal_rn-59 AND e.signal_rn) high60,
(SELECT AVG(p.volume) FROM prices p WHERE p.symbol=e.symbol AND p.rn BETWEEN e.signal_rn-4 AND e.signal_rn) avgvol5,
(SELECT AVG(p.volume) FROM prices p WHERE p.symbol=e.symbol AND p.rn BETWEEN e.signal_rn-59 AND e.signal_rn-5) avgvol55,
(SELECT p.px_close/e.entry_price-1 FROM prices p WHERE p.symbol=e.symbol AND p.rn=e.entry_rn+20 LIMIT 1) r20d
FROM e)
SELECT *,CASE WHEN pre20_base>0 THEN signal_close/pre20_base-1 END pre20_ret,
CASE WHEN pre60_base>0 THEN signal_close/pre60_base-1 END pre60_ret,
CASE WHEN high60>0 THEN signal_close/high60 END pos_in_60d_high,
CASE WHEN avgvol55>0 THEN avgvol5/avgvol55 END pre_volume_accel,
(CASE WHEN market_cap<80000000 THEN 1 ELSE 0 END + CASE WHEN fcf_improve_to_mcap>0.01 THEN 1 ELSE 0 END + CASE WHEN ebit_improve_to_mcap>0.05 THEN 1 ELSE 0 END + CASE WHEN ni_loss_to_mcap>0.10 THEN 1 ELSE 0 END) tail_score
FROM x""")

con.execute(f"COPY events TO '{OUT/'a_tail_events.csv'}' (HEADER,DELIMITER ',')")

# Score performance, restricted to mature 2024-2025 cohorts.
score_rows=con.execute("""SELECT tail_score,COUNT(r20d) n,MEDIAN(r20d),AVG(r20d),AVG(CASE WHEN r20d>0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d>0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d>0.5 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d>1.0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) FROM events WHERE EXTRACT(year FROM report_date) IN (2024,2025) GROUP BY 1 ORDER BY 1""").fetchall()
with open(OUT/'score_performance.csv','w',newline='') as f:
 w=csv.writer(f); w.writerow(['score','n','median_r20','mean_r20','win_rate','up20','up50','up100','down20']); w.writerows(score_rows)

# Compare score-4 +50% winners with score-4 non-winners.
features=['market_cap','fcf_improve_to_mcap','ebit_improve_to_mcap','ni_loss_to_mcap','dilution_1y','pre20_ret','pre60_ret','pos_in_60d_high','pre_volume_accel','gap']
comp=[]
for feat in features:
 vals1=[r[0] for r in con.execute(f"SELECT {feat} FROM events WHERE tail_score=4 AND EXTRACT(year FROM report_date) IN (2024,2025) AND r20d>0.5 AND {feat} IS NOT NULL AND isfinite({feat})").fetchall()]
 vals0=[r[0] for r in con.execute(f"SELECT {feat} FROM events WHERE tail_score=4 AND EXTRACT(year FROM report_date) IN (2024,2025) AND r20d<=0.5 AND {feat} IS NOT NULL AND isfinite({feat})").fetchall()]
 if vals1 and vals0:
  u,p=mannwhitneyu(vals1,vals0,alternative='two-sided')
  med1=sorted(vals1)[len(vals1)//2] if len(vals1)%2 else (sorted(vals1)[len(vals1)//2-1]+sorted(vals1)[len(vals1)//2])/2
  med0=sorted(vals0)[len(vals0)//2] if len(vals0)%2 else (sorted(vals0)[len(vals0)//2-1]+sorted(vals0)[len(vals0)//2])/2
  comp.append((feat,len(vals1),med1,len(vals0),med0,p))
with open(OUT/'winner_vs_rest_features.csv','w',newline='') as f:
 w=csv.writer(f); w.writerow(['feature','n_winner','median_winner','n_rest','median_rest','mw_p']); w.writerows(comp)

# Simple pre-trade confirmations inside score-4 group. No threshold search: round intuitive cutoffs only.
checks=[('no_dilution','dilution_1y<=0'),('dilution_lt20','dilution_1y<0.20'),('pre20_positive','pre20_ret>0'),('pre20_negative','pre20_ret<=0'),('near_60d_high','pos_in_60d_high>=0.80'),('far_from_high','pos_in_60d_high<0.80'),('volume_accel','pre_volume_accel>=1.5'),('no_volume_accel','pre_volume_accel<1.5'),('gap_positive','gap>0'),('gap_gt5','gap>0.05')]
check_rows=[]
for name,cond in checks:
 a=con.execute(f"SELECT COUNT(*),SUM(CASE WHEN r20d>0.5 THEN 1 ELSE 0 END),SUM(CASE WHEN r20d>1 THEN 1 ELSE 0 END),MEDIAN(r20d),AVG(r20d),AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FROM events WHERE tail_score=4 AND EXTRACT(year FROM report_date) IN (2024,2025) AND r20d IS NOT NULL AND {cond}").fetchone()
 b=con.execute(f"SELECT COUNT(*),SUM(CASE WHEN r20d>0.5 THEN 1 ELSE 0 END) FROM events WHERE tail_score=4 AND EXTRACT(year FROM report_date) IN (2024,2025) AND r20d IS NOT NULL AND NOT ({cond})").fetchone()
 n,win50,win100,med,mean,down20=a; n0,w0=b
 p=None
 if n and n0:
  p=fisher_exact([[int(win50 or 0),int(n-(win50 or 0))],[int(w0 or 0),int(n0-(w0 or 0))]],alternative='greater').pvalue
 check_rows.append((name,n,win50,(win50/n if n else None),win100,(win100/n if n else None),med,mean,down20,n0,w0,(w0/n0 if n0 else None),p))
with open(OUT/'confirmation_filters.csv','w',newline='') as f:
 w=csv.writer(f);w.writerow(['filter','n','up50_n','up50_rate','up100_n','up100_rate','median_r20','mean_r20','down20_rate','complement_n','complement_up50_n','complement_up50_rate','fisher_one_sided_p']);w.writerows(check_rows)

# Year split for score-4 and a few confirmations that look interpretable ex ante.
year_rows=[]
for y in (2024,2025):
 for name,cond in [('score4','TRUE'),('score4_no_dilution','dilution_1y<=0'),('score4_pre20pos','pre20_ret>0'),('score4_high80','pos_in_60d_high>=0.8'),('score4_vol15','pre_volume_accel>=1.5')]:
  r=con.execute(f"SELECT COUNT(r20d),MEDIAN(r20d),AVG(r20d),AVG(CASE WHEN r20d>0.5 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d>1.0 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL),AVG(CASE WHEN r20d<-0.2 THEN 1.0 ELSE 0.0 END) FILTER(WHERE r20d IS NOT NULL) FROM events WHERE tail_score=4 AND EXTRACT(year FROM report_date)={y} AND {cond}").fetchone()
  year_rows.append((y,name)+r)
with open(OUT/'year_split.csv','w',newline='') as f:
 w=csv.writer(f);w.writerow(['year','filter','n','median_r20','mean_r20','up50','up100','down20']);w.writerows(year_rows)

# Save score-4 candidates sorted by outcome for inspection.
con.execute(f"COPY (SELECT symbol,company_name,report_date,filing_date,market_cap,fcf_improve_to_mcap,ebit_improve_to_mcap,ni_loss_to_mcap,dilution_1y,pre20_ret,pre60_ret,pos_in_60d_high,pre_volume_accel,gap,r20d FROM events WHERE tail_score=4 AND EXTRACT(year FROM report_date) IN (2024,2025) ORDER BY r20d DESC) TO '{OUT/'score4_candidates.csv'}' (HEADER,DELIMITER ',')")

print('SCORE PERFORMANCE'); [print(r) for r in score_rows]
print('WINNER VS REST'); [print(r) for r in comp]
print('CONFIRMATIONS'); [print(r) for r in check_rows]
print('YEAR SPLIT'); [print(r) for r in year_rows]
