#!/usr/bin/env python3
# Historical robustness test of the already-frozen V2 rule. No retuning.
from pathlib import Path
import json, math, time, requests
import numpy as np, pandas as pd
ACC=Path("korea_dart_quarterly_2016_2020_full.csv")
SEC=Path("korea_historical_security_universe_2015_2020.csv")
OUT=Path("korea_turnaround_v2_historical_2018_2020_events.csv")
SUM=Path("korea_turnaround_v2_historical_2018_2020_summary.json")
MARCAP="https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"
YH="https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA={"User-Agent":"Mozilla/5.0"}
THRESHOLD=5.0; MCAP_MAX=50e9; PEERS=20
QMAP={"Q1":"Q1","H1":"Q2","Q3":"Q3","FY":"Q4"}
def norm(v):
 s=str(v or "").replace(".0","").strip(); return s.zfill(6) if s else ""
def get_marcap(y):
 p=Path(f"marcap-{y}.parquet")
 if not p.exists():
  r=requests.get(MARCAP.format(year=y),headers=UA,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
 z=pd.read_parquet(p)
 if "Date" not in z:z=z.reset_index()
 z["Date"]=pd.to_datetime(z["Date"]);z["Code"]=z["Code"].map(norm)
 return z[z.Market.isin(["KOSPI","KOSDAQ"])].sort_values(["Code","Date"]).reset_index(drop=True)
def yahoo(sym):
 params={"period1":int(pd.Timestamp("2017-12-01",tz="UTC").timestamp()),"period2":int(pd.Timestamp("2021-03-01",tz="UTC").timestamp()),"interval":"1d","events":"history","includeAdjustedClose":"true"}
 for k in range(5):
  r=requests.get(YH.format(sym=sym),params=params,headers=UA,timeout=60)
  if r.ok:
   js=r.json();res=(js.get("chart") or {}).get("result")
   if res:
    q=res[0];ts=q.get("timestamp") or [];quote=((q.get("indicators") or {}).get("quote") or [{}])[0]
    d=pd.DataFrame({"Date":pd.to_datetime(ts,unit="s",utc=True).tz_convert("Asia/Seoul").tz_localize(None).normalize(),"Open":quote.get("open",[]),"Close":quote.get("close",[])})
    return d.dropna().drop_duplicates("Date").sort_values("Date").reset_index(drop=True)
  time.sleep(2*(k+1))
 raise RuntimeError(sym)
def stats(g,col):
 s=pd.to_numeric(g[col],errors="coerce").dropna()
 if s.empty:return {"n":0}
 return {"n":int(len(s)),"median":float(s.median()),"mean":float(s.mean()),"win_rate":float((s>0).mean()),"p25":float(s.quantile(.25)),"p75":float(s.quantile(.75))}
def signal_map():
 fs=sorted(Path("universe").rglob("korea_dart_historical_universe_20??.csv"))
 frames=[]
 for f in fs:
  u=pd.read_csv(f,dtype=str).fillna("")
  if "is_earliest_corp_period" in u:u=u[u.is_earliest_corp_period.str.lower().eq("true")]
  u["corp_code"]=u.corp_code.astype(str).str.zfill(8);u["business_year"]=pd.to_numeric(u.target_year,errors="coerce");u["fiscal_quarter"]=u.period.map(QMAP);u["signal_date"]=pd.to_datetime(u.rcept_dt,format="%Y%m%d",errors="coerce")
  u=u[u.signal_date.between(pd.Timestamp("2018-01-01"),pd.Timestamp("2020-12-31"))]
  frames.append(u[["corp_code","business_year","fiscal_quarter","stock_code","signal_date"]])
 return pd.concat(frames,ignore_index=True).sort_values(["corp_code","business_year","fiscal_quarter","signal_date"]).drop_duplicates(["corp_code","business_year","fiscal_quarter"])
def main():
 a=pd.read_csv(ACC,dtype={"corp_code":str},low_memory=False);a.corp_code=a.corp_code.astype(str).str.zfill(8);a["business_year"]=pd.to_numeric(a.business_year,errors="coerce")
 a=a[a.business_year.between(2017,2020)].sort_values(["corp_code","business_year","fiscal_quarter"]).drop_duplicates(["corp_code","business_year","fiscal_quarter"],keep="last")
 prev=a[["corp_code","business_year","fiscal_quarter","statement_basis","operating_profit_q"]].copy();prev.business_year+=1;prev=prev.rename(columns={"statement_basis":"prior_basis","operating_profit_q":"prior_op_q"})
 x=a.merge(prev,on=["corp_code","business_year","fiscal_quarter"],how="left");x=x[x.statement_basis.fillna("").ne("") & x.statement_basis.eq(x.prior_basis)].merge(signal_map(),on=["corp_code","business_year","fiscal_quarter"],how="inner")
 mk={y:get_marcap(y) for y in range(2017,2022)};by={}
 for z in mk.values():
  for c,g in z.groupby("Code",sort=False):by.setdefault(c,[]).append(g)
 by={c:pd.concat(gs).sort_values("Date").drop_duplicates("Date").reset_index(drop=True) for c,gs in by.items()}
 idx={"KOSPI":yahoo("%5EKS11"),"KOSDAQ":yahoo("%5EKQ11")};rows=[];drops={}
 def dr(k):drops[k]=drops.get(k,0)+1
 for r in x.itertuples(index=False):
  code=norm(r.stock_code);sd=pd.Timestamp(r.signal_date);z=by.get(code)
  if z is None:dr("no_market");continue
  pre=z[z.Date<sd]
  if pre.empty:dr("no_pre_market");continue
  mc=float(pre.iloc[-1].Marcap);mkt=str(pre.iloc[-1].Market);op=pd.to_numeric(pd.Series([r.operating_profit_q]),errors="coerce").iloc[0];pop=pd.to_numeric(pd.Series([r.prior_op_q]),errors="coerce").iloc[0]
  if pd.isna(op) or pd.isna(pop):dr("missing_op");continue
  opy=(op-pop)/mc*100
  if mc>MCAP_MAX or opy<THRESHOLD:dr("frozen_rule_fail");continue
  elig=z[(z.Date>sd)&(pd.to_numeric(z.Open,errors="coerce")>0)&(pd.to_numeric(z.Volume,errors="coerce")>0)]
  if elig.empty:dr("no_entry");continue
  e=elig.iloc[0];ei=int(e.name);j=ei+19
  if j>=len(z):dr("r20_unmatured");continue
  end=z.iloc[j];path=z.iloc[ei:j+1];sh=pd.to_numeric(path.Stocks,errors="coerce")
  if bool(((sh/sh.shift(1)-1).abs()>0.20).fillna(False).any()):dr("corporate_action");continue
  R20=(float(end.Close)/float(e.Open)-1)*100;b=idx[mkt];be=b[b.Date.eq(pd.Timestamp(e.Date))];bx=b[b.Date.eq(pd.Timestamp(end.Date))]
  if be.empty or bx.empty:dr("benchmark_missing");continue
  br=(float(bx.iloc[0].Close)/float(be.iloc[0].Open)-1)*100
  allz=pd.concat([mk.get(sd.year-1,pd.DataFrame()),mk.get(sd.year,pd.DataFrame())],ignore_index=True);ppre=allz[allz.Date<sd].sort_values("Date").groupby("Code",as_index=False).tail(1);ppre=ppre[(ppre.Market==mkt)&(ppre.Code!=code)&(pd.to_numeric(ppre.Marcap,errors="coerce")>0)].copy();ppre["dist"]=(np.log(pd.to_numeric(ppre.Marcap,errors="coerce"))-math.log(mc)).abs();ppre=ppre.nsmallest(100,"dist")
  prs=[]
  for pr in ppre.itertuples(index=False):
   pz=by.get(norm(pr.Code))
   if pz is None:continue
   pe=pz[pz.Date.eq(pd.Timestamp(e.Date))];px=pz[pz.Date.eq(pd.Timestamp(end.Date))]
   if pe.empty or px.empty:continue
   pe=pe.iloc[0];px=px.iloc[0]
   if float(pe.Open)<=0 or float(pe.Volume)<=0:continue
   ppath=pz[(pz.Date>=pd.Timestamp(e.Date))&(pz.Date<=pd.Timestamp(end.Date))];psh=pd.to_numeric(ppath.Stocks,errors="coerce")
   if bool(((psh/psh.shift(1)-1).abs()>0.20).fillna(False).any()):continue
   rr=(float(px.Close)/float(pe.Open)-1)*100
   if np.isfinite(rr):prs.append(rr)
   if len(prs)>=PEERS:break
  peer=float(np.median(prs)) if len(prs)>=10 else np.nan
  rows.append({"corp_code":r.corp_code,"stock_code":code,"market":mkt,"signal_date":sd.date().isoformat(),"signal_year":sd.year,"entry_date":pd.Timestamp(e.Date).date().isoformat(),"exit_date":pd.Timestamp(end.Date).date().isoformat(),"mcap":mc,"op_q":op,"prior_op_q":pop,"op_yoy_pct":opy,"R20":R20,"benchmark_R20":br,"market_excess_R20":R20-br,"matched_peer_n":len(prs),"matched_peer_median_R20":peer,"matched_excess_R20":R20-peer if np.isfinite(peer) else np.nan})
 out=pd.DataFrame(rows);out.to_csv(OUT,index=False);fam={"all":{"absolute":stats(out,"R20"),"market_excess":stats(out,"market_excess_R20"),"matched_excess":stats(out,"matched_excess_R20")}}
 for y in [2018,2019,2020]:
  g=out[out.signal_year==y];fam[str(y)]={"absolute":stats(g,"R20"),"market_excess":stats(g,"market_excess_R20"),"matched_excess":stats(g,"matched_excess_R20")}
 def passed(v):return v["absolute"].get("n",0)>0 and v["absolute"].get("median",-1)>0 and v["absolute"].get("win_rate",0)>.5 and v["market_excess"].get("median",-1)>0 and v["matched_excess"].get("median",-1)>0
 overall=passed(fam["all"]);years=sum(passed(fam[str(y)]) for y in [2018,2019,2020]);n=fam["all"]["absolute"].get("n",0)
 verdict="PASS" if overall and years>=2 and n>=30 else ("WEAK_PASS" if overall and years>=1 and n>=15 else "FAIL")
 summary={"test_type":"historical robustness; not independent OOS","frozen_lock_commit":"2a74fa7d9344cbf8c7c9cf8337d9cdf97a965eca","rule":"unchanged frozen V2: PIT mcap<=50B KRW; pure-quarter OP YoY improvement/PIT mcap>=5%; next tradable open; R20; >20% share-count CA excluded","signal_window":"2018-01-01..2020-12-31","eligible_clean_events":int(len(out)),"drop_reasons":drops,"results":fam,"verdict":verdict,"verdict_note":"PASS requires overall criteria, >=2 of 3 years individually positive on all primary metrics, and n>=30; WEAK_PASS requires overall criteria, >=1 year, n>=15. No strategy parameters were changed."}
 SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
