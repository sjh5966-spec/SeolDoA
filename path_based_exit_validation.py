from pathlib import Path
import json
import pandas as pd
import numpy as np

SRC=Path('mfe_mae_results/daily_path_0_20.csv')
OUT=Path('path_based_exit_results'); OUT.mkdir(exist_ok=True)
if not SRC.exists(): raise FileNotFoundError(SRC)
path=pd.read_csv(SRC)
path['d']=pd.to_datetime(path['d'])

# Conservative OHLC simulation. Same-day ambiguity resolves against the strategy.
def trailing_after_trigger(g, trigger=0.20, trail=0.15):
    g=g.sort_values('day')
    ep=float(g.entry_price.iloc[0]); armed=False; peak=None
    for _,r in g.iterrows():
        oret=r.px_open/ep-1; hret=r.px_high/ep-1; lret=r.px_low/ep-1
        if not armed:
            if oret>=trigger:
                armed=True; peak=oret
            elif hret>=trigger:
                armed=True; peak=hret
        if armed:
            peak=max(peak,hret)
            stop_level=peak-trail
            # if stop is below open via gap, executable at open; otherwise at stop threshold.
            if oret<=stop_level:
                return oret,int(r.day),'TRAIL_GAP'
            if lret<=stop_level:
                return stop_level,int(r.day),'TRAIL'
    r=g.iloc[-1]
    return r.px_close/ep-1,int(r.day),'TIME'

def no_response_exit(g, day_cut=10, min_ret=0.0):
    g=g.sort_values('day')
    ep=float(g.entry_price.iloc[0])
    dcut=g[g.day==day_cut]
    if len(dcut):
        r=dcut.iloc[-1]; ret=r.px_close/ep-1
        if ret<=min_ret:
            return ret,int(r.day),'NO_RESPONSE'
    r=g.iloc[-1]
    return r.px_close/ep-1,int(r.day),'TIME'

def combo(g, trigger=0.20, trail=0.15, day_cut=10, min_ret=0.0):
    g=g.sort_values('day'); ep=float(g.entry_price.iloc[0]); armed=False; peak=None
    for _,r in g.iterrows():
        oret=r.px_open/ep-1; hret=r.px_high/ep-1; lret=r.px_low/ep-1
        if not armed:
            if oret>=trigger: armed=True; peak=oret
            elif hret>=trigger: armed=True; peak=hret
        if armed:
            peak=max(peak,hret); stop_level=peak-trail
            if oret<=stop_level: return oret,int(r.day),'TRAIL_GAP'
            if lret<=stop_level: return stop_level,int(r.day),'TRAIL'
        if int(r.day)==day_cut and not armed:
            ret=r.px_close/ep-1
            if ret<=min_ret: return ret,int(r.day),'NO_RESPONSE'
    r=g.iloc[-1]; return r.px_close/ep-1,int(r.day),'TIME'

rules=[]
for trigger,trail in [(0.20,0.15),(0.20,0.20),(0.30,0.15),(0.30,0.20)]:
    rules.append(('trail',trigger,trail,None,None))
for day_cut,min_ret in [(10,0.0),(10,0.05),(10,-0.05)]:
    rules.append(('no_response',None,None,day_cut,min_ret))
for trigger,trail,day_cut,min_ret in [(0.20,0.15,10,0.0),(0.20,0.20,10,0.0),(0.20,0.15,10,0.05),(0.30,0.15,10,0.0)]:
    rules.append(('combo',trigger,trail,day_cut,min_ret))

rows=[]; evrows=[]
for rule,trigger,trail,day_cut,min_ret in rules:
    vals=[]
    for key,g in path.groupby('event_key'):
        if rule=='trail': ret,day,reason=trailing_after_trigger(g,trigger,trail)
        elif rule=='no_response': ret,day,reason=no_response_exit(g,day_cut,min_ret)
        else: ret,day,reason=combo(g,trigger,trail,day_cut,min_ret)
        era=g.era.iloc[0]; vals.append((key,era,ret,day,reason))
    rdf=pd.DataFrame(vals,columns=['event_key','era','exit_return','exit_day','exit_reason'])
    rdf['rule']=rule; rdf['trigger']=trigger; rdf['trail']=trail; rdf['day_cut']=day_cut; rdf['min_ret']=min_ret
    evrows.append(rdf)
    for era,g in list(rdf.groupby('era'))+[('ALL',rdf)]:
        x=g.exit_return
        rows.append({'era':era,'rule':rule,'trigger':trigger,'trail':trail,'day_cut':day_cut,'min_ret':min_ret,'n':len(g),
                     'mean':x.mean(),'median':x.median(),'win_rate':(x>0).mean(),'up20_rate':(x>=0.20).mean(),
                     'down20_rate':(x<=-0.20).mean(),'mean_exit_day':g.exit_day.mean(),
                     'trail_exit_rate':g.exit_reason.str.startswith('TRAIL').mean(),'no_response_exit_rate':(g.exit_reason=='NO_RESPONSE').mean(),
                     'time_exit_rate':(g.exit_reason=='TIME').mean()})

# baseline from same path
base=[]
for era,g in list(path.groupby('era'))+[('ALL',path)]:
    last=g.sort_values(['event_key','day']).groupby('event_key').tail(1).copy()
    x=last.px_close/last.entry_price-1
    base.append({'era':era,'rule':'R20_TIME','n':len(x),'mean':x.mean(),'median':x.median(),'win_rate':(x>0).mean(),'up20_rate':(x>=0.20).mean(),'down20_rate':(x<=-0.20).mean(),'mean_exit_day':last.day.mean()})

pd.DataFrame(rows).to_csv(OUT/'path_exit_summary.csv',index=False)
pd.concat(evrows,ignore_index=True).to_csv(OUT/'path_exit_events.csv',index=False)
pd.DataFrame(base).to_csv(OUT/'baseline.csv',index=False)
meta={'note':'All rules use only information available through each trading day; same-day trailing ambiguity resolved conservatively against the strategy.','rules':rules}
with open(OUT/'meta.json','w') as f: json.dump(meta,f,indent=2)
print('BASELINE'); print(pd.DataFrame(base).to_string(index=False)); print('\nRULES'); print(pd.DataFrame(rows).to_string(index=False))
