from pathlib import Path
from datetime import datetime, timezone
import os
import duckdb
import numpy as np
import pandas as pd

BASE='https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/'
S=BASE+'stock_statement.parquet'
P=BASE+'stock_prices.parquet'
SH=BASE+'stock_shares_outstanding.parquet'
F=BASE+'stock_sec_filing.parquet'

LOG=Path('paper_trade_log.csv')
TEMPLATE=Path('paper_trade_log_template.csv')
QUEUE=Path('paper_signal_candidates.csv')
START_DATE=os.environ.get('PAPER_START_DATE','2026-09-07')
INITIAL_CAPITAL=float(os.environ.get('PAPER_INITIAL_CAPITAL','15000'))
MIN_ORDER=float(os.environ.get('PAPER_MIN_ORDER','500'))
SPEC_VERSION='paper-v1-2026-09-07'
FCF_CURRENT_HIGH=0.03591639
FCF_IMPROVE_HIGH=0.11938595

required_cols=list(pd.read_csv(TEMPLATE,nrows=0).columns)
if LOG.exists():
    log=pd.read_csv(LOG)
else:
    log=pd.DataFrame(columns=required_cols)
for c in required_cols:
    if c not in log.columns: log[c]=np.nan
log=log[required_cols]

con=duckdb.connect()
con.execute('INSTALL httpfs; LOAD httpfs')
con.execute("SET threads=4; SET memory_limit='7GB'")

# Detect whether the filing source contains a real acceptance/filed timestamp.
filing_cols=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{F}') LIMIT 1").fetchdf()['column_name'].tolist()
ts_candidates=['acceptance_datetime','accepted_datetime','filing_datetime','filed_at','accepted_at','acceptance_time','filing_time']
ts_col=next((c for c in ts_candidates if c in filing_cols),None)
ts_expr=f'TRY_CAST("{ts_col}" AS TIMESTAMP)' if ts_col else 'NULL::TIMESTAMP'
print('FILING_TIMESTAMP_COLUMN',ts_col)

# Current modern fundamentals. No return-dependent filters and no removed EBIT-improvement rule.
con.execute(f"""
CREATE OR REPLACE TABLE q AS
SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
 MAX(CASE WHEN item_name='ebit' AND finance_type='income_statement' THEN item_value END)::DOUBLE ebit,
 MAX(CASE WHEN item_name='net_income' AND finance_type='income_statement' THEN item_value END)::DOUBLE net_income,
 MAX(CASE WHEN item_name='stockholders_equity' AND finance_type='balance_sheet' THEN item_value END)::DOUBLE equity,
 MAX(CASE WHEN item_name='free_cash_flow' AND finance_type='cash_flow' THEN item_value END)::DOUBLE fcf
FROM read_parquet('{S}')
WHERE period_type='quarterly' AND report_date<>'TTM'
 AND item_name IN ('ebit','net_income','stockholders_equity','free_cash_flow')
 AND TRY_CAST(report_date AS DATE)>=DATE '2022-01-01'
GROUP BY 1,2
""")
con.execute("""
CREATE OR REPLACE TABLE qp AS
WITH w AS (
 SELECT *,
  LAG(report_date,4) OVER(PARTITION BY symbol ORDER BY report_date) d4,
  LAG(ebit,4) OVER(PARTITION BY symbol ORDER BY report_date) ebit_yoy,
  LAG(fcf,4) OVER(PARTITION BY symbol ORDER BY report_date) fcf_yoy,
  SUM(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni_ttm,
  COUNT(net_income) OVER(PARTITION BY symbol ORDER BY report_date ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) ni4
 FROM q)
SELECT * FROM w WHERE ni4=4 AND d4 IS NOT NULL
 AND DATE_DIFF('day',d4,report_date) BETWEEN 300 AND 450
""")
con.execute(f"""
CREATE OR REPLACE TABLE filings AS
SELECT symbol,TRY_CAST(report_date AS DATE) report_date,
 MIN(TRY_CAST(filing_date AS DATE)) filing_date,
 MIN({ts_expr}) filing_timestamp
FROM read_parquet('{F}')
WHERE form_type IN ('10-Q','10-K')
 AND TRY_CAST(report_date AS DATE) IS NOT NULL
 AND TRY_CAST(filing_date AS DATE) IS NOT NULL
GROUP BY 1,2
""")
con.execute(f"""
CREATE OR REPLACE TABLE prices AS
SELECT symbol,TRY_CAST(report_date AS DATE) d,
 open::DOUBLE px_open,high::DOUBLE px_high,low::DOUBLE px_low,close::DOUBLE px_close,volume::DOUBLE volume,
 ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY TRY_CAST(report_date AS DATE)) rn
FROM read_parquet('{P}')
WHERE TRY_CAST(report_date AS DATE)>=DATE '2022-01-01'
 AND close IS NOT NULL
""")
con.execute(f"""
CREATE OR REPLACE TABLE shares AS
SELECT symbol,TRY_CAST(report_date AS DATE) d,shares_outstanding::DOUBLE shares_outstanding
FROM read_parquet('{SH}')
WHERE TRY_CAST(report_date AS DATE) IS NOT NULL AND shares_outstanding>0
""")
con.execute(f"""
CREATE OR REPLACE TABLE raw_events AS
WITH c AS (
 SELECT q.*,f.filing_date,f.filing_timestamp,
  (SELECT s.shares_outstanding FROM shares s WHERE s.symbol=q.symbol AND s.d<=q.report_date ORDER BY s.d DESC LIMIT 1) shares_asof,
  (SELECT p.px_close FROM prices p WHERE p.symbol=q.symbol AND p.d<=f.filing_date ORDER BY p.d DESC LIMIT 1) signal_close,
  (SELECT p.d FROM prices p WHERE p.symbol=q.symbol AND p.d>f.filing_date ORDER BY p.d ASC LIMIT 1) entry_date
 FROM qp q JOIN filings f USING(symbol,report_date)
 WHERE q.ebit>0 AND q.ebit_yoy<=0 AND q.ni_ttm<0 AND q.equity>0
   AND q.fcf IS NOT NULL AND q.fcf_yoy IS NOT NULL
), v AS (
 SELECT *,shares_asof*signal_close market_cap
 FROM c WHERE shares_asof IS NOT NULL AND signal_close IS NOT NULL AND entry_date IS NOT NULL
)
SELECT *,
 fcf/market_cap current_fcf_to_mcap,
 (fcf-fcf_yoy)/market_cap fcf_improve_to_mcap,
 (-ni_ttm)/market_cap ni_loss_to_mcap
FROM v
WHERE market_cap BETWEEN 10000000 AND 300000000
 AND filing_date>=DATE '{START_DATE}'
""")

