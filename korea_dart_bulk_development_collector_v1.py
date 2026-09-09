#!/usr/bin/env python3
"""Development-only 2016-2020 quarterly accounting reconstruction from OpenDART bulk TXT ZIPs.

Bulk snapshots are used ONLY for full-universe candidate discovery/QC. They can contain later corrections.
Every final candidate must be re-confirmed against its original DART receipt before PIT signal dating.
No 2021+, no returns, no threshold selection, no modern OOS.
"""
from __future__ import annotations
import io,json,re,time,zipfile
from collections import defaultdict,Counter
from pathlib import Path
import pandas as pd
import requests

MAIN='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do'
LIST='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do'
DL='https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm='
SEED=Path('korea_dart_historical_seed_2015_2020.csv')
OUT=Path('korea_dart_bulk_quarterly_2016_2020.csv')
SUM=Path('korea_dart_bulk_quarterly_2016_2020_summary.json')
YEARS=range(2016,2021)
PERIOD={'FQ':'Q1','HY':'Q2','TQ':'Q3','FY':'Q4'}
ROLES={'BS','PL','CF'}

IDS={
 'op':{'dart_OperatingIncomeLoss'},
 'ni':{'ifrs_ProfitLoss','ifrs-full_ProfitLoss'},
 'equity':{'ifrs_Equity','ifrs-full_Equity'},
 'cfo':{'ifrs_CashFlowsFromUsedInOperatingActivities','ifrs-full_CashFlowsFromUsedInOperatingActivities'},
 'ppe':{'ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities','ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'},
 'inta':{'ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities','ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'},
}
LABEL={
 'op':{'영업이익','영업손실','영업이익(손실)','영업손익'},
 'ni':{'당기순이익','당기순손실','당기순이익(손실)','분기순이익','분기순손실','분기순이익(손실)','반기순이익','반기순손실','반기순이익(손실)','연결당기순이익','연결당기순이익(손실)'},
 'equity':{'자본총계','자본의총계'},
 'cfo':{'영업활동현금흐름','영업활동으로인한현금흐름','영업활동으로부터의현금흐름','영업활동에서창출된현금흐름'},
}

def norm(s):return re.sub(r'\s+','',str(s or '')).replace('[abstract]','')
def num(x):
    s=str(x or '').strip().replace(',','').replace('−','-').replace('(','-').replace(')','')
    if s in ('','-','—','nan'):return None
    try:return float(s)
    except:return None
def code(x):
    m=re.search(r'(\d{6})',str(x or ''));return m.group(1) if m else ''
def basis(x):
    s=str(x or '')
    if '연결재무제표' in s and '별도재무제표' not in s:return 'CFS'
    if '별도재무제표' in s:return 'OFS'
    return ''
def decode(raw):
    for enc in ('utf-8-sig','utf-8','cp949','euc-kr'):
        try:return raw.decode(enc),enc
        except:pass
    return raw.decode('utf-8','replace'),'replace'
def get(s,url,**kw):
    last=''
    for a in range(6):
        try:
            r=s.get(url,timeout=(15,240),**kw);r.raise_for_status();return r
        except Exception as e:last=str(e);time.sleep(min(20,2*(a+1)))
    raise RuntimeError(last)
def current_cols(cols,role,q):
    cs=[c for c in cols if str(c).startswith('당기') and not str(c).startswith('당기순')]
    if role=='PL':
        m3=[c for c in cs if '3개월' in c]
        if m3:return m3[0]
        cum=[c for c in cs if ('누적' in c or q=='Q4')]
        return cum[0] if cum else (cs[0] if cs else '')
    return cs[0] if cs else ''
def select_one(g,metric,col):
    if g is None or g.empty or not col:return None,'missing'
    a=g[g['항목코드'].astype(str).isin(IDS[metric])]
    rule='standard_id'
    if a.empty and metric in LABEL:
        a=g[g['항목명'].map(norm).isin(LABEL[metric])];rule='exact_label'
    if a.empty:return None,'missing'
    vals=[num(x) for x in a[col].tolist()];vals=[x for x in vals if x is not None]
    if not vals:return None,rule+'_no_amount'
    uv=set(vals)
    if len(uv)==1:return vals[0],rule+('_duplicate_same' if len(vals)>1 else '')
    return None,'ambiguous_'+rule
def capex(g,metric,col):
    if g is None or g.empty or not col:return None,'missing'
    a=g[g['항목코드'].astype(str).isin(IDS[metric])]
    rule='standard_id'
    if a.empty:
        names=g['항목명'].map(norm)
        if metric=='ppe': mask=names.str.contains('유형자산',regex=False)&(names.str.contains('취득',regex=False)|names.str.contains('구입',regex=False))
        else: mask=names.str.contains('무형자산',regex=False)&(names.str.contains('취득',regex=False)|names.str.contains('구입',regex=False))
        a=g[mask];rule='exact_label_pattern'
    if a.empty:return None,'missing'
    # Deduplicate identical account code/name/value rows before summing distinct qualifying rows.
    seen=set();vals=[]
    for _,r in a.iterrows():
        v=num(r.get(col));k=(str(r.get('항목코드','')),norm(r.get('항목명','')),v)
        if k in seen:continue
        seen.add(k)
        if v is not None:vals.append(abs(v))
    return (sum(vals) if vals else None),rule+('_sum' if len(vals)>1 else '')
