from pathlib import Path
import json
import duckdb
import pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu

OUT=Path('modern_regime_results'); OUT.mkdir(exist_ok=True)
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'; P=BASE+'stock_prices.parquet'; SH=BASE+'stock_shares_outstanding.parquet'; F=BASE+'stock_sec_filing.parquet'
con=duckdb.connect('modern_regime.duckdb'); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")

con.execute(f"""CREATE OR REPLACE TABLE q AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE ebit,
MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE net_income,
MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE equity,
MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN item_value END)::DOUBLE fcf
FROM read_parquet('{S}') WHERE period_type='quarterly' AND report_date<>'TTM' AND item_name IN ('ebit','net_income','stockholders_equity','free_cash_flow')
AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2022-01-01' AND DATE '2026-08-26' GROUP BY 1,2""")
con.execute("""CREATE OR REPLACE TABLE qp AS WITH w AS (SELECT *,LAG(report_date,4) OVER(PARTITION BY symbol ORDER BY report_date) d4,LAG(ebit,4) OVER(PARTITION BY symbol ORDER BY report_date) ebit_yoy,LAG(fcf,4) OVER(PARTITION BY symbol ORDER BY report_date) fcf_yoy,SUM(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni_ttm,COUNT(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni4 FROM q) SELECT * FROM w WHERE ni4=4 AND d4 IS NOT NULL AND DATE_DIFF('day',d4,report_date) BETWEEN 300 AND 450""")
con.execute(f"""CREATE OR REPLACE TABLE filings AS SELECT symbol,TRY_CAST(report_date AS DATE) report_date,MIN(TRY_CAST(filing_date AS DATE)) filing_date FROM read_parquet('{F}') WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(report_date AS DATE) IS NOT NULL AND TRY_CAST(filing_date AS DATE) IS NOT NULL GROUP BY 1,2""")
con.execute(f"""CREATE OR REPLACE TABLE prices AS SELECT symbol,TRY_CAST(report_date AS DATE) d,open::DOUBLE px_open,close::DOUBLE px_close,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn FROM read_parquet('{P}') WHERE TRY_CAST(report_date AS DATE) BETWEEN DATE '2021-01-01' AND DATE '2026-08-26' AND open IS NOT NULL AND close IS NOT NULL""")
con.execute(f"""CREATE OR REPLACE TABLE shares AS SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding FROM read_parquet('{SH}') WHERE TRY_CAST(report_date AS DATE) IS NOT NULL AND shares_outstanding>0""")
con.execute("""CREATE OR REPLACE TABLE e0 AS WITH c AS (SELECT q.*,f.filing_date,
(SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date ORDER BY s.d DESC LIMIT 1) shares_asof,
(SELECT p.px_close FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,
(SELECT p.rn FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_rn,
(SELECT p.px_open FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_price
FROM qp q JOIN filings f USING(symbol,report_date) WHERE q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0 AND q.fcf IS NOT NULL AND q.fcf_yoy IS NOT NULL),v AS (SELECT *,shares_asof*signal_close market_cap FROM c WHERE shares_asof IS NOT NULL AND signal_close IS NOT NULL AND entry_rn IS NOT NULL AND entry_price>0) SELECT v.*,(fcf-fcf_yoy)/market_cap fcf_improve_to_mcap,(ebit-ebit_yoy)/market_cap ebit_improve_to_mcap,(-ni_ttm)/market_cap ni_loss_to_mcap,p20.px_close/entry_price-1 r20d FROM v LEFT JOIN prices p20 ON p20.symbol=v.symbol AND p20.rn=v.entry_rn+20 WHERE market_cap BETWEEN 10000000 AND 300000000""")
con.execute("""CREATE OR REPLACE TABLE events AS SELECT *, (CASE WHEN market_cap<80000000 THEN 1 ELSE 0 END + CASE WHEN fcf_improve_to_mcap>0.01 THEN 1 ELSE 0 END + CASE WHEN ebit_improve_to_mcap>0.05 THEN 1 ELSE 0 END + CASE WHEN ni_loss_to_mcap>0.10 THEN 1 ELSE 0 END) tail_score FROM e0""")

