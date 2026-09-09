#!/usr/bin/env python3
"""Chunked OpenDART quarterly accounting collector for Korea Development 2015-2020.

Guardrails
- Reads only 2015-2020 seed corp/fiscal-year rows.
- Fetches Q1/Q2/Q3 accounting statements only; Q4 comes from the frozen local annual reference.
- No KRX prices/returns, no 2021+, and no 2023+ OOS data.
- Does NOT assign a trading signal/disclosure date. Disclosure-content confirmation is a later candidate-only step.
"""
from __future__ import annotations

import json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

DART_BASE = "https://opendart.fss.or.kr/api"
SEED = Path("korea_dart_quarterly_seed_2015_2020.csv")
REPORTS = {"Q1": "11013", "Q2": "11012", "Q3": "11014"}
PREFERRED_IDS = {
    "operating_profit": {"dart_OperatingIncomeLoss"},
    "net_income": {"ifrs_ProfitLoss"},
    "equity": {"ifrs_Equity"},
    "cfo": {"ifrs_CashFlowsFromUsedInOperatingActivities"},
    "capex_ppe": {"ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"},
    "capex_intangible": {"ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"},
}
FLOW_METRICS = {"operating_profit","net_income","cfo","capex_ppe","capex_intangible"}
CAPEX_METRICS = {"capex_ppe","capex_intangible"}

def num(x):
    if x is None or str(x).strip() == "": return None
    try: return float(str(x).replace(",", "").replace("−", "-"))
    except Exception: return None

def norm_label(x): return re.sub(r"\s+", "", str(x or ""))

def exact_label(metric, row):
    n=norm_label(row.get("account_nm")); s=str(row.get("sj_div") or "")
    if metric=="operating_profit": return s in {"IS","CIS"} and n in {"영업이익","영업손실","영업이익(손실)","영업손익"}
    if metric=="net_income":
        return s in {"IS","CIS"} and n in {"당기순이익","당기순손실","당기순이익(손실)","분기순이익","분기순손실","분기순이익(손실)","반기순이익","반기순손실","반기순이익(손실)","연결당기순이익","연결당기순이익(손실)"}
    if metric=="equity": return s=="BS" and n in {"자본총계","자본의총계"}
    if metric=="cfo": return s=="CF" and n in {"영업활동현금흐름","영업활동으로인한현금흐름","영업활동으로부터의현금흐름","영업활동에서창출된현금흐름"}
    if metric=="capex_ppe": return s=="CF" and "유형자산" in n and ("취득" in n or "구입" in n)
    if metric=="capex_intangible": return s=="CF" and "무형자산" in n and ("취득" in n or "구입" in n)
    return False

def canonical_section(metric):
    if metric in {"operating_profit","net_income"}: return {"IS","CIS"}
    if metric=="equity": return {"BS"}
    return {"CF"}

def choose_metric(items, metric):
    xs=[x for x in items if str(x.get("sj_div") or "") in canonical_section(metric)]
    std=[x for x in xs if str(x.get("account_id") or "") in PREFERRED_IDS[metric]]
    if len(std)==1: return std[0], "standard_id"
    if len(std)>1:
        exact=[x for x in std if exact_label(metric,x)]
        if len(exact)==1: return exact[0], "standard_id_exact_label"
        return None, "ambiguous_standard_id"
    exact=[x for x in xs if exact_label(metric,x)]
    if len(exact)==1: return exact[0], "exact_label_fallback"
    if len(exact)>1: return None, "ambiguous_exact_label"
    return None, "missing"

def capex_rows(items, metric):
    xs=[x for x in items if str(x.get("sj_div") or "")=="CF"]
    std=[x for x in xs if str(x.get("account_id") or "") in PREFERRED_IDS[metric]]
    chosen=std if std else [x for x in xs if exact_label(metric,x)]
    # Deduplicate exact duplicate rows while allowing multiple distinct acquisition rows to be summed.
    out=[]; seen=set()
    for x in chosen:
        key=(str(x.get("account_id") or ""),norm_label(x.get("account_nm")),str(x.get("thstrm_amount") or ""),str(x.get("thstrm_add_amount") or ""))
        if key not in seen: seen.add(key); out.append(x)
    return out, ("standard_id_sum" if std else ("exact_label_sum" if out else "no_qualifying_rows"))

def api_json(session,key,path,**params):
    last=None
    for attempt in range(4):
        try:
            r=session.get(f"{DART_BASE}/{path}",params={"crtfc_key":key,**params},timeout=60); r.raise_for_status(); d=r.json(); st=str(d.get("status",""))
            if st=="000": return d,"ok"
            if st=="013": return {"list":[]},"no_data"
            return d,f"dart_status_{st}"
        except Exception as e:
            last=str(e); time.sleep(attempt+1)
    return {"list":[]},f"request_error:{last}"