def load_zip(raw,role,q):
    frames=[];encs=Counter()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for n in zf.namelist():
            if not n.lower().endswith(('.txt','.tsv','.csv')):continue
            txt,enc=decode(zf.read(n));encs[enc]+=1
            try:d=pd.read_csv(io.StringIO(txt),sep='\t',dtype=str,keep_default_na=False,low_memory=False)
            except Exception:continue
            d=d.loc[:,~d.columns.astype(str).str.startswith('Unnamed')].copy()
            need={'재무제표종류','종목코드','회사명','시장구분','항목코드','항목명'}
            if not need.issubset(set(d.columns)):continue
            d['statement_basis']=d['재무제표종류'].map(basis);d['stock_code']=d['종목코드'].map(code)
            d=d[d.statement_basis.isin(['CFS','OFS']) & d.stock_code.ne('')]
            if not d.empty:frames.append(d)
    return (pd.concat(frames,ignore_index=True,sort=False) if frames else pd.DataFrame()),dict(encs)
def main():
    if not SEED.exists():raise SystemExit('historical seed missing')
    seed=pd.read_csv(SEED,dtype=str).fillna('');seed=seed[seed.fiscal_year.astype(int).between(2016,2020)].copy()
    seed['corp_code']=seed.corp_code.astype(str).str.zfill(8);seed['stock_code']=seed.stock_code.map(code);seed['nname']=seed.company_name.map(norm)
    code_map={(int(r.fiscal_year),r.stock_code):r for r in seed.itertuples(index=False) if r.stock_code}
    name_groups=defaultdict(list)
    for r in seed.itertuples(index=False):name_groups[(int(r.fiscal_year),r.nname)].append(r)
    s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
    get(s,MAIN);s.headers['Referer']=MAIN;listing=get(s,LIST)
    calls=re.findall(r"download_ext002\('([0-9]{4})','([^']+)',\s*'([^']+)',\s*'([^']+\.zip)'\)",listing.text)
    chosen={(int(y),PERIOD[p],role):fn for y,p,role,fn in calls if int(y) in YEARS and p in PERIOD and role in ROLES}
    expected={(y,q,r) for y in YEARS for q in PERIOD.values() for r in ROLES}
    miss=sorted(expected-set(chosen));
    if miss:raise SystemExit('missing bulk links '+repr(miss[:20]))
    # Store extracted role tables only while needed; 60 ZIPs, but compact metric dictionary stays small.
    metrics=defaultdict(dict); statement_presence=set(); download_meta=[]; mapping=Counter();selection=Counter()
    for y in YEARS:
      for p,q in PERIOD.items():
        for role in ('BS','PL','CF'):
            fn=chosen[(y,q,role)];r=get(s,DL+fn)
            if r.content[:2]!=b'PK':raise RuntimeError(f'not zip {fn}: {r.text[:200]}')
            d,encs=load_zip(r.content,role,q);download_meta.append({'year':y,'quarter':q,'role':role,'filename':fn,'zip_bytes':len(r.content),'rows':len(d),'encodings':encs})
            if d.empty:continue
            col=current_cols(d.columns,role,q)
            for (sc,b),g in d.groupby(['stock_code','statement_basis'],sort=False):
                statement_presence.add((y,q,sc,b))
                seedrow=code_map.get((y,sc));maprule='stock_code'
                if seedrow is None:
                    nn=norm(g.iloc[0]['회사명']);cands=name_groups.get((y,nn),[])
                    if len(cands)==1:seedrow=cands[0];maprule='unique_name'
                if seedrow is None:mapping['unmapped_groups']+=1;continue
                mapping[maprule]+=1;corp=seedrow.corp_code
                key=(corp,y,q,b);m=metrics[key];m.update({'corp_code':corp,'company_name':seedrow.company_name or g.iloc[0]['회사명'],'stock_code_bulk':sc,'business_year':y,'fiscal_quarter':q,'statement_basis':b,'mapping_rule':maprule})
                if role=='BS':
                    v,ru=select_one(g,'equity',col);m['equity_cumulative']=v;selection['equity_'+ru]+=1
                elif role=='PL':
                    for met in ('op','ni'):
                        v,ru=select_one(g,met,col);m[met+'_pl_value']=v;selection[met+'_'+ru]+=1
                    m['pl_amount_kind']='pure_quarter' if q in {'Q1','Q2','Q3'} else 'annual_cumulative'
                else:
                    for met in ('cfo','ppe','inta'):
                        if met in ('ppe','inta'):v,ru=capex(g,met,col)
                        else:v,ru=select_one(g,met,col)
                        m[met+'_cf_cumulative']=v;selection[met+'_'+ru]+=1
    # Select one statement basis per corp/quarter globally: CFS whenever any CFS statement is present, else OFS.
    allkeys={(k[0],k[1],k[2]) for k in metrics}
    rows=[];byseq={}
    qord={'Q1':1,'Q2':2,'Q3':3,'Q4':4}
    for corp,y,q in sorted(allkeys,key=lambda x:(x[0],x[1],qord[x[2]])):
        bases=[b for b in ('CFS','OFS') if (corp,y,q,b) in metrics]
        b='CFS' if 'CFS' in bases else ('OFS' if 'OFS' in bases else '')
        m=metrics.get((corp,y,q,b),{});seq=y*4+qord[q];prev=byseq.get((corp,seq-1));sameprev=bool(prev and prev['statement_basis']==b)
        op_raw=m.get('op_pl_value');ni_raw=m.get('ni_pl_value')
        if q!='Q4':opq=op_raw;niq=ni_raw;opmethod='bulk_pl_direct_3m';nimethod='bulk_pl_direct_3m'
        else:
            ps=[byseq.get((corp,seq-i)) for i in (1,2,3)]
            comparable=all(x and x['statement_basis']==b for x in ps)
            opvals=[x.get('operating_profit_q') if x else None for x in ps];niv=[x.get('net_income_q') if x else None for x in ps]
            opq=(op_raw-sum(opvals)) if comparable and op_raw is not None and all(x is not None for x in opvals) else None
            niq=(ni_raw-sum(niv)) if comparable and ni_raw is not None and all(x is not None for x in niv) else None
            opmethod='fy_minus_q1_q2_q3' if opq is not None else 'missing_predecessor_or_basis';nimethod='fy_minus_q1_q2_q3' if niq is not None else 'missing_predecessor_or_basis'
        cfo_c=m.get('cfo_cf_cumulative');ppe_c=m.get('ppe_cf_cumulative');inta_c=m.get('inta_cf_cumulative')
        if q=='Q1':cfoq=cfo_c;ppeq=ppe_c;intaq=inta_c;cfmethod='direct_q1'
        else:
            cfoq=(cfo_c-prev.get('cfo_cumulative')) if sameprev and cfo_c is not None and prev.get('cfo_cumulative') is not None else None
            ppeq=(ppe_c-prev.get('ppe_cumulative')) if sameprev and ppe_c is not None and prev.get('ppe_cumulative') is not None else None
            intaq=(inta_c-prev.get('inta_cumulative')) if sameprev and inta_c is not None and prev.get('inta_cumulative') is not None else None
            if ppeq is not None and ppeq<0:ppeq=None
            if intaq is not None and intaq<0:intaq=None
            cfmethod='cumulative_difference' if sameprev else 'missing_predecessor_or_basis'
        capexq=(ppeq+intaq) if ppeq is not None and intaq is not None else None;fcfq=(cfoq-capexq) if cfoq is not None and capexq is not None else None
        row={'corp_code':corp,'company_name':m.get('company_name',''),'stock_code':m.get('stock_code_bulk',''),'business_year':y,'fiscal_quarter':q,'statement_basis':b,'mapping_rule':m.get('mapping_rule',''),
             'operating_profit_q':opq,'net_income_q':niq,'equity_q_end':m.get('equity_cumulative'),'cfo_q':cfoq,'capex_ppe_q_spend':ppeq,'capex_intangible_q_spend':intaq,'capex_q_spend':capexq,'fcf_q':fcfq,
             'operating_profit_source_value':op_raw,'net_income_source_value':ni_raw,'cfo_cumulative':cfo_c,'ppe_cumulative':ppe_c,'inta_cumulative':inta_c,'op_pure_method':opmethod,'ni_pure_method':nimethod,'cf_pure_method':cfmethod,
             'source_type':'OPENDART_BULK_CURRENT_SNAPSHOT_CANDIDATE_DISCOVERY_ONLY','pit_value_confirmed':False,'signal_date_status':'NOT_ASSIGNED','modern_oos_protected':True}
        rows.append(row);byseq[(corp,seq)]=row
    o=pd.DataFrame(rows).sort_values(['corp_code','business_year','fiscal_quarter']);o.to_csv(OUT,index=False)
    sm={'research_stage':'development_bulk_accounting_candidate_discovery','development_only':True,'modern_oos_protected':True,'years':[2016,2017,2018,2019,2020],'bulk_zip_count':len(download_meta),'rows':len(o),'unique_corps':int(o.corp_code.nunique()),
        'year_rows':o.business_year.value_counts().sort_index().to_dict(),'basis_counts':o.statement_basis.value_counts().to_dict(),'mapping_counts':dict(mapping),'op_populated':int(o.operating_profit_q.notna().sum()),'ni_populated':int(o.net_income_q.notna().sum()),'equity_populated':int(o.equity_q_end.notna().sum()),'cfo_populated':int(o.cfo_q.notna().sum()),'fcf_populated':int(o.fcf_q.notna().sum()),
        'downloads':download_meta,'selection_counts':dict(selection),'critical_limitation':'OpenDART bulk files are rebuilt/current snapshots and may reflect later corrections. Use only for candidate discovery/QC. Re-confirm every selected candidate against original receipt-specific DART filing before PIT values/signal dates.'}
    SUM.write_text(json.dumps(sm,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in sm.items() if k not in {'downloads','selection_counts'}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
