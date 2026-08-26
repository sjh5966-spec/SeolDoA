from pathlib import Path
import json
import duckdb
import pandas as pd
import numpy as np

SRC=Path('holding_path_results/events_holding_path.csv')
OUT=Path('mfe_mae_results'); OUT.mkdir(exist_ok=True)
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
P=BASE+'stock_prices.parquet'
if not SRC.exists(): raise FileNotFoundError(SRC)
ev=pd.read_csv(SRC)
ev=ev[ev['candidate3']==1].copy()
ev['filing_date']=pd.to_datetime(ev['filing_date'])
con=duckdb.connect(); con.execute("SET threads=4"); con.execute("SET memory_limit='6GB'")
con.register('ev',ev[['event_key','symbol','filing_date','entry_price','entry_rn_common','era']])
con.execute(f"""CREATE TABLE px AS
SELECT p.symbol,TRY_CAST(p.report_date AS DATE) d,p.open::DOUBLE px_open,p.high::DOUBLE px_high,p.low::DOUBLE px_low,p.close::DOUBLE px_close,
ROW_NUMBER() OVER(PARTITION BY p.symbol ORDER BY TRY_CAST(p.report_date AS DATE)) rn
FROM read_parquet('{P}') p JOIN (SELECT DISTINCT symbol FROM ev) s USING(symbol)
WHERE TRY_CAST(p.report_date AS DATE) BETWEEN DATE '2008-01-01' AND DATE '2026-08-26'
AND p.open IS NOT NULL AND p.high IS NOT NULL AND p.low IS NOT NULL AND p.close IS NOT NULL""")
path=con.execute("""SELECT e.event_key,e.symbol,e.era,e.entry_price,(p.rn-e.entry_rn_common) AS day_num,p.d,p.px_open,p.px_high,p.px_low,p.px_close
FROM ev e JOIN px p ON p.symbol=e.symbol AND p.rn BETWEEN e.entry_rn_common AND e.entry_rn_common+20
ORDER BY e.event_key,p.rn""").fetchdf()
path['high_ret']=path.px_high/path.entry_price-1
path['low_ret']=path.px_low/path.entry_price-1
path['close_ret']=path.px_close/path.entry_price-1
agg=path.groupby(['event_key','symbol','era','entry_price'],as_index=False).agg(
    mfe20=('high_ret','max'), mae20=('low_ret','min'), r20_close=('close_ret','last'), n_days=('day_num','count'))
for th in [0.10,0.20,0.30,0.50]:
    first=path[path.high_ret>=th].groupby('event_key')['day_num'].min()
    agg[f'first_up_{int(th*100)}d']=agg.event_key.map(first)
for th in [0.10,0.15,0.20]:
    first=path[path.low_ret<=-th].groupby('event_key')['day_num'].min()
    agg[f'first_down_{int(th*100)}d']=agg.event_key.map(first)

def simulate_one(g,tp,sl):
    ep=float(g.entry_price.iloc[0])
    for _,r in g.sort_values('day_num').iterrows():
        oret=r.px_open/ep-1
        if oret<=-sl: return oret,int(r.day_num),'SL_gap'
        if oret>=tp: return oret,int(r.day_num),'TP_gap'
        hit_sl=(r.px_low/ep-1)<=-sl
        hit_tp=(r.px_high/ep-1)>=tp
        if hit_sl: return -sl,int(r.day_num),'SL'
        if hit_tp: return tp,int(r.day_num),'TP'
    r=g.sort_values('day_num').iloc[-1]
    return r.px_close/ep-1,int(r.day_num),'TIME'

rules=[(0.20,0.10),(0.20,0.15),(0.30,0.10),(0.30,0.15),(0.50,0.15)]
rule_rows=[]; event_rule=[]
for tp,sl in rules:
    vals=[]
    for key,g in path.groupby('event_key'):
        ret,day_num,reason=simulate_one(g,tp,sl); vals.append((key,ret,day_num,reason))
    rdf=pd.DataFrame(vals,columns=['event_key','exit_return','exit_day','exit_reason']).merge(ev[['event_key','era']],on='event_key',how='left')
    rdf['tp']=tp; rdf['sl']=sl; event_rule.append(rdf)
    for era,g in list(rdf.groupby('era'))+[('ALL',rdf)]:
        x=g.exit_return
        rule_rows.append({'era':era,'tp':tp,'sl':sl,'n':len(g),'mean':x.mean(),'median':x.median(),'win_rate':(x>0).mean(),
                          'tp_exit_rate':g.exit_reason.str.startswith('TP').mean(),'sl_exit_rate':g.exit_reason.str.startswith('SL').mean(),
                          'time_exit_rate':(g.exit_reason=='TIME').mean(),'mean_exit_day':g.exit_day.mean(),
                          'down20_rate':(x<=-0.20).mean(),'up20_rate':(x>=0.20).mean()})
base_rows=[]
for era,g in list(agg.groupby('era'))+[('ALL',agg)]:
    x=g.r20_close
    base_rows.append({'era':era,'n':len(g),'mean':x.mean(),'median':x.median(),'win_rate':(x>0).mean(),'up20_rate':(x>=0.20).mean(),'down20_rate':(x<=-0.20).mean(),
                      'median_mfe20':g.mfe20.median(),'median_mae20':g.mae20.median(),'mfe20_ge20_rate':(g.mfe20>=0.20).mean(),'mae20_le10_rate':(g.mae20<=-0.10).mean(),'mae20_le15_rate':(g.mae20<=-0.15).mean()})
diag=[]
for era,e0 in list(agg.groupby('era'))+[('ALL',agg)]:
    for label,mask in [('R20_GE20',e0.r20_close>=0.20),('R20_0_20',(e0.r20_close>0)&(e0.r20_close<0.20)),('R20_LE0',e0.r20_close<=0)]:
        g=e0[mask]
        if len(g): diag.append({'era':era,'group':label,'n':len(g),'median_r20':g.r20_close.median(),'median_mfe20':g.mfe20.median(),'median_mae20':g.mae20.median(),'mae_le10_rate':(g.mae20<=-0.10).mean(),'mae_le15_rate':(g.mae20<=-0.15).mean()})
agg.to_csv(OUT/'event_mfe_mae.csv',index=False)
path.to_csv(OUT/'daily_path_0_20.csv',index=False)
pd.DataFrame(rule_rows).to_csv(OUT/'exit_rule_summary.csv',index=False)
pd.concat(event_rule,ignore_index=True).to_csv(OUT/'exit_rule_events.csv',index=False)
pd.DataFrame(base_rows).to_csv(OUT/'baseline_mfe_mae_summary.csv',index=False)
pd.DataFrame(diag).to_csv(OUT/'winner_loser_path_diagnostics.csv',index=False)
meta={'candidate3':'base turnaround + market_cap<80M + dFCF/mcap>1% + abs(NI_TTM loss)/mcap>10%','window':'entry day through common-axis +20 trading-day close','barrier_order':'conservative: open gaps first; if TP and SL both touched intraday on same day, SL assumed first','rules':rules,'events':int(len(agg)),'full_21_price_rows':int((agg.n_days==21).sum())}
with open(OUT/'meta.json','w') as f: json.dump(meta,f,indent=2)
print('BASELINE'); print(pd.DataFrame(base_rows).to_string(index=False)); print('\nEXIT RULES'); print(pd.DataFrame(rule_rows).to_string(index=False)); print('\nDIAGNOSTICS'); print(pd.DataFrame(diag).to_string(index=False)); print('\nMETA',json.dumps(meta,indent=2))
