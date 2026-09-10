#!/usr/bin/env python3
from __future__ import annotations
import io, json, os, re, time, zipfile
from pathlib import Path
from collections import Counter
import numpy as np
import pandas as pd
import requests

QFILE=Path('korea_dart_quarterly_2016_2020_full.csv')
SEC=Path('korea_historical_security_universe_2015_2020.csv')
OUT=Path('korea_2019_development_base_a_events_v1.csv')
SUM=Path('korea_2019_development_analysis_v1_summary.json')
API='https://opendart.fss.or.kr/api'
MARCAP='https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
QORD={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
PERIOD_TOKEN={'Q1':('분기보고서','2019.03'),'Q2':('반기보고서','2019.06'),'Q3':('분기보고서','2019.09'),'Q4':('사업보고서','2019.12')}
DATES={'Q1':('20190101','20190630'),'Q2':('20190401','20190930'),'Q3':('20190701','20191231'),'Q4':('20191001','20200430')}
PRELIM_HINTS=('잠정','매출액또는손익구조','영업(잠정)','영업(잠정)실적')

def getj(s,key,path,**params):
    for a in range(5):
        r=s.get(f'{API}/{path}',params={'crtfc_key':key,**params},timeout=60)
        r.raise_for_status(); d=r.json(); st=str(d.get('status',''))
        if st in ('000','013'): return d
        if st=='020': time.sleep(3*(a+1)); continue
        return d
    return {'status':'020_retry_exhausted','list':[]}

def text_bytes(b):
    for e in ('utf-8','cp949','euc-kr'):
        try:return b.decode(e)
        except:pass
    return b.decode('utf-8','replace')

def normdigits(s): return re.sub(r'[^0-9]','',s)

def prelim_match(s,key,rno,target):
    try:
        r=s.get(f'{API}/document.xml',params={'crtfc_key':key,'rcept_no':rno},timeout=120)
        if r.content[:2]!=b'PK': return False,'NONZIP'
        vals=[]; a=abs(float(target))
        for scale in (1,1e3,1e6,1e8):
            v=int(round(a/scale)); ds=str(v)
            if len(ds)>=3: vals.append(ds)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            for n in zf.namelist():
                if not n.lower().endswith(('.xml','.html','.htm','.txt')): continue
                try:t=text_bytes(zf.read(n))
                except:continue
                plain=re.sub(r'<[^>]+>',' ',t); plain=re.sub(r'\s+',' ',plain)
                for lab in ('영업이익','영업손실','영업손익'):
                    start=0
                    while True:
                        p=plain.find(lab,start)
                        if p<0: break
                        sn=plain[max(0,p-300):p+900]
                        dg=normdigits(sn)
                        if any(v in dg for v in vals): return True,'OP_LABEL_SCALED_AMOUNT_NEARBY'
                        start=p+len(lab)
        return False,'NO_NEAR_AMOUNT'
    except Exception as e:
        return False,'ERR_'+type(e).__name__

def build_accounting():
    d=pd.read_csv(QFILE,dtype={'corp_code':str},low_memory=False)
    d=d[d.business_year.astype(int).between(2018,2019)].copy()
    d['corp_code']=d.corp_code.astype(str).str.zfill(8);d['qord']=d.fiscal_quarter.map(QORD)
    d['seq']=d.business_year.astype(int)*4+d.qord.astype(int)
    d=d.sort_values(['corp_code','seq']).drop_duplicates(['corp_code','business_year','fiscal_quarter'],keep='last')
    key={(r.corp_code,int(r.business_year),r.fiscal_quarter):r for r in d.itertuples(index=False)}
    byseq={(r.corp_code,int(r.seq)):r for r in d.itertuples(index=False)}
    rows=[]
    for r in d[d.business_year.astype(int).eq(2019)].itertuples(index=False):
        py=key.get((r.corp_code,2018,r.fiscal_quarter)); seq=int(r.seq)
        four=[byseq.get((r.corp_code,s)) for s in range(seq-3,seq+1)]
        exact=all(x is not None for x in four)
        bases=[str(getattr(x,'statement_basis','') or '') for x in four] if exact else []
        same=bool(exact and bases and len(set(bases))==1 and bases[0])
        nis=[getattr(x,'net_income_q',np.nan) if x is not None else np.nan for x in four]
        valid=bool(same and all(pd.notna(x) for x in nis)); ni_ttm=float(sum(nis)) if valid else np.nan
        op=r.operating_profit_q; pop=getattr(py,'operating_profit_q',np.nan) if py is not None else np.nan
        eq=r.equity_q_end; fcf=r.fcf_q; pfcf=getattr(py,'fcf_q',np.nan) if py is not None else np.nan
        turn=bool(pd.notna(op) and pd.notna(pop) and op>0 and pop<=0)
        base=bool(turn and pd.notna(ni_ttm) and ni_ttm<0 and pd.notna(eq) and eq>0)
        if base:
            rows.append({'corp_code':r.corp_code,'company_name':r.company_name,'business_year':2019,'fiscal_quarter':r.fiscal_quarter,'statement_basis':r.statement_basis,'operating_profit_q':op,'prior_year_same_q_operating_profit':pop,'net_income_ttm':ni_ttm,'equity_q_end':eq,'fcf_q':fcf,'prior_year_same_q_fcf':pfcf,'fcf_yoy_improvement':(fcf-pfcf if pd.notna(fcf) and pd.notna(pfcf) else np.nan)})
    return pd.DataFrame(rows), {'2019_rows':int((d.business_year.astype(int)==2019).sum()),'2019_corps':int(d.loc[d.business_year.astype(int)==2019,'corp_code'].nunique())}

def add_security(x):
    sec=pd.read_csv(SEC,dtype=str).fillna('')
    fy='fiscal_year' if 'fiscal_year' in sec.columns else ('year' if 'year' in sec.columns else None)
    if fy: sec=sec[pd.to_numeric(sec[fy],errors='coerce').eq(2019)]
    sec['corp_code']=sec.corp_code.astype(str).str.zfill(8)
    codecol=next((c for c in ('matched_stock_code','stock_code','Code','code') if c in sec.columns),None)
    statuscol=next((c for c in ('status','security_status','match_status') if c in sec.columns),None)
    keep=['corp_code']+[c for c in (codecol,statuscol,'market_observed','market','name_match_flag','exclusion_flags') if c and c in sec.columns]
    sec=sec[keep].drop_duplicates('corp_code')
    o=x.merge(sec,on='corp_code',how='left')
    o['stock_code']=o[codecol].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6) if codecol else ''
    o['security_status']=o[statuscol] if statuscol else ''
    return o