def fetch_statement(session,key,corp,year,report,basis):
    d,status=api_json(session,key,"fnlttSinglAcntAll.json",corp_code=corp,bsns_year=str(year),reprt_code=report,fs_div=basis)
    return d.get("list",[]) or [],status

def amount_fields(row,metric,quarter):
    if not row: return None,None,None,"missing"
    cur=num(row.get("thstrm_amount")); add=num(row.get("thstrm_add_amount")); sj=str(row.get("sj_div") or "")
    if metric=="equity": return cur,cur,add,("instant_thstrm_amount" if cur is not None else "missing")
    if quarter=="Q1":
        chosen=cur if cur is not None else add
        return chosen,cur,add,("q1_thstrm_amount" if cur is not None else ("q1_add_fallback" if add is not None else "missing"))
    if add is not None: return add,cur,add,"cumulative_thstrm_add_amount"
    # OpenDART CF rows commonly expose only thstrm_amount; for H1/Q3 this is YTD cumulative.
    if sj=="CF" and cur is not None: return cur,cur,add,"cumulative_cf_thstrm_amount"
    return None,cur,add,"cumulative_missing"

def aggregate_capex(items,metric,quarter):
    rows,rule=capex_rows(items,metric)
    if not rows:
        # A usable CF statement with no qualifying acquisition row means no observed cash CAPEX of this class.
        return {"cumulative":0.0,"thstrm_amount":None,"thstrm_add_amount":None,"amount_method":"no_qualifying_rows_zero","selection_rule":rule,"account_id":None,"account_nm":None,"sj_div":"CF","row_count":0}
    vals=[]; raw_cur=[]; raw_add=[]; audit=[]
    for r in rows:
        cumulative,cur,add,method=amount_fields(r,metric,quarter)
        if cumulative is not None: vals.append(cumulative)
        raw_cur.append(cur); raw_add.append(add)
        audit.append({"account_id":r.get("account_id"),"account_nm":r.get("account_nm"),"cumulative":cumulative,"thstrm_amount":cur,"thstrm_add_amount":add,"method":method})
    cumulative=sum(vals) if vals else None
    return {"cumulative":cumulative,"thstrm_amount":raw_cur,"thstrm_add_amount":raw_add,"amount_method":"sum_distinct_capex_rows","selection_rule":rule,"account_id":None,"account_nm":None,"sj_div":"CF","row_count":len(rows),"rows":audit}

