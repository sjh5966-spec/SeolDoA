#!/usr/bin/env python3
"""Development-only bridge from candidate DART signal content to historical marcap execution data.
Uses only 2015-2020. The candidate signal remains provisional until content precedence is frozen.
Raw prices are unadjusted; any material shares-outstanding change in the holding window is flagged.
"""
from pathlib import Path
import json, requests
import pandas as pd

SIG=Path('korea_candidate_signal_probe_v1.json')
SEC=Path('korea_historical_security_universe_2015_2020.csv')
OUT=Path('korea_market_event_probe_v1.csv')
SUM=Path('korea_market_event_probe_v1_summary.json')
BASE='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'

def code_for(sec,corp,year):
    x=sec[(sec.corp_code.astype(str).str.zfill(8)==corp)&(sec.fiscal_year.astype(int)==year)].copy()
    for c in ('stock_code','matched_stock_code','Code','code'):
        if c in x.columns:
            z=x[c].fillna('').astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
            z=z[z.str.fullmatch(r'\d{6}')]
            if len(z): return z.iloc[0]
    return ''

def main():
    obj=json.loads(SIG.read_text(encoding='utf-8'));sec=pd.read_csv(SEC,dtype=str).fillna('')
    rows=[]; cache={}
    for d in obj.get('detail',[]):
        sig=d.get('earliest_op_label_candidate')
        if not sig or not sig.get('exact_amount_match'): continue
        y=int(d['business_year'])
        if not 2015<=y<=2020: raise RuntimeError('OOS guard')
        corp=str(d['corp_code']).zfill(8); code=code_for(sec,corp,y)
        if not code:
            rows.append({'corp_code':corp,'year':y,'quarter':d['fiscal_quarter'],'status':'NO_SECURITY_CODE'});continue
        if y not in cache:
            p=Path(f'marcap-{y}.parquet')
            if not p.exists():
                r=requests.get(BASE.format(year=y),timeout=180);r.raise_for_status();p.write_bytes(r.content)
            m=pd.read_parquet(p);m['Date']=pd.to_datetime(m['Date']);m['Code']=m.Code.astype(str).str.zfill(6);cache[y]=m
        m=cache[y]; sdate=pd.to_datetime(str(sig['rcept_dt']),format='%Y%m%d')
        z=m[(m.Code==code)&(m.Market.isin(['KOSPI','KOSDAQ']))].sort_values('Date').reset_index(drop=True)
        eligible=z[(z.Date>sdate)&(z.Open>0)&(z.Volume>0)&(z.Amount>0)]
        if eligible.empty:
            rows.append({'corp_code':corp,'stock_code':code,'year':y,'quarter':d['fiscal_quarter'],'signal_date':sdate.date(),'status':'NO_NEXT_TRADABLE_OPEN'});continue
        e=eligible.iloc[0]; idx=int(z.index[z.Date.eq(e.Date)][0]); hist=z.iloc[max(0,idx-20):idx]
        adv20=float(hist.Amount.mean()) if len(hist)>=20 else None
        horizons={}
        for h in (5,10,20,60,120):
            j=idx+h-1
            horizons[f'R{h}']=((float(z.iloc[j].Close)/float(e.Open)-1)*100) if j<len(z) and float(e.Open)>0 else None
        j=min(len(z)-1,idx+119); path=z.iloc[idx:j+1]
        stock_ratio=(path.Stocks.astype(float)/path.Stocks.astype(float).shift(1)-1).abs()
        corp_action=bool((stock_ratio>0.20).fillna(False).any())
        rows.append({'corp_code':corp,'company_name':d.get('company_name',''),'stock_code':code,'year':y,'quarter':d['fiscal_quarter'],'signal_date':sdate.date(),'signal_receipt_no':sig['rcept_no'],'signal_report_name':sig['report_nm'],'entry_date':e.Date.date(),'entry_open':float(e.Open),'pit_mcap_entry_day':float(e.Marcap),'adv20_amount':adv20,'adv20_complete':len(hist)>=20,'market':e.Market,'holding_path_shares_change_gt20pct':corp_action,'status':'PROVISIONAL_MARKET_BRIDGE',**horizons})
    o=pd.DataFrame(rows);o.to_csv(OUT,index=False)
    s={'development_only':True,'modern_oos_protected':True,'rows':len(o),'market_bridge_rows':int((o.status=='PROVISIONAL_MARKET_BRIDGE').sum()) if len(o) else 0,'corp_action_flagged':int(o.get('holding_path_shares_change_gt20pct',pd.Series(dtype=bool)).fillna(False).sum()) if len(o) else 0,'note':'Returns are provisional QC only. Signal precedence is not frozen and raw-price holding windows with material shares changes require corporate-action handling before research use.'}
    SUM.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False,indent=2));print(o.to_string(index=False))
if __name__=='__main__': main()
