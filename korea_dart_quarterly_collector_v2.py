#!/usr/bin/env python3
"""Development-only OpenDART quarterly accounting collector v2.1.

Key rules:
- 2016-2020 only. 2015 is handled by receipt-specific XBRL because the full-financial API lacks reliable 2015 quarterly coverage.
- Prefer the reconstructed historical DART corp-year seed; retain the old smoke seed only as a fallback.
- Q1 direct; Q2=H1-Q1; Q3=9M-H1; Q4=FY-9M.
- Same statement basis required across the immediate predecessor.
- CFS preferred; OFS fallback only when CFS is unavailable. No silent cross-basis differencing.
- CAPEX sums distinct PPE/intangible acquisition rows, normalizes cumulative cash spending positive before differencing,
  and rejects negative normalized quarter deltas instead of absolute-valuing them.
- Missing CAPEX acquisition rows remain missing; they are not silently interpreted as zero.
- No trading signal dates, KRX prices, returns, or 2021+/2023+ OOS data.
"""
from __future__ import annotations
import json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
import pandas as pd
import requests

BASE='https://opendart.fss.or.kr/api'
HISTORICAL_SEED=Path('korea_dart_historical_seed_2015_2020.csv')
SMOKE_SEED=Path('korea_dart_quarterly_seed_2015_2020.csv')
REPORTS=[('Q1','11013'),('Q2','11012'),('Q3','11014'),('Q4','11011')]
PREFERRED={
 'operating_profit':{'dart_OperatingIncomeLoss'},
 'net_income':{'ifrs_ProfitLoss'},
 'equity':{'ifrs_Equity'},
 'cfo':{'ifrs_CashFlowsFromUsedInOperatingActivities'},
 'capex_ppe':{'ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'},
 'capex_intangible':{'ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'},
}
FLOW={'operating_profit','net_income','cfo','capex_ppe','capex_intangible'}
CAPEX={'capex_ppe','capex_intangible'}

def num(x):
    if x is None or str(x).strip()=='': return None
    try: return float(str(x).replace(',','').replace('−','-'))
    except: return None

def norm(x): return re.sub(r'\s+','',str(x or ''))

def section(metric):
    if metric in {'operating_profit','net_income'}: return {'IS','CIS'}
    if metric=='equity': return {'BS'}
    return {'CF'}

def exact(metric,r):
    n=norm(r.get('account_nm')); s=str(r.get('sj_div') or '')
    if metric=='operating_profit': return s in {'IS','CIS'} and n in {'영업이익','영업손실','영업이익(손실)','영업손익'}
    if metric=='net_income': return s in {'IS','CIS'} and n in {'당기순이익','당기순손실','당기순이익(손실)','분기순이익','분기순손실','분기순이익(손실)','반기순이익','반기순손실','반기순이익(손실)','연결당기순이익','연결당기순이익(손실)'}
    if metric=='equity': return s=='BS' and n in {'자본총계','자본의총계'}
    if metric=='cfo': return s=='CF' and n in {'영업활동현금흐름','영업활동으로인한현금흐름','영업활동으로부터의현금흐름','영업활동에서창출된현금흐름'}
    if metric=='capex_ppe': return s=='CF' and '유형자산' in n and ('취득' in n or '구입' in n)
    if metric=='capex_intangible': return s=='CF' and '무형자산' in n and ('취득' in n or '구입' in n)
    return False

def api(session,key,corp,year,report,basis):
    last=''
    for attempt in range(4):
        try:
            r=session.get(f'{BASE}/fnlttSinglAcntAll.json',params={'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':report,'fs_div':basis},timeout=60)
            r.raise_for_status(); d=r.json(); st=str(d.get('status',''))
            if st=='000': return d.get('list') or [],'ok'
            if st=='013': return [],'no_data'
            if st=='020': time.sleep(2*(attempt+1)); continue
            return d.get('list') or [],f'dart_status_{st}'
        except Exception as e:
            last=str(e); time.sleep(attempt+1)
    return [],f'request_error:{last}'

def flow_cumulative(row,metric,q):
    if row is None: return None,'missing'
    cur=num(row.get('thstrm_amount')); add=num(row.get('thstrm_add_amount')); sj=str(row.get('sj_div') or '')
    if metric=='equity': return cur,('instant_thstrm_amount' if cur is not None else 'missing')
    if q=='Q1':
        if cur is not None: return cur,'q1_thstrm_amount'
        if add is not None: return add,'q1_add_fallback'
        return None,'missing'
    if q in {'Q2','Q3'}:
        if add is not None: return add,'cumulative_thstrm_add_amount'
        if sj=='CF' and cur is not None: return cur,'cumulative_cf_thstrm_amount'
        return None,'cumulative_missing'
    if q=='Q4':
        if cur is not None: return cur,'fy_thstrm_amount'
        if add is not None: return add,'fy_add_fallback'
    return None,'missing'