def add_signals(x,key):
    s=requests.Session();s.headers.update({'User-Agent':'SeolDoA-2019-Development/1.0'})
    out=[]; ctr=Counter()
    for i,r in enumerate(x.itertuples(index=False),1):
        q=r.fiscal_quarter;b,e=DATES[q]
        lj=getj(s,key,'list.json',corp_code=r.corp_code,bgn_de=b,end_de=e,page_count='100')
        items=sorted(lj.get('list') or [],key=lambda z:(str(z.get('rcept_dt','')),str(z.get('rcept_no',''))))
        tok=PERIOD_TOKEN[q]
        periodic=[z for z in items if tok[0] in str(z.get('report_nm','')) and tok[1] in str(z.get('report_nm',''))]
        per=periodic[0] if periodic else None
        prelim=[z for z in items if any(h in str(z.get('report_nm','')) for h in PRELIM_HINTS)]
        high=[]
        for z in prelim[:12]:
            if per and str(z.get('rcept_dt',''))>=str(per.get('rcept_dt','')): continue
            ok,why=prelim_match(s,key,str(z.get('rcept_no','')),r.operating_profit_q); ctr['prelim_docs_checked']+=1
            if ok: high.append((z,why)); break
        chosen=high[0][0] if high else per
        d=r._asdict();d.update({'list_status':lj.get('status'),'periodic_receipt_date':str(per.get('rcept_dt','')) if per else '','periodic_receipt_no':str(per.get('rcept_no','')) if per else '','periodic_report_name':str(per.get('report_nm','')) if per else '','prelim_high_confidence':bool(high),'signal_date':str(chosen.get('rcept_dt','')) if chosen else '','signal_receipt_no':str(chosen.get('rcept_no','')) if chosen else '','signal_report_name':str(chosen.get('report_nm','')) if chosen else '','signal_quality':'PRELIM_HIGH_CONFIDENCE' if high else ('PERIODIC_FALLBACK' if per else 'NO_SIGNAL')})
        ctr[d['signal_quality']]+=1;out.append(d)
        if i%25==0: print('signals',i,'/',len(x),dict(ctr),flush=True)
    return pd.DataFrame(out),dict(ctr)

def load_marcap():
    fs=[]
    for y in (2019,2020):
        p=Path(f'marcap-{y}.parquet')
        if not p.exists():
            rr=requests.get(MARCAP.format(year=y),timeout=180);rr.raise_for_status();p.write_bytes(rr.content)
        d=pd.read_parquet(p);d['Date']=pd.to_datetime(d.Date);d['Code']=d.Code.astype(str).str.zfill(6);fs.append(d)
    return pd.concat(fs,ignore_index=True).sort_values(['Code','Date'])

