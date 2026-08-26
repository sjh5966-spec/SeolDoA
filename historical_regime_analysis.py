from pathlib import Path
import json
import duckdb
import pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu

OUT=Path('historical_results'); OUT.mkdir(exist_ok=True)
EVENTS=OUT/'historical_events.csv'
HF='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
P=HF+'stock_prices.parquet'

if not EVENTS.exists():
    raise FileNotFoundError(EVENTS)

events=pd.read_csv(EVENTS)
events['filing_date']=pd.to_datetime(events['filing_date'])
events['report_date']=pd.to_datetime(events['report_date'])

con=duckdb.connect()
# Verify benchmark availability and load only the two pre-specified ETFs.
avail=con.execute(f"""SELECT symbol,COUNT(*) n,MIN(TRY_CAST(report_date AS DATE)) d0,MAX(TRY_CAST(report_date AS DATE)) d1
FROM read_parquet('{P}') WHERE symbol IN ('IWM','SPY') GROUP BY 1 ORDER BY 1""").fetchdf()
avail.to_csv(OUT/'benchmark_coverage.csv',index=False)
if set(avail['symbol']) != {'IWM','SPY'}:
    raise RuntimeError(f'IWM/SPY benchmark coverage missing: {avail.to_dict(orient="records")}')

px=con.execute(f"""WITH x AS (
 SELECT symbol,TRY_CAST(report_date AS DATE) d,close::DOUBLE close,
        ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn
 FROM read_parquet('{P}')
 WHERE symbol IN ('IWM','SPY') AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2021-12-31' AND close IS NOT NULL
)
SELECT a.symbol,a.d,a.close,a.close/p20.close-1 ret20,a.close/p60.close-1 ret60
FROM x a LEFT JOIN x p20 ON p20.symbol=a.symbol AND p20.rn=a.rn-20
         LEFT JOIN x p60 ON p60.symbol=a.symbol AND p60.rn=a.rn-60
ORDER BY a.symbol,a.d""").fetchdf()
px['d']=pd.to_datetime(px['d'])

# Attach latest benchmark close available on or before the filing date (no future data).
def asof_series(sym):
    z=px[px.symbol==sym][['d','ret20','ret60']].sort_values('d').copy()
    z=z.rename(columns={'d':'benchmark_date','ret20':f'{sym.lower()}_ret20','ret60':f'{sym.lower()}_ret60'})
    return z

m=events.sort_values('filing_date').copy()
for sym in ['IWM','SPY']:
    m=pd.merge_asof(m.sort_values('filing_date'),asof_series(sym),left_on='filing_date',right_on='benchmark_date',direction='backward',tolerance=pd.Timedelta(days=7))
    m=m.drop(columns=['benchmark_date'])

# Pre-specified regime definition. No tuning on event outcomes:
# risk_on: small-caps positive over both 20d and 60d AND outperform SPY over 20d.
# risk_off: small-caps negative over both 20d and 60d.
# neutral: everything else.
m['iwm_rel20']=m['iwm_ret20']-m['spy_ret20']
m['regime']='neutral'
m.loc[(m.iwm_ret20>0)&(m.iwm_ret60>0)&(m.iwm_rel20>0),'regime']='risk_on'
m.loc[(m.iwm_ret20<0)&(m.iwm_ret60<0),'regime']='risk_off'

m.to_csv(OUT/'historical_events_with_regime.csv',index=False)

# Focus on frozen score4, while also keeping rest as a comparator.
def summarize(g):
    g=g[g.r20d.notna()].copy()
    if len(g)==0:
        return {'n':0,'median_r20':None,'mean_r20':None,'win_rate':None,'up20_rate':None,'up50_rate':None,'down20_rate':None}
    return {'n':len(g),'median_r20':float(g.r20d.median()),'mean_r20':float(g.r20d.mean()),'win_rate':float((g.r20d>0).mean()),'up20_rate':float((g.r20d>0.20).mean()),'up50_rate':float((g.r20d>0.50).mean()),'down20_rate':float((g.r20d<-0.20).mean())}

rows=[]
for regime in ['risk_on','neutral','risk_off']:
    for grp,mask in [('score4',m.tail_score==4),('rest',m.tail_score!=4)]:
        g=m[mask & (m.regime==regime)]
        rows.append({'regime':regime,'group':grp,**summarize(g)})
summary=pd.DataFrame(rows)
summary.to_csv(OUT/'regime_summary.csv',index=False)

# One-sided tests are directional and limited to the three pre-specified regimes.
tests=[]
for regime in ['risk_on','neutral','risk_off']:
    s=m[(m.tail_score==4)&(m.regime==regime)&m.r20d.notna()]
    r=m[(m.tail_score!=4)&(m.regime==regime)&m.r20d.notna()]
    rec={'regime':regime,'score4_n':len(s),'rest_n':len(r)}
    if len(s)>0 and len(r)>0:
        rec['mw_score4_greater_p']=float(mannwhitneyu(s.r20d,r.r20d,alternative='greater').pvalue)
        a=int((s.r20d>0.20).sum()); b=len(s)-a; c=int((r.r20d>0.20).sum()); d=len(r)-c
        rec['up20_fisher_score4_greater_p']=float(fisher_exact([[a,b],[c,d]],alternative='greater').pvalue)
    tests.append(rec)
pd.DataFrame(tests).to_csv(OUT/'regime_tests.csv',index=False)

# Direct comparison inside score4: risk-on vs non-risk-on. This tests whether market regime adds value to the frozen corporate signal.
s4=m[(m.tail_score==4)&m.r20d.notna()].copy()
on=s4[s4.regime=='risk_on']; non=s4[s4.regime!='risk_on']
direct={'risk_on':summarize(on),'non_risk_on':summarize(non)}
if len(on)>0 and len(non)>0:
    direct['mw_risk_on_greater_p']=float(mannwhitneyu(on.r20d,non.r20d,alternative='greater').pvalue)
    a=int((on.r20d>0.20).sum()); b=len(on)-a; c=int((non.r20d>0.20).sum()); d=len(non)-c
    direct['up20_fisher_risk_on_greater_p']=float(fisher_exact([[a,b],[c,d]],alternative='greater').pvalue)
with open(OUT/'regime_direct_score4.json','w') as f: json.dump(direct,f,indent=2)

print('BENCHMARK COVERAGE')
print(avail.to_string(index=False))
print('\nREGIME SUMMARY')
print(summary.to_string(index=False))
print('\nTESTS')
print(pd.DataFrame(tests).to_string(index=False))
print('\nDIRECT SCORE4 RISK-ON VS OTHER')
print(json.dumps(direct,indent=2))
