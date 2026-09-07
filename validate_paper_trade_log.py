from pathlib import Path
import sys
import numpy as np
import pandas as pd

LOG=Path(sys.argv[1] if len(sys.argv)>1 else 'paper_trade_log.csv')
TEMPLATE=Path('paper_trade_log_template.csv')
ALLOWED_SKIP={'none','skipped_min_order','skipped_slot','skipped_cash','data_unavailable','filing_timestamp_ambiguous','trading_halt_or_no_open'}
required=list(pd.read_csv(TEMPLATE,nrows=0).columns)
if not LOG.exists(): raise SystemExit(f'missing log file: {LOG}')
df=pd.read_csv(LOG)
missing=[c for c in required if c not in df.columns]; extra=[c for c in df.columns if c not in required]
if missing: raise SystemExit(f'missing columns: {missing}')
if extra: raise SystemExit(f'unexpected columns: {extra}')
errors=[]

ids=df.event_id.dropna().astype(str)
if ids.duplicated().any(): errors.append(f'duplicate event_id values: {ids[ids.duplicated()].tolist()}')

def f(x):
    v=pd.to_numeric(x,errors='coerce'); return float(v) if pd.notna(v) else np.nan

for i,r in df.iterrows():
    row=i+2; skip=str(r.get('skip_reason','')).strip()
    if skip not in ALLOWED_SKIP: errors.append(f'row {row}: invalid skip_reason={skip!r}')
    signal=pd.to_datetime(r.get('signal_date'),errors='coerce'); entry=pd.to_datetime(r.get('entry_date'),errors='coerce'); exitd=pd.to_datetime(r.get('exit_date'),errors='coerce')
    if skip=='none' and pd.notna(signal) and pd.notna(entry) and entry.normalize()<=signal.normalize(): errors.append(f'row {row}: executable entry is not strictly after filing date')
    if pd.notna(exitd) and pd.notna(entry) and exitd<=entry: errors.append(f'row {row}: exit_date must be after entry_date')

    adv=f(r.get('adv20_dollar')); planned=f(r.get('planned_notional')); equity=f(r.get('portfolio_equity_pre_entry')); min_order=f(r.get('chosen_min_order')); part=f(r.get('planned_participation')); cs=f(r.get('cs_spread20_median'))
    if np.isfinite(adv) and np.isfinite(planned) and planned>0.05*adv+1e-6: errors.append(f'row {row}: planned_notional exceeds 5% ADV20')
    if np.isfinite(equity) and np.isfinite(planned) and planned>equity/3+1e-6: errors.append(f'row {row}: planned_notional exceeds one-third portfolio equity')
    if np.isfinite(adv) and adv>0 and np.isfinite(planned) and np.isfinite(part) and abs(part-planned/adv)>1e-8: errors.append(f'row {row}: planned_participation != planned_notional/ADV20')
    try:
        slots=int(r['slot_count_pre_entry'])
        if slots<0 or slots>3: errors.append(f'row {row}: slot_count_pre_entry outside 0..3')
        if slots>=3 and skip=='none': errors.append(f'row {row}: trade executable with no free slot')
    except Exception: pass
    if skip=='none' and np.isfinite(min_order) and np.isfinite(planned) and planned<min_order-1e-9: errors.append(f'row {row}: planned_notional below chosen_min_order without skip')

    if np.isfinite(cs) and np.isfinite(part):
        for mult in (1,2):
            for k,lab in ((.005,'005'),(.01,'010'),(.02,'020'),(.05,'050')):
                actual=f(r.get(f'expected_rt_cost_spread{mult}_k{lab}')); expected=mult*cs+k*np.sqrt(max(part,0))
                if np.isfinite(actual) and abs(actual-expected)>1e-8: errors.append(f'row {row}: expected cost mismatch spread{mult} k{lab}')

    pe=f(r.get('paper_entry_open')); px=f(r.get('paper_exit_close')); gross=f(r.get('gross_r20'))
    if np.isfinite(pe) and np.isfinite(px) and pe>0 and np.isfinite(gross) and abs(gross-(px/pe-1))>1e-8: errors.append(f'row {row}: gross_r20 inconsistent with paper fills')

if errors:
    print('\n'.join(errors)); raise SystemExit(1)
print(f'OK: {len(df)} rows, schema, uniqueness, timing, liquidity, cost and lifecycle invariants passed')