def add_market(x):
    m=load_marcap(); out=[]
    for r in x.itertuples(index=False):
        d=r._asdict(); code=str(getattr(r,'stock_code','')).zfill(6); sig=str(getattr(r,'signal_date',''))
        if not re.fullmatch(r'\d{6}',code) or not sig:
            d['market_status']='NO_CODE_OR_SIGNAL';out.append(d);continue
        sd=pd.to_datetime(sig,format='%Y%m%d',errors='coerce')
        z=m[(m.Code==code)&(m.Market.isin(['KOSPI','KOSDAQ']))].sort_values('Date').reset_index(drop=True)
        if z.empty or pd.isna(sd): d['market_status']='NO_MARKET_SERIES';out.append(d);continue
        pre=z[z.Date<sd]
        d['pit_mcap_pre_signal']=float(pre.iloc[-1].Marcap) if len(pre) else np.nan
        d['pit_mcap_date']=pre.iloc[-1].Date.date().isoformat() if len(pre) else ''
        elig=z[(z.Date>sd)&(z.Open>0)&(z.Volume>0)&(z.Amount>0)]
        if elig.empty: d['market_status']='NO_NEXT_TRADABLE_OPEN';out.append(d);continue
        e=elig.iloc[0]; idx=int(z.index[z.Date.eq(e.Date)][0]); hist=z.iloc[max(0,idx-20):idx]
        d.update({'entry_date':e.Date.date().isoformat(),'entry_open':float(e.Open),'entry_delay_calendar_days':int((e.Date-sd).days),'market':str(e.Market),'adv20_amount':float(hist.Amount.mean()) if len(hist)==20 else np.nan,'adv20_complete':len(hist)==20,'market_status':'OK'})
        for h in (5,10,20,60,120):
            j=idx+h-1
            ret=np.nan; ca=np.nan
            if j<len(z):
                path=z.iloc[max(0,idx-1):j+1]
                ratios=(pd.to_numeric(path.Stocks,errors='coerce')/pd.to_numeric(path.Stocks,errors='coerce').shift(1)-1).abs()
                ca=bool((ratios>0.20).fillna(False).any())
                ret=(float(z.iloc[j].Close)/float(e.Open)-1)*100 if float(e.Open)>0 else np.nan
            d[f'R{h}_raw']=ret;d[f'CA_R{h}']=ca;d[f'R{h}_clean']=ret if pd.notna(ret) and ca is False else np.nan
        j=idx+19
        if j<len(z) and d.get('CA_R20') is False:
            pth=z.iloc[idx:j+1]
            d['MFE20']=((float(pth.High.max())/float(e.Open))-1)*100
            d['MAE20']=((float(pth.Low.min())/float(e.Open))-1)*100
        else:d['MFE20']=np.nan;d['MAE20']=np.nan
        mc=d.get('pit_mcap_pre_signal',np.nan)
        d['fcf_to_mcap']=float(r.fcf_q)/mc if pd.notna(getattr(r,'fcf_q',np.nan)) and pd.notna(mc) and mc>0 else np.nan
        d['fcf_yoy_improvement_to_mcap']=float(r.fcf_yoy_improvement)/mc if pd.notna(getattr(r,'fcf_yoy_improvement',np.nan)) and pd.notna(mc) and mc>0 else np.nan
        d['abs_ttm_loss_to_mcap']=abs(float(r.net_income_ttm))/mc if pd.notna(mc) and mc>0 else np.nan
        out.append(d)
    return pd.DataFrame(out)

def stats(s):
    s=pd.to_numeric(s,errors='coerce').dropna()
    if not len(s):return {'n':0}
    return {'n':int(len(s)),'mean':float(s.mean()),'median':float(s.median()),'p10':float(s.quantile(.1)),'p25':float(s.quantile(.25)),'p75':float(s.quantile(.75)),'p90':float(s.quantile(.9)),'win_rate':float((s>0).mean()),'ge20':float((s>=20).mean()),'le_m20':float((s<=-20).mean())}

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY required')
    x,acct=build_accounting(); print('accounting Base A',len(x),flush=True)
    x=add_security(x);x,sig=add_signals(x,key);x=add_market(x)
    x.to_csv(OUT,index=False)
    clean=x['R20_clean'] if 'R20_clean' in x else pd.Series(dtype=float)
    mc=pd.to_numeric(x.get('pit_mcap_pre_signal'),errors='coerce').dropna()
    summary={'research_stage':'2019_development_complete_year_provisional_signal_market_analysis','development_only':True,'modern_oos_protected':True,**acct,'accounting_base_a':int(len(x)),'security_code_available':int(x.stock_code.str.fullmatch(r'\d{6}').sum()) if 'stock_code' in x else 0,'signal_counts':sig,'market_ok':int((x.get('market_status')=='OK').sum()),'r20_clean_stats':stats(clean),'mcap_krw':{'n':int(len(mc)),'p10':float(mc.quantile(.1)) if len(mc) else None,'p25':float(mc.quantile(.25)) if len(mc) else None,'median':float(mc.median()) if len(mc) else None,'p75':float(mc.quantile(.75)) if len(mc) else None,'p90':float(mc.quantile(.9)) if len(mc) else None},'fcf_to_mcap_stats':stats(x.get('fcf_to_mcap',pd.Series(dtype=float))*100),'fcf_yoy_improvement_to_mcap_stats':stats(x.get('fcf_yoy_improvement_to_mcap',pd.Series(dtype=float))*100),'abs_ttm_loss_to_mcap_stats':stats(x.get('abs_ttm_loss_to_mcap',pd.Series(dtype=float))*100),'corporate_action_r20':int(pd.Series(x.get('CA_R20')).fillna(False).astype(bool).sum()) if len(x) else 0,'important_limitation':'2019 is a complete accounting Development year. Signal date uses earliest high-confidence preliminary disclosure only when operating-profit scaled amount is found near the label; otherwise exact periodic-report receipt fallback. Threshold selection must wait for multi-year Development completion; 2023+ OOS untouched.'}
    SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
