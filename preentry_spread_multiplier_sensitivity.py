from pathlib import Path
import pandas as pd, numpy as np

OUT=Path('preentry_execution_results')
ev=pd.read_csv(OUT/'event_preentry_execution.csv')
ev['entry_date']=pd.to_datetime(ev.entry_date)
ev['exit_date']=pd.to_datetime(ev.exit_date)

# Corwin-Schultz estimates a proportional bid-ask spread. Treat 1x as the
# base round-trip spread cost (buy half-spread + sell half-spread) and retain
# 2x only as a conservative sensitivity. Nothing here is fitted to returns.
def run_portfolio(g, initial_capital, k, min_order, spread_mult):
    g=g.sort_values(['entry_date','event_key']).copy()
    cash=float(initial_capital); positions=[]; trades=[]
    skipped_min=skipped_slot=skipped_cash=0

    def close_through(dt):
        nonlocal cash,positions
        remain=[]
        for p in positions:
            if p['exit_date']<=dt:
                cash += p['notional']*(1+p['net_r20'])
                trades.append(p)
            else:
                remain.append(p)
        positions=remain

    for _,e in g.iterrows():
        close_through(e.entry_date)
        if len(positions)>=3:
            skipped_slot += 1; continue
        marked_equity=cash+sum(p['notional'] for p in positions)
        target=marked_equity/3.0
        liquidity_cap=0.05*e.adv20_dollar
        notional=min(target,liquidity_cap,cash)
        if notional < min_order:
            skipped_min += 1; continue
        if notional <= 0:
            skipped_cash += 1; continue
        participation=notional/e.adv20_dollar
        spread_rt=spread_mult*(0 if pd.isna(e.cs_spread20_median) else e.cs_spread20_median)
        impact_rt=k*np.sqrt(max(participation,0))
        rt_cost=spread_rt+impact_rt
        net_r20=e.r20_close-rt_cost
        cash -= notional
        positions.append({'event_key':int(e.event_key),'symbol':e.symbol,
            'entry_date':e.entry_date,'exit_date':e.exit_date,'notional':notional,
            'participation':participation,'gross_r20':e.r20_close,
            'spread_rt':spread_rt,'impact_rt':impact_rt,'rt_cost':rt_cost,
            'net_r20':net_r20})

    for p in sorted(positions,key=lambda z:z['exit_date']):
        cash += p['notional']*(1+p['net_r20']); trades.append(p)
    t=pd.DataFrame(trades)
    return {'initial_capital':initial_capital,'k':k,'min_order':min_order,
        'spread_mult':spread_mult,'signals':len(g),'trades':len(t),
        'skipped_min_order':skipped_min,'skipped_slot':skipped_slot,
        'skipped_cash':skipped_cash,'final_equity':cash,
        'total_return':cash/initial_capital-1,
        'median_trade_notional':t.notional.median() if len(t) else np.nan,
        'median_participation':t.participation.median() if len(t) else np.nan,
        'median_rt_cost':t.rt_cost.median() if len(t) else np.nan,
        'median_net_r20':t.net_r20.median() if len(t) else np.nan,
        'mean_net_r20':t.net_r20.mean() if len(t) else np.nan,
        'win_rate':(t.net_r20>0).mean() if len(t) else np.nan}, t

rows=[]; details=[]
for era,g in ev.groupby('era'):
  for capital in [15000,30000]:
    for k in [0.005,0.01,0.02,0.05]:
      for min_order in [100,250,500,1000]:
        for spread_mult in [1.0,2.0]:
          r,t=run_portfolio(g,capital,k,min_order,spread_mult)
          r['era']=era; rows.append(r)
          if len(t):
            t=t.copy(); t['era']=era; t['initial_capital']=capital
            t['k']=k; t['min_order']=min_order; t['spread_mult']=spread_mult
            details.append(t)

out=pd.DataFrame(rows)
detail=pd.concat(details,ignore_index=True) if details else pd.DataFrame()
assert out.skipped_slot.max()==0
out.to_csv(OUT/'portfolio_spread_multiplier_sensitivity.csv',index=False)
detail.to_csv(OUT/'portfolio_spread_multiplier_trade_detail.csv',index=False)
print('SPREAD_MULTIPLIER_SENSITIVITY')
print(out.to_string(index=False))
