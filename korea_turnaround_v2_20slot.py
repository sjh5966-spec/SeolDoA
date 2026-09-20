#!/usr/bin/env python3
# 20-slot execution test layered on frozen V2 signals.
# D disclosure -> next tradable open buy; T0+20 trading-day open sell.
from pathlib import Path
import json, requests
import numpy as np, pandas as pd

INP=Path("korea_turnaround_v2_historical_2018_2020_events.csv")
OUT=Path("korea_turnaround_v2_20slot_trades.csv"); NAV=Path("korea_turnaround_v2_20slot_nav.csv")
SUM=Path("korea_turnaround_v2_20slot_summary.json")
MARCAP="https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"
UA={"User-Agent":"Mozilla/5.0"}
SLOTS=20; SLOT_NOTIONAL=0.05; BUY_COST=0.0025; SELL_COST=0.0025
def norm(v):
 s=str(v or "").replace(".0","").strip(); return s.zfill(6) if s else ""
def get_marcap(y):
 p=Path(f"marcap-{y}.parquet")
 if not p.exists():
  r=requests.get(MARCAP.format(year=y),headers=UA,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
 z=pd.read_parquet(p)
 if "Date" not in z:z=z.reset_index()
 z["Date"]=pd.to_datetime(z["Date"]); z["Code"]=z["Code"].map(norm)
 return z[z.Market.isin(["KOSPI","KOSDAQ"])].sort_values(["Code","Date"]).reset_index(drop=True)
def main():
 e=pd.read_csv(INP,dtype={"stock_code":str}); e["stock_code"]=e.stock_code.map(norm); e["signal_date"]=pd.to_datetime(e.signal_date)
 mk=pd.concat([get_marcap(y) for y in range(2018,2022)],ignore_index=True).sort_values(["Code","Date"])
 by={c:g.reset_index(drop=True) for c,g in mk.groupby("Code",sort=False)}
 cand=[]; drops={}
 def dr(k):drops[k]=drops.get(k,0)+1
 for r in e.itertuples(index=False):
  z=by.get(r.stock_code)
  if z is None:dr("no_market");continue
  q=z[(z.Date>r.signal_date)&(pd.to_numeric(z.Open,errors="coerce")>0)&(pd.to_numeric(z.Volume,errors="coerce")>0)]
  if q.empty:dr("no_entry");continue
  ent=q.iloc[0]; ei=int(ent.name); xi=ei+20
  if xi>=len(z):dr("unmatured");continue
  ex=z.iloc[xi]; path=z.iloc[ei:xi+1]; sh=pd.to_numeric(path.Stocks,errors="coerce")
  if bool(((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any()):dr("corporate_action");continue
  cand.append({"stock_code":r.stock_code,"signal_date":r.signal_date,"entry_date":ent.Date,"exit_date":ex.Date,
   "mcap":float(r.mcap),"entry_open":float(ent.Open),"exit_open":float(ex.Open)})
 c=pd.DataFrame(cand).sort_values(["entry_date","mcap","signal_date","stock_code"]).reset_index(drop=True)
 active=[]; rows=[]
 for d,g in c.groupby("entry_date",sort=True):
  active=[p for p in active if p["exit_date"]>d]; free=SLOTS-len(active)
  for j,r in enumerate(g.itertuples(index=False)):
   accepted=j<free; rec=r._asdict(); rec["status"]="entered" if accepted else "capacity_rejected"
   gross=r.exit_open/r.entry_open-1
   rec["gross_return"]=gross
   if accepted:
    rec["net_return"]=(1-BUY_COST)*(r.exit_open/r.entry_open)*(1-SELL_COST)-1
    active.append({"stock_code":r.stock_code,"exit_date":r.exit_date})
   else: rec["net_return"]=np.nan
   rows.append(rec)
 t=pd.DataFrame(rows); t.to_csv(OUT,index=False); entered=t[t.status=="entered"].copy()
 # Daily mark-to-market fixed-notional NAV. Buy cost charged on entry; sell cost on exit.
 cal=pd.DatetimeIndex(sorted(mk.Date.unique())); cal=cal[(cal>=entered.entry_date.min())&(cal<=entered.exit_date.max())]
 realized=0.0; navrows=[]
 for d in cal:
  pnl=0.0; used=0
  for r in entered.itertuples(index=False):
   if d<r.entry_date: continue
   if d>=r.exit_date:
    if d==r.exit_date: pass
    continue
   z=by[r.stock_code]; px=z[z.Date.eq(d)]
   if px.empty: # carry last available close for suspended/nontrading stock
    px=z[(z.Date<d)&(z.Date>=r.entry_date)]
    mark=float(px.iloc[-1].Close) if not px.empty else r.entry_open
   else: mark=float(px.iloc[0].Close)
   pnl += SLOT_NOTIONAL*((1-BUY_COST)*mark/r.entry_open-1); used+=1
  # realized P&L for trades exited on or before d
  done=entered[entered.exit_date<=d]
  realized=float((SLOT_NOTIONAL*done.net_return).sum())
  nav=1+realized+pnl
  navrows.append({"date":d,"nav":nav,"active_slots":used,"cash_fraction":1-used*SLOT_NOTIONAL})
 n=pd.DataFrame(navrows); n["peak"]=n.nav.cummax(); n["drawdown"]=n.nav/n.peak-1; n.to_csv(NAV,index=False)
 total=float(n.iloc[-1].nav-1); years=max((n.iloc[-1].date-n.iloc[0].date).days/365.25,1/365.25)
 cagr=(n.iloc[-1].nav/n.iloc[0].nav)**(1/years)-1
 annual={}
 for y,g in n.groupby(n.date.dt.year):
  annual[str(y)]=float(g.iloc[-1].nav/g.iloc[0].nav-1)
 rejected=t[t.status=="capacity_rejected"]
 rej_net=(1-BUY_COST)*(rejected.exit_open/rejected.entry_open)*(1-SELL_COST)-1
 summary={"test":"20-slot portfolio execution V1 + daily NAV","rules":{"slots":20,"slot_notional_initial_capital":0.05,
  "priority":"smaller PIT market cap; ties signal date then stock code","entry":"first tradable open strictly after disclosure date",
  "exit":"open 20 trading days after entry day (T0+20)","same_open_order":"exits first, then entries","round_trip_cost":BUY_COST+SELL_COST},
  "candidates":int(len(t)),"entered":int(len(entered)),"capacity_rejected":int(len(rejected)),
  "capacity_rejected_rate":float(len(rejected)/len(t)),"entered_net_mean":float(entered.net_return.mean()),
  "entered_net_median":float(entered.net_return.median()),"entered_net_win_rate":float((entered.net_return>0).mean()),
  "rejected_hypothetical_net_mean":float(rej_net.mean()) if len(rejected) else None,
  "rejected_hypothetical_net_median":float(rej_net.median()) if len(rejected) else None,
  "rejected_hypothetical_net_win_rate":float((rej_net>0).mean()) if len(rejected) else None,
  "nav_total_return":total,"cagr":float(cagr),"mdd":float(n.drawdown.min()),"annual_returns":annual,
  "average_active_slots":float(n.active_slots.mean()),"max_active_slots":int(n.active_slots.max()),
  "average_cash_fraction":float(n.cash_fraction.mean()),"drop_reasons":drops,
  "note":"Daily NAV uses fixed 5% of initial capital per accepted trade; close marks between entry and exit, open execution on entry/exit, costs at execution."}
 SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
if __name__=="__main__":main()