def main():
    key=os.getenv("DART_API_KEY","").strip()
    if not key: raise SystemExit("DART_API_KEY is required")
    year=int(os.getenv("DART_QUARTER_YEAR","2015")); chunk=int(os.getenv("DART_QUARTER_CHUNK","0")); chunk_size=int(os.getenv("DART_QUARTER_CHUNK_SIZE","300"))
    if year<2015 or year>2020: raise SystemExit("DART_QUARTER_YEAR must be 2015..2020")
    if chunk<0 or chunk_size<1 or chunk_size>1000: raise SystemExit("invalid chunk/chunk_size")
    seed=pd.read_csv(SEED,dtype=str).fillna(""); seed=seed[seed["fiscal_year"].astype(str).eq(str(year))].copy(); seed=seed.sort_values(["corp_code","receipt_no"]).drop_duplicates(["corp_code","fiscal_year"],keep="first")
    part=seed.iloc[chunk*chunk_size:chunk*chunk_size+chunk_size].copy()
    out_csv=Path(f"korea_dart_quarterly_{year}_chunk{chunk:03d}.csv"); out_summary=Path(f"korea_dart_quarterly_{year}_chunk{chunk:03d}_summary.json")
    session=requests.Session(); session.headers.update({"User-Agent":"SeolDoA-Korea-DART-Quarterly/1.1"})
    raw=[]; api_status_counts={}; basis_switch_rows=0
    for _,seedrow in part.iterrows():
        corp=str(seedrow["corp_code"]).zfill(8); preferred=str(seedrow.get("basis","") or ""); previous_cumulative={m:None for m in FLOW_METRICS}; previous_basis=None
        for q,report_code in REPORTS.items():
            order=([preferred] if preferred in {"CFS","OFS"} else [])+[b for b in ("CFS","OFS") if b!=preferred]
            items=[]; basis_used=""; fetch_status=""
            for b in order:
                items,fetch_status=fetch_statement(session,key,corp,year,report_code,b); api_status_counts[fetch_status]=api_status_counts.get(fetch_status,0)+1
                if items: basis_used=b; break
            metrics={}
            for metric in PREFERRED_IDS:
                if metric in CAPEX_METRICS and items:
                    metrics[metric]=aggregate_capex(items,metric,q); continue
                chosen,selection=choose_metric(items,metric) if items else (None,"missing_statement")
                cumulative,current_field,add_field,amount_method=amount_fields(chosen,metric,q)
                metrics[metric]={"cumulative":cumulative,"thstrm_amount":current_field,"thstrm_add_amount":add_field,"amount_method":amount_method,"selection_rule":selection,"account_id":chosen.get("account_id") if chosen else None,"account_nm":chosen.get("account_nm") if chosen else None,"sj_div":chosen.get("sj_div") if chosen else None}
            basis_comparable=(q=="Q1") or (basis_used!="" and previous_basis==basis_used); pure={}; pure_method={}
            for metric in PREFERRED_IDS:
                cumulative=metrics[metric]["cumulative"]
                if metric=="equity": pure[metric]=cumulative; pure_method[metric]="instant"
                elif q=="Q1": pure[metric]=cumulative; pure_method[metric]="direct_q1" if cumulative is not None else "missing"
                else:
                    prev=previous_cumulative.get(metric)
                    if basis_comparable and cumulative is not None and prev is not None: pure[metric]=cumulative-prev; pure_method[metric]="cumulative_difference"
                    else: pure[metric]=None; pure_method[metric]="missing_predecessor_or_basis_change"
            ppe_spend=abs(pure["capex_ppe"]) if pure["capex_ppe"] is not None else None; int_spend=abs(pure["capex_intangible"]) if pure["capex_intangible"] is not None else None
            capex_spend=(ppe_spend+int_spend) if ppe_spend is not None and int_spend is not None else None; fcf=(pure["cfo"]-capex_spend) if pure["cfo"] is not None and capex_spend is not None else None
            if q!="Q1" and basis_used and previous_basis and basis_used!=previous_basis: basis_switch_rows+=1
            raw.append({"corp_code":corp,"company_name":seedrow.get("company_name",""),"business_year":year,"fiscal_quarter":q,"report_code":report_code,"annual_reference_basis":preferred,"statement_basis":basis_used,"basis_matches_annual_reference":bool(basis_used and preferred and basis_used==preferred),"basis_comparable_to_immediate_predecessor":basis_comparable,"statement_fetch_status":fetch_status,"operating_profit_cumulative":metrics["operating_profit"]["cumulative"],"operating_profit_q":pure["operating_profit"],"net_income_cumulative":metrics["net_income"]["cumulative"],"net_income_q":pure["net_income"],"equity_q_end":pure["equity"],"cfo_cumulative":metrics["cfo"]["cumulative"],"cfo_q":pure["cfo"],"capex_ppe_cumulative":metrics["capex_ppe"]["cumulative"],"capex_ppe_q_spend":ppe_spend,"capex_intangible_cumulative":metrics["capex_intangible"]["cumulative"],"capex_intangible_q_spend":int_spend,"capex_q_spend":capex_spend,"fcf_q":fcf,"op_pure_method":pure_method["operating_profit"],"ni_pure_method":pure_method["net_income"],"cfo_pure_method":pure_method["cfo"],"metric_selection_json":json.dumps(metrics,ensure_ascii=False),"signal_date_status":"NOT_ASSIGNED_ACCOUNTING_STAGE","seed_source":"annual_reference_2015_2020_accept","modern_oos_protected":True})
            for metric in FLOW_METRICS:
                if metrics[metric]["cumulative"] is not None: previous_cumulative[metric]=metrics[metric]["cumulative"]
            if basis_used: previous_basis=basis_used
    df=pd.DataFrame(raw); df.to_csv(out_csv,index=False)
    summary={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"research_stage":"development_quarterly_accounting_collection","collector_version":"1.1","modern_oos_protected":True,"year":year,"chunk":chunk,"chunk_size":chunk_size,"seed_rows_in_year":int(len(seed)),"seed_rows_in_chunk":int(len(part)),"output_rows":int(len(df)),"basis_switch_rows":int(basis_switch_rows),"api_status_counts":api_status_counts,"op_quarter_populated":int(df["operating_profit_q"].notna().sum()) if not df.empty else 0,"ni_quarter_populated":int(df["net_income_q"].notna().sum()) if not df.empty else 0,"cfo_quarter_populated":int(df["cfo_q"].notna().sum()) if not df.empty else 0,"fcf_quarter_populated":int(df["fcf_q"].notna().sum()) if not df.empty else 0,"signal_dates_assigned":0,"field_semantics_note":"IS/CIS H1/Q3 prefers thstrm_add_amount cumulative; CF H1/Q3 uses thstrm_amount as cumulative when add field is absent. CAPEX sums distinct acquisition rows.","important_limitation":"Accounting-only Q1-Q3 collector. Signal dates require later candidate-only disclosure-content confirmation. No KRX prices/returns are used."}
    out_summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
