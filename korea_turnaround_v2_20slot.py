#!/usr/bin/env python3
from pathlib import Path
import json,requests,numpy as np,pandas as pd
INP=Path("korea_turnaround_v2_historical_2018_2020_events.csv"); OUT=Path("korea_turnaround_v2_20slot_dynamic_trades.csv"); NAV=Path("korea_turnaround_v2_20slot_dynamic_nav.csv"); SUM=Path("korea_turnaround_v2_20slot_dynamic_summary.json")
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
  cand.append(dict(stock_code=r.stock_code,signal_date=r.signal_date,entry_date=ent.Date,exit_date=ex.Date,mcap=float(r.mcap),entry_open=float(ent.Open),exit_open=float(ex.Open)))
 c=pd.DataFrame(cand).sort_values(["entry_date","mcap","signal_date","stock_code"]).reset_index(drop=True)
 entries={d:g for d,g in c.groupby("entry_date")}
 dates=pd.DatetimeIndex(sorted(mk.Date.unique()));dates=dates[(dates>=c.entry_date.min())&(dates<=c.exit_date.max())]
 cash=1.0;pos=[];trades=[];navrows=[]
 def mark(p,d,col="Close"):
  z=by[p["stock_code"]];q=z[z.Date.eq(d)]
  if not q.empty and float(q.iloc[0][col])>0:return float(q.iloc[0][col])
  q=z[(z.Date<d)&(z.Date>=p["entry_date"])]
  return float(q.iloc[-1].Close) if not q.empty else p["entry_open"]
 for d in dates:
  # sell first; proceeds available for same-open entries
  keep=[]
  for p in pos:
   if p["exit_date"]==d:
    proceeds=p["shares"]*p["exit_open"]*(1-SELL);cash+=proceeds;p["proceeds"]=proceeds;p["net_return"]=proceeds/p["cash_spent"]-1;p["status"]="entered";trades.append(p)
   else:keep.append(p)
  pos=keep
  # one NAV snapshot at this open; every same-day new position gets identical 5% target
  nav_open=cash+sum(p["shares"]*mark(p,d,"Open") for p in pos)
  target=W*nav_open
  if d in entries:
   free=SLOTS-len(pos)
   for j,r in enumerate(entries[d].itertuples(index=False)):
    rec=r._asdict()
    if j>=free:
     rec.update(status="capacity_rejected",allocation=np.nan,shares=np.nan,cash_spent=np.nan,net_return=np.nan);trades.append(rec);continue
    # allocation is gross stock notional; fee is additional cash. If cash is tight, scale to available cash without leverage.
    gross=min(target,cash/(1+BUY))
    if gross<=0:
     rec.update(status="cash_rejected",allocation=0,shares=0,cash_spent=0,net_return=np.nan);trades.append(rec);continue
    spent=gross*(1+BUY);shares=gross/r.entry_open;cash-=spent
    rec.update(allocation=gross,shares=shares,cash_spent=spent)
    pos.append(rec)
  close_value=sum(p["shares"]*mark(p,d,"Close") for p in pos); nav=cash+close_value
  navrows.append(dict(date=d,nav=nav,cash=cash,active_slots=len(pos),cash_fraction=cash/nav if nav else np.nan))
 # safety: all should be exited by final date
 t=pd.DataFrame(trades);t.to_csv(OUT,index=False)
 n=pd.DataFrame(navrows);n["peak"]=n.nav.cummax();n["drawdown"]=n.nav/n.peak-1;n.to_csv(NAV,index=False)
 entered=t[t.status.eq("entered")];rej=t[t.status.eq("capacity_rejected")].copy()
 if len(rej): rejnet=(1-BUY)*(rej.exit_open/rej.entry_open)*(1-SELL)-1
 years=max((n.date.iloc[-1]-n.date.iloc[0]).days/365.25,1/365.25); cagr=(n.nav.iloc[-1]/1.0)**(1/years)-1
 annual={}
 prev=1.0
 for y,g in n.groupby(n.date.dt.year):
  end=float(g.nav.iloc[-1]);annual[str(y)]=end/prev-1;prev=end
 counts={"zero":int((n.active_slots==0).sum()),"partial_1_19":int(n.active_slots.between(1,19).sum()),"full_20":int((n.active_slots==20).sum())}
 summary={"test":"20-slot dynamic NAV 5% sizing","definition":"At each entry open, after same-open exits, compute current total NAV once; each same-day accepted signal gets 5% of that NAV.",
  "costs":{"buy":BUY,"sell":SELL},"candidates":int(len(c)),"entered":int(len(entered)),"capacity_rejected":int(len(rej)),
  "total_return":float(n.nav.iloc[-1]-1),"cagr":float(cagr),"mdd":float(n.drawdown.min()),"annual_returns":annual,
  "entered_net_mean":float(entered.net_return.mean()),"entered_net_median":float(entered.net_return.median()),"entered_win_rate":float((entered.net_return>0).mean()),
  "rejected_hypothetical_net_mean":float(rejnet.mean()) if len(rej) else None,"rejected_hypothetical_net_median":float(rejnet.median()) if len(rej) else None,
  "average_active_slots":float(n.active_slots.mean()),"average_cash_fraction":float(n.cash_fraction.mean()),"holding_day_counts":counts,
  "holding_day_ratios":{k:v/len(n) for k,v in counts.items()},"trading_days":int(len(n))}
 SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
