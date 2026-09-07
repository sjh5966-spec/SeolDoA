from pathlib import Path
import duckdb
import pandas as pd

LOG=Path('paper_trade_log.csv')
if not LOG.exists(): raise SystemExit('missing paper_trade_log.csv')
df=pd.read_csv(LOG)
if len(df)==0:
    print('TIMESTAMP_ENRICHER rows=0'); raise SystemExit(0)
BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
F=BASE+'stock_sec_filing.parquet'
con=duckdb.connect(); con.execute('INSTALL httpfs; LOAD httpfs')
updated=0
for i,r in df.iterrows():
    if str(r.get('filing_timestamp','')).strip() not in ('','nan','NaN','None'):
        continue
    symbol=str(r.get('symbol','')).strip(); signal=pd.to_datetime(r.get('signal_date'),errors='coerce')
    if not symbol or pd.isna(signal): continue
    q=con.execute(f"""
      SELECT TRY_CAST(acceptance_date_time AS TIMESTAMP)
      FROM read_parquet('{F}')
      WHERE symbol=? AND TRY_CAST(filing_date AS DATE)=? AND form_type IN ('10-Q','10-K')
        AND acceptance_date_time IS NOT NULL
      ORDER BY TRY_CAST(acceptance_date_time AS TIMESTAMP)
      LIMIT 1
    """,[symbol,signal.date()]).fetchone()
    if q and q[0] is not None:
        df.at[i,'filing_timestamp']=pd.Timestamp(q[0]).isoformat(); updated+=1

df.to_csv(LOG,index=False)
print(f'TIMESTAMP_ENRICHER updated={updated}')