cand=con.execute("""
SELECT *,
 (market_cap<80000000 AND fcf_improve_to_mcap>0.01 AND ni_loss_to_mcap>0.10) candidate3,
 (market_cap<80000000 AND fcf_improve_to_mcap>0.01 AND ni_loss_to_mcap>0.10
  AND current_fcf_to_mcap>=0.03591639 AND fcf_improve_to_mcap>=0.11938595) fcf_high
FROM raw_events
ORDER BY filing_date,symbol
""").fetchdf()
if len(cand):
    cand['event_id']=cand.apply(lambda r:f"{r.symbol}|{r.report_date}|{r.filing_date}",axis=1)
    cand.to_csv(QUEUE,index=False)
else:
    pd.DataFrame(columns=['event_id','symbol','report_date','filing_date','candidate3','fcf_high']).to_csv(QUEUE,index=False)

high=cand[cand.fcf_high==True].copy() if len(cand) else cand
existing=set(log.event_id.dropna().astype(str)) if len(log) else set()
new_rows=[]
now=datetime.now(timezone.utc).isoformat()

# Lightweight paper ledger: realized P&L from completed rows; open positions are held at cost
# unless an entry price and a prior close are available for marking.
def fnum(x,default=np.nan):
    try:
        v=float(x)
        return v if np.isfinite(v) else default
    except Exception:
        return default

def portfolio_state(at_date):
    equity=INITIAL_CAPITAL
    active=[]
    if not len(log): return equity,INITIAL_CAPITAL,active
    for _,r in log.iterrows():
        if str(r.get('skip_reason',''))!='none': continue
        try:
            en=pd.to_datetime(r['entry_date'])
        except Exception:
            continue
        if pd.isna(en) or en>at_date: continue
        notional=fnum(r.get('planned_notional'),0.0)
        try: ex=pd.to_datetime(r.get('exit_date'))
        except Exception: ex=pd.NaT
        net=fnum(r.get('paper_net_r20'))
        if pd.notna(ex) and ex<at_date and np.isfinite(net):
            equity += notional*net
        elif pd.isna(ex) or ex>=at_date:
            active.append(r)
    open_cost=sum(fnum(r.get('planned_notional'),0.0) for r in active)
    cash=max(0.0,equity-open_cost)
    return equity,cash,active

