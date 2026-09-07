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

if not LOG.exists():
    raise SystemExit('missing paper_trade_log.csv')
df=pd.read_csv(LOG)

con=duckdb.connect()
con.execute('INSTALL httpfs; LOAD httpfs')
con.execute("SET threads=4; SET memory_limit='4GB'")

now=datetime.now(timezone.utc).isoformat()
rows=[]
realized_pnl=0.0
reserved_open=0.0

for _,r in df.iterrows():
    skip=str(r.get('skip_reason','')).strip()
    planned=pd.to_numeric(r.get('planned_notional'),errors='coerce')
    planned=float(planned) if pd.notna(planned) else 0.0
    state='SKIPPED' if skip!='none' else 'PLANNED'
    entry_px=np.nan; exit_px=np.nan; gross=np.nan; net=np.nan; pnl=np.nan
    entry_date=pd.to_datetime(r.get('entry_date'),errors='coerce')
    exit_date=pd.to_datetime(r.get('exit_date'),errors='coerce')

    if skip=='none' and pd.notna(entry_date):
        q=con.execute(f"SELECT open::DOUBLE FROM read_parquet('{P}') WHERE symbol=? AND TRY_CAST(report_date AS DATE)=? LIMIT 1",
                      [str(r.symbol),entry_date.date()]).fetchone()
        if q and q[0] is not None:
            entry_px=float(q[0]); state='OPEN'
        # Exit is day-20 close only; no interim price exit.
        if state=='OPEN' and pd.notna(exit_date):
            q=con.execute(f"SELECT close::DOUBLE FROM read_parquet('{P}') WHERE symbol=? AND TRY_CAST(report_date AS DATE)=? LIMIT 1",
                          [str(r.symbol),exit_date.date()]).fetchone()
            if q and q[0] is not None and entry_px>0:
                exit_px=float(q[0]); gross=exit_px/entry_px-1.0
                cost=pd.to_numeric(r.get('expected_rt_cost_spread1_k010'),errors='coerce')
                cost=float(cost) if pd.notna(cost) else 0.0
                net=gross-cost; pnl=planned*net; realized_pnl+=pnl; state='CLOSED'
        if state=='OPEN': reserved_open+=planned

    rows.append({
      'event_id':r.get('event_id',''),'symbol':r.get('symbol',''),'state':state,
      'skip_reason':skip,'entry_date':r.get('entry_date',''),'exit_date':r.get('exit_date',''),
      'planned_notional':planned,'paper_entry_open':entry_px,'paper_exit_close':exit_px,
      'gross_r20':gross,'paper_net_r20_model':net,'realized_pnl_model':pnl,
      'updated_at_utc':now})

pd.DataFrame(rows,columns=['event_id','symbol','state','skip_reason','entry_date','exit_date','planned_notional','paper_entry_open','paper_exit_close','gross_r20','paper_net_r20_model','realized_pnl_model','updated_at_utc']).to_csv(LEDGER,index=False)
summary=pd.DataFrame([{
 'initial_capital':INITIAL_CAPITAL,'realized_pnl_model':realized_pnl,
 'reserved_open_notional':reserved_open,'cash_after_reservations':INITIAL_CAPITAL+realized_pnl-reserved_open,
 'closed_positions':sum(x['state']=='CLOSED' for x in rows),'open_positions':sum(x['state']=='OPEN' for x in rows),
 'planned_positions':sum(x['state']=='PLANNED' for x in rows),'skipped_signals':sum(x['state']=='SKIPPED' for x in rows),
 'updated_at_utc':now}])
summary.to_csv('paper_portfolio_summary.csv',index=False)
print(summary.to_string(index=False))
