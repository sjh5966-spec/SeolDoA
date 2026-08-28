from pathlib import Path
import duckdb, pandas as pd, numpy as np

OUT=Path('liquidity_capacity_results'); OUT.mkdir(exist_ok=True)
HF='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/stock_prices.parquet'
# Frozen FCF Quality High event keys from the already-validated 30-event sample.
HIGH_KEYS={16,118,124,139,179,258,277,280,353,358,403,409,430,520,521,583,606,607,76,83,152,168,234,310,362,376,408,465,469,473}
base=pd.read_csv('mfe_mae_input/event_mfe_mae.csv')
base=base[(base.event_key.isin(HIGH_KEYS)) & (base.n_days==21)].copy()
paths=pd.read_csv('mfe_mae_input/daily_path_0_20.csv',usecols=['event_key','day_num','d'])
entry=paths[(paths.event_key.isin(HIGH_KEYS)) & (paths.day_num==0)][['event_key','d']].rename(columns={'d':'entry_date'})
events=base.merge(entry,on='event_key',how='inner')
events['entry_date']=pd.to_datetime(events.entry_date)
assert len(events)==30, f'expected 30 frozen FCF High events, got {len(events)}'
syms=events.symbol.dropna().unique().tolist()

con=duckdb.connect()
con.execute('INSTALL httpfs; LOAD httpfs')
con.execute("SET threads=4; SET memory_limit='7GB'")
cols=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{HF}') LIMIT 1").fetchdf()['column_name'].tolist()
print('PRICE_COLUMNS',cols)
volcol=next((c for c in ['volume','Volume'] if c in cols),None)
if volcol is None: raise RuntimeError('stock_prices parquet has no volume column: '+str(cols))
qsyms=','.join("'"+s.replace("'","''")+"'" for s in syms)
px=con.execute(f"""SELECT symbol,TRY_CAST(report_date AS DATE) d,open::DOUBLE open,close::DOUBLE close,{volcol}::DOUBLE volume
FROM read_parquet('{HF}') WHERE symbol IN ({qsyms}) AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2012-01-01' AND DATE '2026-08-28'""").fetchdf()
px['d']=pd.to_datetime(px.d)

rows=[]
for _,e in events.iterrows():
    g=px[(px.symbol==e.symbol)&(px.d<e.entry_date)].sort_values('d').tail(20).copy()
    ent=px[(px.symbol==e.symbol)&(px.d==e.entry_date)]
    if len(g): g['dollar_volume']=g.close*g.volume
    rows.append({**e.to_dict(),'pre20_n':len(g),
      'adv20_dollar':g.dollar_volume.mean() if len(g) else np.nan,
      'median_dv20':g.dollar_volume.median() if len(g) else np.nan,
      'min_dv20':g.dollar_volume.min() if len(g) else np.nan,
      'entry_dollar_volume':float(ent.iloc[0].close*ent.iloc[0].volume) if len(ent) else np.nan,
      'entry_volume':float(ent.iloc[0].volume) if len(ent) else np.nan})
liq=pd.DataFrame(rows)
for pct in [.01,.02,.05,.10]: liq[f'capacity_adv_{int(pct*100)}pct']=liq.adv20_dollar*pct

s=[]
floors=[100_000,250_000,500_000,1_000_000,2_000_000,5_000_000]
for era,g in liq.groupby('era'):
  for floor in floors:
    x=g[g.adv20_dollar>=floor]
    s.append({'era':era,'test':f'ADV>={floor}','n':len(x),'coverage':len(x)/len(g),'mean_r20':x.r20_close.mean(),'median_r20':x.r20_close.median(),'win_rate':(x.r20_close>0).mean() if len(x) else np.nan,'up20_rate':(x.r20_close>=.2).mean() if len(x) else np.nan,'down20_rate':(x.r20_close<=-.2).mean() if len(x) else np.nan})
  for pos in [5_000,10_000,25_000,50_000,100_000,250_000]:
    for pct in [.01,.02,.05,.10]:
      ok=g[g.adv20_dollar*pct>=pos]
      s.append({'era':era,'test':f'position_{pos}_at_{int(pct*100)}pct_ADV','n':len(ok),'coverage':len(ok)/len(g),'mean_r20':ok.r20_close.mean(),'median_r20':ok.r20_close.median(),'win_rate':(ok.r20_close>0).mean() if len(ok) else np.nan,'up20_rate':(ok.r20_close>=.2).mean() if len(ok) else np.nan,'down20_rate':(ok.r20_close<=-.2).mean() if len(ok) else np.nan})
summary=pd.DataFrame(s)
liq.to_csv(OUT/'event_liquidity.csv',index=False)
summary.to_csv(OUT/'liquidity_threshold_summary.csv',index=False)
liq.groupby('era').agg(n=('event_key','size'),median_adv20=('adv20_dollar','median'),mean_adv20=('adv20_dollar','mean'),median_entry_dv=('entry_dollar_volume','median')).reset_index().to_csv(OUT/'era_liquidity_summary.csv',index=False)
print(liq[['event_key','symbol','era','entry_date','adv20_dollar','entry_dollar_volume','r20_close']].sort_values(['era','entry_date']).to_string(index=False))
print(summary.to_string(index=False))