def choose_single(items,metric):
    xs=[x for x in items if str(x.get('sj_div') or '') in section(metric)]
    std=[x for x in xs if str(x.get('account_id') or '') in PREFERRED[metric]]
    if len(std)==1: return std[0],'standard_id'
    if len(std)>1:
        ex=[x for x in std if exact(metric,x)]
        if len(ex)==1: return ex[0],'standard_id_exact_label'
        vals={num(x.get('thstrm_amount')) for x in std if num(x.get('thstrm_amount')) is not None}
        if len(vals)==1: return std[0],'standard_id_duplicate_same_value'
        return None,'ambiguous_standard_id'
    ex=[x for x in xs if exact(metric,x)]
    if len(ex)==1: return ex[0],'exact_label_fallback'
    if len(ex)>1:
        vals={num(x.get('thstrm_amount')) for x in ex if num(x.get('thstrm_amount')) is not None}
        if len(vals)==1: return ex[0],'exact_label_duplicate_same_value'
        return None,'ambiguous_exact_label'
    return None,'missing'

def capex_aggregate(items,metric,q):
    xs=[x for x in items if str(x.get('sj_div') or '')=='CF']
    std=[x for x in xs if str(x.get('account_id') or '') in PREFERRED[metric]]
    rows=std if std else [x for x in xs if exact(metric,x)]
    seen=set(); uniq=[]
    for x in rows:
        k=(str(x.get('account_id') or ''),norm(x.get('account_nm')),str(x.get('thstrm_amount') or ''),str(x.get('thstrm_add_amount') or ''))
        if k not in seen: seen.add(k); uniq.append(x)
    if not uniq: return None,'no_qualifying_rows_missing',0,[]
    vals=[]; audit=[]
    for x in uniq:
        v,m=flow_cumulative(x,metric,q)
        # Acquisition cash flows can be reported with either sign. Normalize cumulative spend first.
        spend=abs(v) if v is not None else None
        if spend is not None: vals.append(spend)
        audit.append({'account_id':x.get('account_id'),'account_nm':x.get('account_nm'),'raw_cumulative':v,'normalized_cumulative_spend':spend,'method':m})
    return (sum(vals) if vals else None),('standard_id_sum_normalized' if std else 'exact_label_sum_normalized'),len(uniq),audit

