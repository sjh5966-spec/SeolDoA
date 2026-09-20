#!/usr/bin/env python3
# 20-slot execution test layered on frozen V2 signals.
# Pre-registered execution: D disclosure -> next tradable open buy; T+20 trading-day open sell.
from pathlib import Path
import json, requests
import numpy as np, pandas as pd

INP=Path("korea_turnaround_v2_historical_2018_2020_events.csv")
OUT=Path("korea_turnaround_v2_20slot_trades.csv")
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
  ent=q.iloc[0]; ei=int(ent.name)
  # T0=entry day, sell at open 20 trading days AFTER T0.
  xi=ei+20
  if xi>=len(z):dr("unmatured");continue
  ex=z.iloc[xi]
  # preserve frozen V2 corporate-action exclusion over holding path
  path=z.iloc[ei:xi+1]; sh=pd.to_numeric(path.Stocks,errors="coerce")
  if bool(((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any()):dr("corporate_action");continue
  # mcap priority uses information available before disclosure, same PIT mcap carried by frozen event file
  cand.append({"stock_code":r.stock_code,"signal_date":r.signal_date,"entry_date":ent.Date,
    "exit_date":ex.Date,"mcap":float(r.mcap),"entry_open":float(ent.Open),"exit_open":float(ex.Open)})
 c=pd.DataFrame(cand).sort_values(["entry_date","mcap","signal_date","stock_code"]).reset_index(drop=True)
 active=[]; rows=[]
 for d,g in c.groupby("entry_date",sort=True):
  # exits at this open free capacity before new buys
  active=[p for p in active if p["exit_date"]>d]
  free=SLOTS-len(active)
  for j,r in enumerate(g.itertuples(index=False)):
   accepted=j<free
   rec=r._asdict(); rec["status"]="entered" if accepted else "capacity_rejected"
   if accepted:
    gross=r.exit_open/r.entry_open-1
    net=(1-BUY_COST)*(r.exit_open/r.entry_open)*(1-SELL_COST)-1
    rec["gross_return"]=gross; rec["net_return"]=net
    active.append({"stock_code":r.stock_code,"exit_date":r.exit_date})
   else:
    rec["gross_return"]=r.exit_open/r.entry_open-1
    rec["net_return"]=np.nan
   rows.append(rec)
 t=pd.DataFrame(rows); t.to_csv(OUT,index=False)
 entered=t[t.status=="entered"].copy()
 # Fixed initial-capital 5% slots: realized trade P&L contribution; no compounding.
 entered["portfolio_pnl"]=SLOT_NOTIONAL*entered.net_return
 total=float(entered.portfolio_pnl.sum())
 start=entered.entry_date.min(); end=entered.exit_date.max()
 years=max((end-start).days/365.25,1/365.25)
 cagr=(1+total)**(1/years)-1 if 1+total>0 else np.nan
 summary={"test":"20-slot portfolio execution V1","signal_source":"frozen V2 historical 2018-2020 eligible events",
  "rules":{"slots":20,"slot_notional_initial_capital":0.05,"priority":"smaller PIT market cap; ties signal date then stock code",
  "entry":"first tradable open strictly after disclosure date","exit":"open 20 trading days after entry day (T0+20)",
  "same_open_order":"exits first, then entries","buy_cost":BUY_COST,"sell_cost":SELL_COST,"leverage":False},
  "candidates":int(len(t)),"entered":int(len(entered)),"capacity_rejected":int((t.status=="capacity_rejected").sum()),
  "capacity_rejected_rate":float((t.status=="capacity_rejected").mean()) if len(t) else None,
  "mean_net_trade_return":float(entered.net_return.mean()) if len(entered) else None,
  "median_net_trade_return":float(entered.net_return.median()) if len(entered) else None,
  "win_rate_net":float((entered.net_return>0).mean()) if len(entered) else None,
  "fixed_notional_total_return":total,"approx_cagr_from_fixed_notional_pnl":float(cagr) if np.isfinite(cagr) else None,
  "drop_reasons":drops,
  "note":"CAGR is approximate because fixed 5% initial-capital sizing is additive, not NAV-proportional compounding. MDD requires daily mark-to-market and is intentionally not fabricated."}
 SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
 print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))

if __name__=="__main__":main()