events=con.execute("SELECT * FROM events").fetchdf(); events['filing_date']=pd.to_datetime(events['filing_date'])
bench=con.execute("""WITH x AS (SELECT symbol,d,px_close,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY d) rn FROM prices WHERE symbol IN ('IWM','SPY')) SELECT a.symbol,a.d,a.px_close/p20.px_close-1 ret20,a.px_close/p60.px_close-1 ret60 FROM x a LEFT JOIN x p20 ON p20.symbol=a.symbol AND p20.rn=a.rn-20 LEFT JOIN x p60 ON p60.symbol=a.symbol AND p60.rn=a.rn-60""").fetchdf(); bench['d']=pd.to_datetime(bench['d'])
m=events.sort_values('filing_date').copy()
for sym in ['IWM','SPY']:
 z=bench[bench.symbol==sym][['d','ret20','ret60']].sort_values('d').rename(columns={'d':'benchmark_date','ret20':f'{sym.lower()}_ret20','ret60':f'{sym.lower()}_ret60'})
 m=pd.merge_asof(m.sort_values('filing_date'),z,left_on='filing_date',right_on='benchmark_date',direction='backward',tolerance=pd.Timedelta(days=7)).drop(columns=['benchmark_date'])
m['iwm_rel20']=m.iwm_ret20-m.spy_ret20
m['regime']='neutral'; m.loc[(m.iwm_ret20>0)&(m.iwm_ret60>0)&(m.iwm_rel20>0),'regime']='risk_on'; m.loc[(m.iwm_ret20<0)&(m.iwm_ret60<0),'regime']='risk_off'
m.to_csv(OUT/'events_with_regime.csv',index=False)

def summ(g):
 g=g[g.r20d.notna()]
 return {'n':len(g),'median_r20':float(g.r20d.median()) if len(g) else None,'mean_r20':float(g.r20d.mean()) if len(g) else None,'win_rate':float((g.r20d>0).mean()) if len(g) else None,'up20_rate':float((g.r20d>0.2).mean()) if len(g) else None,'up50_rate':float((g.r20d>0.5).mean()) if len(g) else None,'down20_rate':float((g.r20d<-0.2).mean()) if len(g) else None}
rows=[]
for y in sorted(m.report_date.dt.year.unique()):
 for reg in ['risk_on','neutral','risk_off']:
  for grp,mask in [('score4',m.tail_score==4),('rest',m.tail_score!=4)]: rows.append({'year':int(y),'regime':reg,'group':grp,**summ(m[(m.report_date.dt.year==y)&(m.regime==reg)&mask])})
pd.DataFrame(rows).to_csv(OUT/'year_regime_summary.csv',index=False)
agg=[]
for reg in ['risk_on','neutral','risk_off']:
 for grp,mask in [('score4',m.tail_score==4),('rest',m.tail_score!=4)]: agg.append({'regime':reg,'group':grp,**summ(m[(m.regime==reg)&mask])})
pd.DataFrame(agg).to_csv(OUT/'regime_summary.csv',index=False)

s=m[(m.tail_score==4)&(m.regime=='risk_on')&m.r20d.notna()]; r=m[(m.tail_score!=4)&(m.regime=='risk_on')&m.r20d.notna()]; non=m[(m.tail_score==4)&(m.regime!='risk_on')&m.r20d.notna()]
tests={'score4_risk_on_vs_rest':{},'score4_risk_on_vs_nonriskon':{}}
if len(s) and len(r):
 tests['score4_risk_on_vs_rest']['mw_p']=float(mannwhitneyu(s.r20d,r.r20d,alternative='greater').pvalue); a=int((s.r20d>.2).sum()); c=int((r.r20d>.2).sum()); tests['score4_risk_on_vs_rest']['fisher_up20_p']=float(fisher_exact([[a,len(s)-a],[c,len(r)-c]],alternative='greater').pvalue)
if len(s) and len(non):
 tests['score4_risk_on_vs_nonriskon']['mw_p']=float(mannwhitneyu(s.r20d,non.r20d,alternative='greater').pvalue); a=int((s.r20d>.2).sum()); c=int((non.r20d>.2).sum()); tests['score4_risk_on_vs_nonriskon']['fisher_up20_p']=float(fisher_exact([[a,len(s)-a],[c,len(non)-c]],alternative='greater').pvalue)
tests['score4_risk_on']=summ(s); tests['score4_nonriskon']=summ(non); tests['coverage']={'min_report':str(m.report_date.min().date()),'max_report':str(m.report_date.max().date()),'events':int(len(m)),'score4':int((m.tail_score==4).sum())}
with open(OUT/'tests.json','w') as f: json.dump(tests,f,indent=2)
print(pd.DataFrame(agg).to_string(index=False)); print(json.dumps(tests,indent=2))
