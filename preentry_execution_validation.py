from pathlib import Path
import duckdb, pandas as pd, numpy as np

OUT=Path('preentry_execution_results'); OUT.mkdir(exist_ok=True)
HF='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/stock_prices.parquet'
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

def pick(names):
    return next((c for c in names if c in cols),None)
open_col=pick(['open','Open']); high_col=pick(['high','High']); low_col=pick(['low','Low']); close_col=pick(['close','Close']); vol_col=pick(['volume','Volume'])
missing=[n for n,c in [('open',open_col),('high',high_col),('low',low_col),('close',close_col),('volume',vol_col)] if c is None]
if missing: raise RuntimeError('missing OHLCV columns: '+str(missing)+' available='+str(cols))
qsyms=','.join("'"+s.replace("'","''")+"'" for s in syms)
px=con.execute(f'''SELECT symbol, TRY_CAST(report_date AS DATE) d,
  "{open_col}"::DOUBLE AS px_open, "{high_col}"::DOUBLE AS px_high,
  "{low_col}"::DOUBLE AS px_low, "{close_col}"::DOUBLE AS px_close,
  "{vol_col}"::DOUBLE AS volume
FROM read_parquet('{HF}')
WHERE symbol IN ({qsyms}) AND TRY_CAST(report_date AS DATE) BETWEEN DATE '2011-01-01' AND DATE '2026-08-28' ''').fetchdf()
px['d']=pd.to_datetime(px.d)

# All diagnostics below use ONLY trading days strictly before entry.
rows=[]; daily=[]
for _,e in events.iterrows():
    g=px[(px.symbol==e.symbol)&(px.d<e.entry_date)].sort_values('d').tail(20).copy()
    if len(g):
        g['dollar_volume']=g.px_close*g.volume
        g['prev_close']=g.px_close.shift(1)
        g['abs_ret']=g.px_close.pct_change().abs()
        g['amihud']=g.abs_ret/g.dollar_volume.replace(0,np.nan)
        # Corwin-Schultz-style OHLC spread estimate. Uses adjacent daily highs/lows;
        # negative alpha is floored at zero, yielding a nonnegative proxy.
        log_hl=np.log(g.px_high/g.px_low.replace(0,np.nan))
        beta=log_hl.pow(2)+log_hl.shift(1).pow(2)
        high2=pd.concat([g.px_high,g.px_high.shift(1)],axis=1).max(axis=1)
        low2=pd.concat([g.px_low,g.px_low.shift(1)],axis=1).min(axis=1)
        gamma=np.log(high2/low2.replace(0,np.nan)).pow(2)
        denom=3-2*np.sqrt(2)
        alpha=(np.sqrt(2*beta)-np.sqrt(beta))/denom - np.sqrt(gamma/denom)
        alpha=alpha.clip(lower=0)
        g['cs_spread']=2*(np.exp(alpha)-1)/(1+np.exp(alpha))
        g['event_key']=e.event_key; g['era']=e.era
        daily.append(g[['event_key','era','symbol','d','px_open','px_high','px_low','px_close','volume','dollar_volume','abs_ret','amihud','cs_spread']])
    rows.append({**e.to_dict(), 'pre20_n':len(g),
        'adv20_dollar':g.dollar_volume.mean() if len(g) else np.nan,
        'median_dv20':g.dollar_volume.median() if len(g) else np.nan,
        'amihud20_median':g.amihud.median() if len(g) else np.nan,
        'amihud20_mean':g.amihud.mean() if len(g) else np.nan,
        'cs_spread20_median':g.cs_spread.median() if len(g) else np.nan,
        'cs_spread20_mean':g.cs_spread.mean() if len(g) else np.nan})

ev=pd.DataFrame(rows)
daily_df=pd.concat(daily,ignore_index=True) if daily else pd.DataFrame()
assert (ev.pre20_n==20).all(), 'not every frozen event has 20 strictly pre-entry trading days'

# Transparent sensitivity model, deliberately not fitted to returns.
# Round-trip cost = 2*spread proxy + impact coefficient*sqrt(position/ADV20).
# Spread proxy is the pre-entry median Corwin-Schultz estimate.
# k values are sensitivity assumptions, not empirical calibration.
scenarios=[]
for capital in [15000,30000]:
  target=capital/3
  for k in [0.005,0.01,0.02,0.05]:
    x=ev.copy()
    x['position_notional']=np.minimum(target,0.05*x.adv20_dollar)
    x['participation']=x.position_notional/x.adv20_dollar
    x['spread_rt']=2*x.cs_spread20_median.fillna(0)
    x['impact_rt']=k*np.sqrt(x.participation.clip(lower=0))
    x['rt_cost']=x.spread_rt+x.impact_rt
    x['net_r20']=x.r20_close-x.rt_cost
    for era,g in x.groupby('era'):
      scenarios.append({'capital':capital,'k':k,'era':era,'n':len(g),
        'median_participation':g.participation.median(),'median_spread_rt':g.spread_rt.median(),
        'median_rt_cost':g.rt_cost.median(),'median_gross_r20':g.r20_close.median(),
        'median_net_r20':g.net_r20.median(),'mean_net_r20':g.net_r20.mean(),
        'net_win_rate':(g.net_r20>0).mean(),'net_up20_rate':(g.net_r20>=.2).mean(),
        'net_down20_rate':(g.net_r20<=-.2).mean()})

summary=pd.DataFrame(scenarios)
ev.to_csv(OUT/'event_preentry_execution.csv',index=False)
daily_df.to_csv(OUT/'preentry_ohlcv_diagnostics.csv',index=False)
summary.to_csv(OUT/'execution_cost_sensitivity.csv',index=False)
ev.groupby('era').agg(n=('event_key','size'),median_adv20=('adv20_dollar','median'),median_cs_spread=('cs_spread20_median','median'),median_amihud=('amihud20_median','median')).reset_index().to_csv(OUT/'era_preentry_diagnostics.csv',index=False)
print(ev[['event_key','symbol','era','entry_date','adv20_dollar','cs_spread20_median','amihud20_median','r20_close']].sort_values(['era','entry_date']).to_string(index=False))
print(summary.to_string(index=False))
