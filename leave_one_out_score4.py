from pathlib import Path
import json
import pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu

OUT=Path('loo_results'); OUT.mkdir(exist_ok=True)
HIST='historical_results/historical_events.csv'
MOD='modern_regime_results/events_with_regime.csv'

specs=[
 ('full4', ['size','fcf','ebit','loss']),
 ('drop_size',['fcf','ebit','loss']),
 ('drop_fcf',['size','ebit','loss']),
 ('drop_ebit',['size','fcf','loss']),
 ('drop_loss',['size','fcf','ebit']),
]

def prep(path):
 d=pd.read_csv(path)
 d=d[d.r20d.notna()].copy()
 d['size']=(d.market_cap<80_000_000)
 d['fcf']=(d.fcf_improve_to_mcap>0.01)
 d['ebit']=(d.ebit_improve_to_mcap>0.05)
 d['loss']=(d.ni_loss_to_mcap>0.10)
 return d

def metrics(g):
 r=g.r20d
 return {
  'n':len(g),
  'median_r20':float(r.median()) if len(g) else None,
  'mean_r20':float(r.mean()) if len(g) else None,
  'win_rate':float((r>0).mean()) if len(g) else None,
  'up20_rate':float((r>0.20).mean()) if len(g) else None,
  'up50_rate':float((r>0.50).mean()) if len(g) else None,
  'down20_rate':float((r<-0.20).mean()) if len(g) else None,
 }

def analyze(label,d):
 rows=[]; tests=[]
 for name,conds in specs:
  mask=pd.Series(True,index=d.index)
  for c in conds: mask &= d[c]
  g=d[mask]; rest=d[~mask]
  rec={'sample':label,'spec':name,'conditions':'+'.join(conds),**metrics(g)}
  rows.append(rec)
  trec={'sample':label,'spec':name,'n':len(g),'rest_n':len(rest)}
  if len(g) and len(rest):
   trec['mw_greater_p']=float(mannwhitneyu(g.r20d,rest.r20d,alternative='greater').pvalue)
   a=int((g.r20d>.2).sum()); c=int((rest.r20d>.2).sum())
   trec['up20_fisher_greater_p']=float(fisher_exact([[a,len(g)-a],[c,len(rest)-c]],alternative='greater').pvalue)
  tests.append(trec)
 return rows,tests

hist=prep(HIST); mod=prep(MOD)
rows=[]; tests=[]
for label,d in [('historical_2012_2020',hist),('modern_2023_2026',mod)]:
 r,t=analyze(label,d); rows+=r; tests+=t
pd.DataFrame(rows).to_csv(OUT/'loo_summary.csv',index=False)
pd.DataFrame(tests).to_csv(OUT/'loo_tests.csv',index=False)

# rank conditions by how much removing them hurts up20 and median relative to full4 in each era
summ=pd.DataFrame(rows)
full=summ[summ.spec=='full4'][['sample','up20_rate','median_r20','n']].rename(columns={'up20_rate':'full_up20','median_r20':'full_median','n':'full_n'})
impact=summ.merge(full,on='sample')
impact=impact[impact.spec!='full4'].copy()
impact['delta_up20_vs_full']=impact.up20_rate-impact.full_up20
impact['delta_median_vs_full']=impact.median_r20-impact.full_median
impact.to_csv(OUT/'condition_impact.csv',index=False)

# simple cross-era robustness score: a condition is more important if dropping it reduces up20 in both eras.
map_drop={'drop_size':'size','drop_fcf':'fcf','drop_ebit':'ebit','drop_loss':'loss'}
rob=[]
for spec,cond in map_drop.items():
 z=impact[impact.spec==spec]
 rob.append({'condition':cond,
             'historical_delta_up20':float(z[z['sample']=='historical_2012_2020'].delta_up20_vs_full.iloc[0]),
             'modern_delta_up20':float(z[z['sample']=='modern_2023_2026'].delta_up20_vs_full.iloc[0]),
             'historical_delta_median':float(z[z['sample']=='historical_2012_2020'].delta_median_vs_full.iloc[0]),
             'modern_delta_median':float(z[z['sample']=='modern_2023_2026'].delta_median_vs_full.iloc[0])})
pd.DataFrame(rob).to_csv(OUT/'robustness_rank.csv',index=False)
with open(OUT/'meta.json','w') as f: json.dump({'historical_n':len(hist),'modern_n':len(mod),'specs':specs},f,indent=2)
print('\nLOO SUMMARY'); print(pd.DataFrame(rows).to_string(index=False))
print('\nROBUSTNESS'); print(pd.DataFrame(rob).to_string(index=False))
