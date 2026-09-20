#!/usr/bin/env python3
from pathlib import Path
import json,requests,numpy as np,pandas as pd
INP=Path("korea_turnaround_v2_historical_2018_2020_events.csv"); OUT=Path("korea_turnaround_v2_20slot_dynamic_trades.csv"); NAV=Path("korea_turnaround_v2_20slot_dynamic_nav.csv"); SUM=Path("korea_turnaround_v2_20slot_priority_summary.json")
URL="https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"; UA={"User-Agent":"Mozilla/5.0"}
SLOTS=20; W=.05; BUY=.0025; SELL=.0025
def norm(v):
 s=str(v or "").replace(".0","").strip(); return s.zfill(6) if s else ""
def load(y):
 p=Path(f"marcap-{y}.parquet")
 if not p.exists():
  r=requests.get(URL.format(year=y),headers=UA,timeout=180);r.raise_for_status();p.write_bytes(r.content)
 z=pd.read_parquet(p)
 if "Date" not in z:z=z.reset_index()
 z.Date=pd.to_datetime(z.Date);z.Code=z.Code.map(norm)
 return z[z.Market.isin(["KOSPI","KOSDAQ"])].sort_values(["Code","Date"]).reset_index(drop=True)
def main():
 e=pd.read_csv(INP,dtype={"stock_code":str});e.stock_code=e.stock_code.map(norm);e.signal_date=pd.to_datetime(e.signal_date)
 mk=pd.concat([load(y) for y in range(2018,2022)],ignore_index=True); by={c:g.reset_index(drop=True) for c,g in mk.groupby("Code")}
 cand=[]
 for r in e.itertuples(index=False):
  z=by.get(r.stock_code)
  if z is None:continue
  q=z[(z.Date>r.signal_date)&(z.Open>0)&(z.Volume>0)]
  if q.empty:continue
  ent=q.iloc[0];ei=int(ent.name);xi=ei+20
  if xi>=len(z):continue
  ex=z.iloc[xi]; sh=pd.to_numeric(z.iloc[ei:xi+1].Stocks,errors="coerce")
  if ((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any():continue
  cand.append(dict(stock_code=r.stock_code,signal_date=r.signal_date,entry_date=ent.Date,exit_date=ex.Date,mcap=float(r.mcap),op_q=float(r.op_q),prior_op_q=float(r.prior_op_q),signal_strength=float(r.op_yoy_pct),profit_growth=((float(r.op_q)-float(r.prior_op_q))/float(r.prior_op_q) if float(r.prior_op_q)>0 else np.nan),entry_open=float(ent.Open),exit_open=float(ex.Open)))
 c=pd.DataFrame(cand)
 def run(priority):
  x=c.copy()
  if priority=="small_mcap": x=x.sort_values(["entry_date","mcap","signal_date","stock_code"],ascending=[True,True,True,True])
  elif priority=="signal_strength": x=x.sort_values(["entry_date","signal_strength","mcap","signal_date","stock_code"],ascending=[True,False,True,True,True])
  else:
   x["_pg"]=x.profit_growth.fillna(-np.inf);x=x.sort_values(["entry_date","_pg","mcap","signal_date","stock_code"],ascending=[True,False,True,True,True])
  entries={d:g for d,g in x.groupby("entry_date")}
  dates=pd.DatetimeIndex(sorted(mk.Date.unique()));dates=dates[(dates>=x.entry_date.min())&(dates<=x.exit_date.max())]
  cash=1.;pos=[];tr=[];nr=[]
  def mark(p,d,col):
   z=by[p["stock_code"]];q=z[z.Date.eq(d)]
   if not q.empty and float(q.iloc[0][col])>0:return float(q.iloc[0][col])
   q=z[(z.Date<d)&(z.Date>=p["entry_date"])]
   return float(q.iloc[-1].Close) if not q.empty else p["entry_open"]
  for d in dates:
   keep=[]
   for p in pos:
    if p["exit_date"]==d:
     proceeds=p["shares"]*p["exit_open"]*(1-SELL);cash+=proceeds;p["net_return"]=proceeds/p["cash_spent"]-1;tr.append(p)
    else:keep.append(p)
   pos=keep
   nav_open=cash+sum(p["shares"]*mark(p,d,"Open") for p in pos);target=W*nav_open
   if d in entries:
    free=SLOTS-len(pos)
    for j,r in enumerate(entries[d].itertuples(index=False)):
     if j>=free:continue
     gross=min(target,cash/(1+BUY))
     if gross<=0:continue
     p=r._asdict();p["allocation"]=gross;p["cash_spent"]=gross*(1+BUY);p["shares"]=gross/r.entry_open;cash-=p["cash_spent"];pos.append(p)
   nav=cash+sum(p["shares"]*mark(p,d,"Close") for p in pos);nr.append((d,nav,cash,len(pos)))
  n=pd.DataFrame(nr,columns=["date","nav","cash","active_slots"]);n["peak"]=n.nav.cummax();n["dd"]=n.nav/n.peak-1
  t=pd.DataFrame(tr);years=max((n.date.iloc[-1]-n.date.iloc[0]).days/365.25,1/365.25)
  return {"total_return":float(n.nav.iloc[-1]-1),"cagr":float(n.nav.iloc[-1]**(1/years)-1),"mdd":float(n.dd.min()),"entered":int(len(t)),"trade_mean":float(t.net_return.mean()),"trade_median":float(t.net_return.median()),"win_rate":float((t.net_return>0).mean()),"avg_active_slots":float(n.active_slots.mean()),"avg_cash_fraction":float((n.cash/n.nav).mean())}
 results={p:run(p) for p in ["small_mcap","signal_strength","profit_growth"]}
 summary={"definition":"Same frozen V2 candidates and dynamic NAV 5% sizing; only same-entry-day capacity priority differs.","profit_growth_definition":"(current OP-prior OP)/prior OP only when prior OP>0; prior OP<=0 or missing ranks below valid growth rates. Tie-break: smaller mcap.","results":results}
 SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(summary,ensure_ascii=False,indent=2))
