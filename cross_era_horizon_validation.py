from pathlib import Path
import json
import duckdb
import pandas as pd
from scipy.stats import mannwhitneyu, fisher_exact

HIST=Path('historical_results/historical_events.csv')
MOD=Path('modern_regime_results/events_with_regime.csv')
OUT=Path('cross_era_horizon_results'); OUT.mkdir(exist_ok=True)
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
P=BASE+'stock_prices.parquet'; F=BASE+'stock_sec_filing.parquet'

if not HIST.exists() or not MOD.exists():
    raise FileNotFoundError(f'missing inputs: hist={HIST.exists()} mod={MOD.exists()}')

hist=pd.read_csv(HIST); mod=pd.read_csv(MOD)
hist['era']='2012-2020'; mod['era']='2023-2026'
cols_needed=['symbol','filing_date','entry_rn','entry_price','market_cap','fcf_improve_to_mcap','ebit_improve_to_mcap','ni_loss_to_mcap','r20d','tail_score','era','report_date']
for d in (hist,mod):
    for c in ['filing_date','report_date']:
        d[c]=pd.to_datetime(d[c])
all_events=pd.concat([hist[cols_needed],mod[cols_needed]],ignore_index=True)
all_events['candidate3']=(
    (all_events.market_cap<80_000_000) &
    (all_events.fcf_improve_to_mcap>0.01) &
    (all_events.ni_loss_to_mcap>0.10)
).astype(int)
all_events['score4']=(all_events.tail_score==4).astype(int)
all_events['event_key']=range(1,len(all_events)+1)

con=duckdb.connect(); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
con.register('ev',all_events)
# Only load prices for symbols in our event set and derive 60d/120d returns from the already point-in-time entry row number.
con.execute(f"""CREATE TABLE px AS
SELECT p.symbol,TRY_CAST(p.report_date AS DATE) d,p.close::DOUBLE px_close,
       ROW_NUMBER() OVER(PARTITION BY p.symbol ORDER BY TRY_CAST(p.report_date AS DATE)) rn
FROM read_parquet('{P}') p
JOIN (SELECT DISTINCT symbol FROM ev) s USING(symbol)
WHERE TRY_CAST(p.report_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2026-08-26' AND p.close IS NOT NULL""")
# Original 10-Q/10-K filing stream for next-filing horizon.
con.execute(f"""CREATE TABLE ff AS
SELECT symbol,TRY_CAST(filing_date AS DATE) filing_date
FROM read_parquet('{F}') f
JOIN (SELECT DISTINCT symbol FROM ev) s USING(symbol)
WHERE form_type IN ('10-Q','10-K') AND TRY_CAST(filing_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2026-08-26'""")

extd=con.execute("""WITH e AS (
 SELECT *,TRY_CAST(filing_date AS DATE) fdate FROM ev
), nf AS (
 SELECT e.event_key,MIN(f.filing_date) next_filing_date
 FROM e LEFT JOIN ff f ON f.symbol=e.symbol AND f.filing_date>e.fdate
 GROUP BY 1
)
SELECT e.*,p60.px_close/e.entry_price-1 r60d,p120.px_close/e.entry_price-1 r120d,nf.next_filing_date,
 (SELECT p.px_close/e.entry_price-1 FROM px p WHERE p.symbol=e.symbol AND nf.next_filing_date IS NOT NULL AND p.d<nf.next_filing_date ORDER BY p.d DESC LIMIT 1) r_next_filing
FROM e LEFT JOIN px p60 ON p60.symbol=e.symbol AND p60.rn=e.entry_rn+60
       LEFT JOIN px p120 ON p120.symbol=e.symbol AND p120.rn=e.entry_rn+120
       LEFT JOIN nf USING(event_key)
""").fetchdf()
extd.to_csv(OUT/'events_extended.csv',index=False)

horizons=['r20d','r60d','r120d','r_next_filing']
def summarize(g,h):
    x=g[h].dropna()
    if len(x)==0: return {'n':0,'median':None,'mean':None,'win_rate':None,'up20_rate':None,'down20_rate':None}
    return {'n':int(len(x)),'median':float(x.median()),'mean':float(x.mean()),'win_rate':float((x>0).mean()),'up20_rate':float((x>0.20).mean()),'down20_rate':float((x<-0.20).mean())}
rows=[]; tests=[]
for era in ['2012-2020','2023-2026']:
    e=extd[extd.era==era]
    for rule_name,flag in [('candidate3','candidate3'),('score4','score4')]:
        for h in horizons:
            a=e[e[flag]==1]; b=e[e[flag]==0]
            rows.append({'era':era,'rule':rule_name,'group':'selected','horizon':h,**summarize(a,h)})
            rows.append({'era':era,'rule':rule_name,'group':'rest','horizon':h,**summarize(b,h)})
            xa=a[h].dropna(); xb=b[h].dropna(); rec={'era':era,'rule':rule_name,'horizon':h,'selected_n':len(xa),'rest_n':len(xb)}
            if len(xa) and len(xb):
                rec['mw_selected_greater_p']=float(mannwhitneyu(xa,xb,alternative='greater').pvalue)
                aa=int((xa>0.20).sum()); cc=int((xb>0.20).sum())
                rec['fisher_up20_selected_greater_p']=float(fisher_exact([[aa,len(xa)-aa],[cc,len(xb)-cc]],alternative='greater').pvalue)
            tests.append(rec)
summary=pd.DataFrame(rows); summary.to_csv(OUT/'horizon_summary.csv',index=False)
pd.DataFrame(tests).to_csv(OUT/'horizon_tests.csv',index=False)

# Candidate3 year-by-year stability, no re-tuning.
yrows=[]
for era in ['2012-2020','2023-2026']:
    e=extd[extd.era==era].copy(); e['year']=pd.to_datetime(e.report_date).dt.year
    for y,g in e.groupby('year'):
        for h in ['r20d','r60d','r120d']:
            yrows.append({'era':era,'year':int(y),'group':'candidate3','horizon':h,**summarize(g[g.candidate3==1],h)})
            yrows.append({'era':era,'year':int(y),'group':'rest','horizon':h,**summarize(g[g.candidate3==0],h)})
pd.DataFrame(yrows).to_csv(OUT/'candidate3_year_summary.csv',index=False)

meta={
 'candidate3':'base turnaround universe AND market_cap<80M AND delta_FCF_YoY/market_cap>1% AND abs(NI_TTM_loss)/market_cap>10%; EBIT shock magnitude threshold removed',
 'score4':'candidate3 plus delta_EBIT_YoY/market_cap>5%',
 'entry':'next trading day open after filing',
 'horizons':'20/60/120 trading days plus last close strictly before next original 10-Q/10-K filing',
 'counts':{era:{'events':int((extd.era==era).sum()),'candidate3':int(((extd.era==era)&(extd.candidate3==1)).sum()),'score4':int(((extd.era==era)&(extd.score4==1)).sum())} for era in ['2012-2020','2023-2026']}
}
with open(OUT/'meta.json','w') as f: json.dump(meta,f,indent=2)
print('META',json.dumps(meta,indent=2))
print('\nSUMMARY')
print(summary.to_string(index=False))
print('\nTESTS')
print(pd.DataFrame(tests).to_string(index=False))