for _,e in high.sort_values(['filing_date','symbol']).iterrows():
    event_id=f"{e.symbol}|{e.report_date}|{e.filing_date}"
    if event_id in existing: continue
    entry_date=pd.to_datetime(e.entry_date)
    px=con.execute("""SELECT d,px_open,px_high,px_low,px_close,volume FROM prices
                      WHERE symbol=? AND d<? ORDER BY d DESC LIMIT 20""",[e.symbol,entry_date.date()]).fetchdf().sort_values('d')
    row={c:'' for c in required_cols}
    row.update({'spec_version':SPEC_VERSION,'event_id':event_id,'symbol':e.symbol,
                'filing_timestamp':pd.to_datetime(e.filing_timestamp).isoformat() if pd.notna(e.filing_timestamp) else '',
                'signal_date':str(pd.to_datetime(e.filing_date).date()),'entry_date':str(entry_date.date()),
                'fcf_high':True,'rank_yoy_fcf_improvement_mcap':e.fcf_improve_to_mcap,
                'chosen_min_order':MIN_ORDER,'created_at_utc':now,'updated_at_utc':now})
    # Day-20 exit date is known from the trading calendar if data already extends far enough; otherwise blank until later.
    exitq=con.execute("SELECT d FROM prices WHERE symbol=? AND d>=? ORDER BY d LIMIT 1 OFFSET 20",[e.symbol,entry_date.date()]).fetchdf()
    if len(exitq): row['exit_date']=str(pd.to_datetime(exitq.iloc[0,0]).date())

    skip='none'
    if pd.isna(e.filing_timestamp): skip='filing_timestamp_ambiguous'
    if len(px)!=20:
        skip='data_unavailable'
    else:
        px['dollar_volume']=px.px_close*px.volume
        px['abs_ret']=px.px_close.pct_change().abs()
        px['amihud']=px.abs_ret/px.dollar_volume.replace(0,np.nan)
        log_hl=np.log(px.px_high/px.px_low.replace(0,np.nan))
        beta=log_hl.pow(2)+log_hl.shift(1).pow(2)
        high2=pd.concat([px.px_high,px.px_high.shift(1)],axis=1).max(axis=1)
        low2=pd.concat([px.px_low,px.px_low.shift(1)],axis=1).min(axis=1)
        gamma=np.log(high2/low2.replace(0,np.nan)).pow(2)
        denom=3-2*np.sqrt(2)
        alpha=((np.sqrt(2*beta)-np.sqrt(beta))/denom-np.sqrt(gamma/denom)).clip(lower=0)
        cs=2*(np.exp(alpha)-1)/(1+np.exp(alpha))
        adv=px.dollar_volume.mean(); spread=float(cs.median()) if cs.notna().any() else 0.0
        equity,cash,active=portfolio_state(entry_date)
        slot_count=len(active)
        target=equity/3.0; adv_cap=.05*adv; planned=min(target,adv_cap,cash)
        if slot_count>=3: skip='skipped_slot'; planned=0.0
        elif planned<MIN_ORDER: skip='skipped_min_order'; planned=0.0
        elif cash<=0: skip='skipped_cash'; planned=0.0
        part=(planned/adv) if adv>0 else np.nan
        row.update({'pre20_start':str(pd.to_datetime(px.d.min()).date()),'pre20_end':str(pd.to_datetime(px.d.max()).date()),
                    'adv20_dollar':adv,'median_dollar_volume20':px.dollar_volume.median(),
                    'amihud20_median':px.amihud.median(),'cs_spread20_median':spread,
                    'portfolio_equity_pre_entry':equity,'target_one_third_notional':target,'adv5pct_cap':adv_cap,
                    'planned_notional':planned,'planned_participation':part,'slot_count_pre_entry':slot_count})
        for mult in [1,2]:
            for k,lab in [(0.005,'005'),(0.01,'010'),(0.02,'020'),(0.05,'050')]:
                cost=mult*spread+k*np.sqrt(max(part,0)) if np.isfinite(part) else np.nan
                row[f'expected_rt_cost_spread{mult}_k{lab}']=cost
    row['skip_reason']=skip
    new_rows.append(row)

if new_rows:
    add=pd.DataFrame(new_rows,columns=required_cols)
    out=pd.concat([log,add],ignore_index=True)
    out.to_csv(LOG,index=False)
    print(f'APPENDED {len(add)} new FCF High signal rows')
    print(add[['event_id','symbol','signal_date','entry_date','rank_yoy_fcf_improvement_mcap','planned_notional','planned_participation','skip_reason']].to_string(index=False))
else:
    log.to_csv(LOG,index=False)
    print('APPENDED 0 new FCF High signal rows')
print(f'CANDIDATE3={int(cand.candidate3.sum()) if len(cand) else 0} FCF_HIGH={int(cand.fcf_high.sum()) if len(cand) else 0} START={START_DATE}')
