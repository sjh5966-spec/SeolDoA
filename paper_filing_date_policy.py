from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

LOG=Path('paper_trade_log.csv')
if not LOG.exists(): raise SystemExit('missing paper_trade_log.csv')
df=pd.read_csv(LOG)
changed=0
for i,r in df.iterrows():
    if str(r.get('skip_reason','')).strip()!='filing_timestamp_ambiguous':
        continue
    signal=pd.to_datetime(r.get('signal_date'),errors='coerce')
    entry=pd.to_datetime(r.get('entry_date'),errors='coerce')
    # The frozen execution rule is first trading-day open strictly AFTER the filing date.
    # Therefore time-of-day cannot change the selected entry session. Exact acceptance time
    # remains an audit field when available, but its absence alone is not an execution skip.
    if pd.notna(signal) and pd.notna(entry) and entry.normalize()>signal.normalize():
        df.at[i,'skip_reason']='none'
        df.at[i,'updated_at_utc']=datetime.now(timezone.utc).isoformat()
        changed+=1

df.to_csv(LOG,index=False)
print(f'FILING_DATE_POLICY_RELEASED={changed}')
