from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

LOG=Path('paper_trade_log.csv')
if not LOG.exists(): raise SystemExit('missing paper_trade_log.csv')
df=pd.read_csv(LOG)
if len(df)==0:
    print('BATCH_ALLOCATOR rows=0'); raise SystemExit(0)

created=pd.to_datetime(df['created_at_utc'],errors='coerce',utc=True)
latest=created.max()
if pd.isna(latest):
    print('BATCH_ALLOCATOR no created_at'); raise SystemExit(0)
# Only rows created in the latest scan are mutable pre-entry allocation rows.
mask=(created==latest) & (df['paper_entry_open'].isna())
idx=list(df.index[mask])
if not idx:
    print('BATCH_ALLOCATOR no new rows'); raise SystemExit(0)

def num(x,default=np.nan):
    v=pd.to_numeric(x,errors='coerce'); return float(v) if pd.notna(v) else default

# Existing executable/open rows reserve slots/cash. A row with no completed paper_net_r20 is active.
prior=df.index[~mask]
active_prior=[]
for j in prior:
    r=df.loc[j]
    if str(r.get('skip_reason','')).strip()!='none': continue
    if pd.isna(pd.to_numeric(r.get('paper_net_r20'),errors='coerce')):
        active_prior.append(j)

# Current paper equity uses realized model P&L only; open positions held at cost.
initial=15000.0
realized=0.0
for j in prior:
    r=df.loc[j]
    if str(r.get('skip_reason','')).strip()!='none': continue
    net=num(r.get('paper_net_r20')); notion=num(r.get('planned_notional'),0.0)
    if np.isfinite(net): realized += notion*net
equity=initial+realized
reserved=sum(num(df.loc[j].get('planned_notional'),0.0) for j in active_prior)
cash=max(0.0,equity-reserved)
active_count=len(active_prior)

# Process latest scan by entry date; within each entry date, higher YoY FCF improvement ranks first.
order=sorted(idx,key=lambda j:(pd.to_datetime(df.loc[j,'entry_date'],errors='coerce'),-num(df.loc[j,'rank_yoy_fcf_improvement_mcap'],-np.inf),str(df.loc[j,'symbol'])))
accepted=0
for j in order:
    r=df.loc[j]; skip=str(r.get('skip_reason','')).strip()
    # Preserve hard data/operational skips. filing_timestamp_ambiguous should already have been
    # released by the date policy when strict next-session entry is valid.
    if skip not in ('none','skipped_slot','skipped_cash','skipped_min_order'):
        continue
    adv=num(r.get('adv20_dollar')); target=num(r.get('target_one_third_notional'),equity/3); cap=num(r.get('adv5pct_cap'),0.05*adv if np.isfinite(adv) else 0); minimum=num(r.get('chosen_min_order'),500)
    planned=min(target,cap,cash) if np.isfinite(target) and np.isfinite(cap) else 0.0
    df.at[j,'portfolio_equity_pre_entry']=equity
    df.at[j,'slot_count_pre_entry']=active_count
    if active_count>=3:
        df.at[j,'skip_reason']='skipped_slot'; planned=0.0
    elif cash<=0:
        df.at[j,'skip_reason']='skipped_cash'; planned=0.0
    elif planned<minimum:
        df.at[j,'skip_reason']='skipped_min_order'; planned=0.0
    else:
        df.at[j,'skip_reason']='none'; active_count+=1; cash-=planned; accepted+=1
    df.at[j,'planned_notional']=planned
    part=planned/adv if np.isfinite(adv) and adv>0 else np.nan
    df.at[j,'planned_participation']=part
    cs=num(r.get('cs_spread20_median'))
    if np.isfinite(cs) and np.isfinite(part):
        for mult in (1,2):
            for k,lab in ((.005,'005'),(.01,'010'),(.02,'020'),(.05,'050')):
                df.at[j,f'expected_rt_cost_spread{mult}_k{lab}']=mult*cs+k*np.sqrt(max(part,0))
    df.at[j,'updated_at_utc']=datetime.now(timezone.utc).isoformat()

df.to_csv(LOG,index=False)
print(f'BATCH_ALLOCATOR new_rows={len(idx)} accepted={accepted} ending_slots={active_count} ending_cash={cash:.2f}')