def main():
    key=os.environ.get('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY required')
    year=int(os.environ.get('DART_QUARTER_YEAR','2020')); chunk=int(os.environ.get('DART_QUARTER_CHUNK','0')); chunk_size=int(os.environ.get('DART_QUARTER_CHUNK_SIZE','20'))
    if year<2016 or year>2020: raise SystemExit('v2.1 supports 2016..2020 only; use the receipt-specific 2015 XBRL collector for 2015')
    seed_path=HISTORICAL_SEED if HISTORICAL_SEED.exists() else SMOKE_SEED
    if not seed_path.exists(): raise SystemExit('missing historical and smoke seed files')
    seed=pd.read_csv(seed_path,dtype=str).fillna('')
    seed=seed[seed.fiscal_year.astype(str).eq(str(year))].sort_values(['corp_code','receipt_no']).drop_duplicates(['corp_code','fiscal_year'],keep='first')
    part=seed.iloc[chunk*chunk_size:chunk*chunk_size+chunk_size]
    session=requests.Session(); session.headers.update({'User-Agent':'SeolDoA-Korea-DART-Quarterly/2.1'})
    status_counts=Counter(); rows=[]; basis_switch=0; negative_capex_delta=0
    for _,sr in part.iterrows():
        corp=str(sr.corp_code).zfill(8); preferred=str(sr.get('basis','') or '')
        prev={m:None for m in FLOW}; prev_basis=None
        for q,report in REPORTS:
            order=([preferred] if preferred in {'CFS','OFS'} else [])+[b for b in ('CFS','OFS') if b!=preferred]
            items=[]; basis=''; fetch_status=''
            for b in order:
                items,fetch_status=api(session,key,corp,year,report,b); status_counts[fetch_status]+=1
                if items: basis=b; break
            metrics={}
            for m in PREFERRED:
                if m in CAPEX and items:
                    v,rule,count,audit=capex_aggregate(items,m,q)
                    metrics[m]={'cumulative':v,'selection_rule':rule,'row_count':count,'rows':audit}
                else:
                    x,rule=choose_single(items,m) if items else (None,'missing_statement')
                    v,method=flow_cumulative(x,m,q)
                    metrics[m]={'cumulative':v,'selection_rule':rule,'amount_method':method,'account_id':x.get('account_id') if x else None,'account_nm':x.get('account_nm') if x else None,'sj_div':x.get('sj_div') if x else None}
            comparable=(q=='Q1') or (basis and prev_basis==basis)
            pure={}; methods={}
            for m in PREFERRED:
                cur=metrics[m]['cumulative']
                if m=='equity': pure[m]=cur; methods[m]='instant'
                elif q=='Q1': pure[m]=cur; methods[m]='direct_q1' if cur is not None else 'missing'
                else:
                    pv=prev.get(m)
                    if comparable and cur is not None and pv is not None:
                        delta=cur-pv
                        if m in CAPEX and delta<0:
                            pure[m]=None; methods[m]='negative_normalized_capex_delta_missing'; negative_capex_delta+=1
                        else:
                            pure[m]=delta; methods[m]='cumulative_difference'
                    else: pure[m]=None; methods[m]='missing_predecessor_or_basis_change'
            if q!='Q1' and basis and prev_basis and basis!=prev_basis: basis_switch+=1
            ppe=pure['capex_ppe']; inta=pure['capex_intangible']
            capex=(ppe+inta) if ppe is not None and inta is not None else None
            fcf=(pure['cfo']-capex) if pure['cfo'] is not None and capex is not None else None
            rows.append({'corp_code':corp,'company_name':sr.get('company_name',''),'business_year':year,'fiscal_quarter':q,'report_code':report,
                         'annual_reference_basis':preferred,'statement_basis':basis,'basis_matches_annual_reference':bool(basis and preferred and basis==preferred),
                         'basis_comparable_to_immediate_predecessor':bool(comparable),'statement_fetch_status':fetch_status,
                         'operating_profit_cumulative':metrics['operating_profit']['cumulative'],'operating_profit_q':pure['operating_profit'],
                         'net_income_cumulative':metrics['net_income']['cumulative'],'net_income_q':pure['net_income'],'equity_q_end':pure['equity'],
                         'cfo_cumulative':metrics['cfo']['cumulative'],'cfo_q':pure['cfo'],'capex_ppe_cumulative':metrics['capex_ppe']['cumulative'],
                         'capex_ppe_q_spend':ppe,'capex_intangible_cumulative':metrics['capex_intangible']['cumulative'],'capex_intangible_q_spend':inta,
                         'capex_q_spend':capex,'fcf_q':fcf,'op_pure_method':methods['operating_profit'],'ni_pure_method':methods['net_income'],
                         'cfo_pure_method':methods['cfo'],'capex_ppe_pure_method':methods['capex_ppe'],'capex_intangible_pure_method':methods['capex_intangible'],
                         'metric_selection_json':json.dumps(metrics,ensure_ascii=False),
                         'signal_date_status':'NOT_ASSIGNED_ACCOUNTING_STAGE','seed_source':seed_path.name,'modern_oos_protected':True})
            for m in FLOW:
                if metrics[m]['cumulative'] is not None: prev[m]=metrics[m]['cumulative']
            if basis: prev_basis=basis
    df=pd.DataFrame(rows)
    out=Path(f'korea_dart_quarterly_v2_{year}_chunk{chunk:03d}.csv'); summ=Path(f'korea_dart_quarterly_v2_{year}_chunk{chunk:03d}_summary.json')
    df.to_csv(out,index=False)
    s={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'research_stage':'development_quarterly_accounting_collection','collector_version':'2.1',
       'modern_oos_protected':True,'year':year,'chunk':chunk,'chunk_size':chunk_size,'seed_file':seed_path.name,'seed_rows_in_year':int(len(seed)),'seed_rows_in_chunk':int(len(part)),
       'output_rows':int(len(df)),'basis_switch_rows':int(basis_switch),'negative_normalized_capex_delta_cases':int(negative_capex_delta),'api_status_counts':dict(status_counts),
       'quarter_counts':df.fiscal_quarter.value_counts().to_dict() if not df.empty else {},
       'op_quarter_populated':int(df.operating_profit_q.notna().sum()) if not df.empty else 0,'ni_quarter_populated':int(df.net_income_q.notna().sum()) if not df.empty else 0,
       'cfo_quarter_populated':int(df.cfo_q.notna().sum()) if not df.empty else 0,'fcf_quarter_populated':int(df.fcf_q.notna().sum()) if not df.empty else 0,
       'q4_op_populated':int(df.loc[df.fiscal_quarter.eq('Q4'),'operating_profit_q'].notna().sum()) if not df.empty else 0,
       'signal_dates_assigned':0,'important_limitation':'Accounting reconstruction only. Earliest disclosure containing the relevant quarterly operating-profit information must be confirmed candidate-by-candidate before signal dating.'}
    summ.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(s,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
