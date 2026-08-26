from pathlib import Path
import json
import duckdb
import pandas as pd
from scipy.stats import mannwhitneyu, fisher_exact

IN=Path('cross_era_horizon_results/events_extended.csv')
OUT=Path('holding_path_results'); OUT.mkdir(exist_ok=True)
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
P=BASE+'stock_prices.parquet'

if not IN.exists():
    raise FileNotFoundError(IN)

ev=pd.read_csv(IN)
ev['filing_date']=pd.to_datetime(ev['filing_date'])
ev['report_date']=pd.to_datetime(ev['report_date'])
# Frozen candidate: base turnaround universe already enforced upstream + the three robust filters.
ev['candidate3']=((ev.market_cap<80_000_000)&(ev.fcf_improve_to_mcap>0.01)&(ev.ni_loss_to_mcap>0.10)).astype(int)
ev['event_key']=range(1,len(ev)+1)

con=duckdb.connect(); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
con.register('ev',ev)
con.execute(f"""CREATE TABLE px AS
SELECT p.symbol,TRY_CAST(p.report_date AS DATE) d,p.close::DOUBLE px_close,
       ROW_NUMBER() OVER(PARTITION BY p.symbol ORDER BY TRY_CAST(p.report_date AS DATE)) rn
FROM read_parquet('{P}') p
JOIN (SELECT DISTINCT symbol FROM ev) s USING(symbol)
WHERE TRY_CAST(p.report_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2026-08-26' AND p.close IS NOT NULL""")

horizons=[5,10,15,20,30,40]
selects=['e.*']
for h in horizons:
    selects.append(f"p{h}.px_close/e.entry_price-1 r{h}d")
joins=[]
for h in horizons:
    joins.append(f"LEFT JOIN px p{h} ON p{h}.symbol=e.symbol AND p{h}.rn=e.entry_rn_common+{h}")
q='SELECT '+','.join(selects)+' FROM ev e '+' '.join(joins)
path=con.execute(q).fetchdf()
path.to_csv(OUT/'events_holding_path.csv',index=False)

def summarize(g,col):
    x=g[col].dropna()
    if len(x)==0:
        return dict(n=0,median=None,mean=None,win_rate=None,up10_rate=None,up20_rate=None,up50_rate=None,down10_rate=None,down20_rate=None)
    return dict(n=int(len(x)),median=float(x.median()),mean=float(x.mean()),win_rate=float((x>0).mean()),
                up10_rate=float((x>0.10).mean()),up20_rate=float((x>0.20).mean()),up50_rate=float((x>0.50).mean()),
                down10_rate=float((x<-0.10).mean()),down20_rate=float((x<-0.20).mean()))

rows=[]; tests=[]
for era in ['2012-2020','2023-2026']:
    e=path[path.era==era]
    for h in horizons:
        col=f'r{h}d'; a=e[e.candidate3==1]; b=e[e.candidate3==0]
        rows.append({'era':era,'group':'candidate3','horizon_days':h,**summarize(a,col)})
        rows.append({'era':era,'group':'rest','horizon_days':h,**summarize(b,col)})
        xa=a[col].dropna(); xb=b[col].dropna()
        rec={'era':era,'horizon_days':h,'candidate_n':len(xa),'rest_n':len(xb)}
        if len(xa) and len(xb):
            rec['mw_candidate_greater_p']=float(mannwhitneyu(xa,xb,alternative='greater').pvalue)
            for label,thr in [('up10',.10),('up20',.20),('up50',.50)]:
                aa=int((xa>thr).sum()); cc=int((xb>thr).sum())
                rec[f'fisher_{label}_p']=float(fisher_exact([[aa,len(xa)-aa],[cc,len(xb)-cc]],alternative='greater').pvalue)
        tests.append(rec)
summary=pd.DataFrame(rows); summary.to_csv(OUT/'holding_path_summary.csv',index=False)
pd.DataFrame(tests).to_csv(OUT/'holding_path_tests.csv',index=False)

# Also show the median path and excess hit-rate path directly.
pivot=[]
for era in ['2012-2020','2023-2026']:
    for h in horizons:
        s=summary[(summary.era==era)&(summary.horizon_days==h)].set_index('group')
        pivot.append({'era':era,'horizon_days':h,
                      'candidate_median':float(s.loc['candidate3','median']),
                      'rest_median':float(s.loc['rest','median']),
                      'median_spread':float(s.loc['candidate3','median']-s.loc['rest','median']),
                      'candidate_up20':float(s.loc['candidate3','up20_rate']),
                      'rest_up20':float(s.loc['rest','up20_rate']),
                      'up20_spread':float(s.loc['candidate3','up20_rate']-s.loc['rest','up20_rate']),
                      'candidate_down20':float(s.loc['candidate3','down20_rate']),
                      'rest_down20':float(s.loc['rest','down20_rate'])})
pd.DataFrame(pivot).to_csv(OUT/'path_comparison.csv',index=False)

meta={'rule':'Frozen candidate3: base EBIT turnaround universe + market cap < $80M + delta FCF YoY / market cap > 1% + abs(TTM NI loss) / market cap > 10%',
      'entry':'next trading day open after filing','horizons':horizons,
      'purpose':'Map when the post-filing repricing appears and fades; horizons pre-specified, not optimized after results.'}
with open(OUT/'meta.json','w') as f: json.dump(meta,f,indent=2)
print('SUMMARY')
print(summary.to_string(index=False))
print('\nTESTS')
print(pd.DataFrame(tests).to_string(index=False))
print('\nPATH')
print(pd.DataFrame(pivot).to_string(index=False))
