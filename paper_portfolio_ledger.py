from pathlib import Path
from datetime import datetime, timezone
import duckdb
import numpy as np
import pandas as pd

LOG=Path('paper_trade_log.csv')
LEDGER=Path('paper_portfolio_ledger.csv')
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
P=BASE+'stock_prices.parquet'
INITIAL_CAPITAL=15000.0

if not LOG.exists(): raise SystemExit('missing paper_trade_log.csv')
df=pd.read_csv(LOG)
con=duckdb.connect(); con.execute('INSTALL httpfs; LOAD httpfs'); con.execute("SET threads=4; SET memory_limit='4GB'")
now=datetime.now(timezone.utc).isoformat(); rows=[]; realized_pnl=0.0; reserved_open=0.0

def num(x):
    v=pd.to_numeric(x,errors='coerce'); return float(v) if pd.notna(v) else np.nan

for i,r in df.iterrows():
    skip=str(r.get('skip_reason','')).strip(); planned=num(r.get('planned_notional')); planned=planned if np.isfinite(planned) else 0.0
    state='SKIPPED' if skip!='none' else 'PLANNED'; entry_px=np.nan; exit_px=np.nan; gross=np.nan; net=np.nan; pnl=np.nan
    entry_date=pd.to_datetime(r.get('entry_date'),errors='coerce')
    exit_date=pd.to_datetime(r.get('exit_date'),errors='coerce')

    if skip=='none' and pd.notna(entry_date):
        eq=con.execute(f"SELECT open::DOUBLE FROM read_parquet('{P}') WHERE symbol=? AND TRY_CAST(report_date AS DATE)=? LIMIT 1",[str(r.symbol),entry_date.date()]).fetchone()
        if eq and eq[0] is not None:
            entry_px=float(eq[0]); state='OPEN'; df.at[i,'paper_entry_open']=entry_px

        # If exit_date was unknown when the signal was first logged, derive it later from the
        # trading sequence: entry session is day 0, the 20th subsequent session is the frozen exit.
        if pd.isna(exit_date):
            xq=con.execute(f"SELECT TRY_CAST(report_date AS DATE) d FROM read_parquet('{P}') WHERE symbol=? AND TRY_CAST(report_date AS DATE)>=? ORDER BY d LIMIT 1 OFFSET 20",[str(r.symbol),entry_date.date()]).fetchone()
            if xq and xq[0] is not None:
                exit_date=pd.Timestamp(xq[0]); df.at[i,'exit_date']=str(exit_date.date())

        if state=='OPEN' and pd.notna(exit_date):
            xq=con.execute(f"SELECT close::DOUBLE FROM read_parquet('{P}') WHERE symbol=? AND TRY_CAST(report_date AS DATE)=? LIMIT 1",[str(r.symbol),exit_date.date()]).fetchone()
            if xq and xq[0] is not None and entry_px>0:
                exit_px=float(xq[0]); gross=exit_px/entry_px-1.0
                cost=num(r.get('expected_rt_cost_spread1_k010')); cost=cost if np.isfinite(cost) else 0.0
                net=gross-cost; pnl=planned*net; realized_pnl+=pnl; state='CLOSED'
                df.at[i,'paper_exit_close']=exit_px; df.at[i,'gross_r20']=gross; df.at[i,'paper_net_r20']=net
        if state=='OPEN': reserved_open+=planned
    df.at[i,'updated_at_utc']=now

    rows.append({'event_id':r.get('event_id',''),'symbol':r.get('symbol',''),'state':state,'skip_reason':skip,
      'entry_date':str(entry_date.date()) if pd.notna(entry_date) else '', 'exit_date':str(exit_date.date()) if pd.notna(exit_date) else '',
      'planned_notional':planned,'paper_entry_open':entry_px,'paper_exit_close':exit_px,'gross_r20':gross,
      'paper_net_r20_model':net,'realized_pnl_model':pnl,'updated_at_utc':now})

df.to_csv(LOG,index=False)
pd.DataFrame(rows,columns=['event_id','symbol','state','skip_reason','entry_date','exit_date','planned_notional','paper_entry_open','paper_exit_close','gross_r20','paper_net_r20_model','realized_pnl_model','updated_at_utc']).to_csv(LEDGER,index=False)
summary=pd.DataFrame([{'initial_capital':INITIAL_CAPITAL,'realized_pnl_model':realized_pnl,'reserved_open_notional':reserved_open,
 'cash_after_reservations':INITIAL_CAPITAL+realized_pnl-reserved_open,'closed_positions':sum(x['state']=='CLOSED' for x in rows),
 'open_positions':sum(x['state']=='OPEN' for x in rows),'planned_positions':sum(x['state']=='PLANNED' for x in rows),
 'skipped_signals':sum(x['state']=='SKIPPED' for x in rows),'updated_at_utc':now}])
summary.to_csv('paper_portfolio_summary.csv',index=False); print(summary.to_string(index=False))
