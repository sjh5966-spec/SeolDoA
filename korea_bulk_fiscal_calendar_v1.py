#!/usr/bin/env python3
"""Build 2016-2020 stock-code fiscal-year-end-month map from OpenDART bulk Q1 BS files.
Development accounting metadata only; no returns, no 2021+, no OOS.
"""
from __future__ import annotations
import io,json,re,time,zipfile
from pathlib import Path
import pandas as pd,requests
MAIN='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do';LIST='https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do';DL='https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm='
OUT=Path('korea_bulk_fiscal_calendar_2016_2020.csv');SUM=Path('korea_bulk_fiscal_calendar_2016_2020_summary.json')
def dec(b):
 for e in ('utf-8-sig','utf-8','cp949','euc-kr'):
  try:return b.decode(e)
  except:pass
 return b.decode('utf-8','replace')
def get(s,u):
 last=''
 for a in range(5):
  try:r=s.get(u,timeout=(15,180));r.raise_for_status();return r
  except Exception as e:last=str(e);time.sleep(2*(a+1))
 raise RuntimeError(last)
def code(x):
 m=re.search(r'(\d{6})',str(x or ''));return m.group(1) if m else ''
def main():
 s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 SeolDoA fiscal calendar';get(s,MAIN);s.headers['Referer']=MAIN;b=get(s,LIST)
 calls=re.findall(r"download_ext002\('([0-9]{4})','([^']+)',\s*'([^']+)',\s*'([^']+\.zip)'\)",b.text);files={int(y):fn for y,p,r,fn in calls if 2016<=int(y)<=2020 and p=='FQ' and r=='BS'}
 if len(files)!=5:raise SystemExit(f'need 5 FQ BS files, got {files}')
 rows=[]
 for y,fn in sorted(files.items()):
  z=get(s,DL+fn);assert z.content[:2]==b'PK'
  with zipfile.ZipFile(io.BytesIO(z.content)) as q:
   for n in q.namelist():
    if not n.lower().endswith('.txt'):continue
    d=pd.read_csv(io.StringIO(dec(q.read(n))),sep='\t',dtype=str,keep_default_na=False,low_memory=False)
    if not {'종목코드','회사명','결산월','시장구분'}.issubset(d.columns):continue
    d['stock_code']=d['종목코드'].map(code);d=d[d.stock_code.ne('')]
    x=d[['stock_code','회사명','결산월','시장구분']].drop_duplicates()
    for r in x.itertuples(index=False):rows.append({'business_year':y,'stock_code':r.stock_code,'company_name':r.회사명,'fiscal_year_end_month':str(r.결산월).zfill(2),'market_label':r.시장구분})
 o=pd.DataFrame(rows).drop_duplicates(['business_year','stock_code','fiscal_year_end_month']).sort_values(['business_year','stock_code']);o.to_csv(OUT,index=False)
 sm={'development_only':True,'modern_oos_protected':True,'rows':len(o),'unique_stock_codes':int(o.stock_code.nunique()),'year_counts':o.business_year.value_counts().sort_index().to_dict(),'fiscal_month_counts':o.fiscal_year_end_month.value_counts().sort_index().to_dict(),'december_fye_rows':int((o.fiscal_year_end_month=='12').sum()),'non_december_fye_rows':int((o.fiscal_year_end_month!='12').sum()),'note':'Used to prevent calendar-quarter misclassification for non-December fiscal year issuers.'};SUM.write_text(json.dumps(sm,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(sm,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
