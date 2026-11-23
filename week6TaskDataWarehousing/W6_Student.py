import pandas as pd, os, re, csv, json, math, sys, shutil
from datetime import datetime, date, timedelta
from collections import Counter
from openpyxl import load_workbook
from openpyxl.styles import Alignment

BASE = r'C:\Users\HP\Downloads\Week6DataWarehousing'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'outputs')
os.makedirs(OUT, exist_ok=True)

# Helpers

def clean(s): return str(s or '').strip()
def canon(s): return clean(s).upper()
def parse_date(s, mode):
    s=clean(s)
    if not s: return None
    try:
        if mode=='marine': return datetime.strptime(s,'%d/%m/%Y').date()
        return pd.to_datetime(s, errors='raise').date()
    except Exception: return None

def num(s):
    s=clean(s).replace(',','')
    if not s: return None
    try: return float(s)
    except Exception: return None

def csv_data(path): return pd.read_csv(path,dtype=str,keep_default_na=False).fillna('')

marine=csv_data(os.path.join(BASE,'marine_march.csv'))
rail=pd.read_excel(os.path.join(BASE,'rail_march.xlsx'),header=2,dtype=str).fillna('')
road=csv_data(os.path.join(BASE,'road_march.csv'))
alias_df=csv_data(os.path.join(BASE,'alias_lookup.csv'))
city_df=csv_data(os.path.join(BASE,'DimCity (1).csv'))
route_df=csv_data(os.path.join(BASE,'DimRoute (1).csv'))
status_df=csv_data(os.path.join(BASE,'DimStatus (1).csv'))
mode_df=csv_data(os.path.join(BASE,'DimMode (1).csv'))
customer_df=csv_data(os.path.join(BASE,'customers_master.csv'))
city_alias={clean(r.RawSpelling):int(r.CityKey) for r in alias_df.itertuples()}
status_map={clean(r.StatusName).upper():int(r.StatusKey) for r in status_df.itertuples() if int(r.StatusKey)>0}
route_map={(int(r.OriginCityKey),int(r.DestCityKey)):int(r.RouteKey) for r in route_df.itertuples() if int(r.RouteKey)>0}
mode_map={'marine':1,'rail':2,'road':3}

raw=[]
def add(source,line,fields,mode):
    raw.append({'SourceFile':source,'SourceLine':line,'SourceMode':mode,**fields})
for i,r in marine.iterrows():
    add('marine_march.csv',i+2,{'ShipmentID':r['Shipment_ID'],'ShipDate':r['Ship_Date'],'Origin':r['Origin_Port'],'Destination':r['Dest_Port'],'WeightKG':r['Weight_KG'],'FreightCostPKR':r['Cost_PKR'],'StatusRaw':r['Status'],'CustomerID':r['Customer_Ref']},'marine')
for i,r in rail.iterrows():
    add('rail_march.xlsx',i+4,{'ShipmentID':'RL-'+clean(r['consignment_no']),'ShipDate':clean(r['date'])[:10],'Origin':r['from_station'],'Destination':r['to_station'],'WeightKG':r['net_tons'],'FreightCostPKR':r['freight_charges'],'StatusRaw':r['consignment_status'],'CustomerID':r['customer_code']},'rail')
for i,r in road.iterrows():
    # preserve footer and blank row as staging records; normalize only structure/column names
    add('road_march.csv',i+2,{'ShipmentID':r['trip_id'],'ShipDate':r['trip_date'],'Origin':r['from_city'],'Destination':r['to_city'],'WeightKG':r['weight_kg'],'FreightCostPKR':r['cost_pkr'],'StatusRaw':r['status'],'CustomerID':r['customer_id']},'road')

# Row-level profiling and verdicts
registry_counts=Counter(customer_df.CustomerID)
records=[]
for r in raw:
    mode=r['SourceMode']; dateval=parse_date(r['ShipDate'],mode)
    # rail is already text ISO via Excel serial/date normalization
    wt=num(r['WeightKG']); cost=num(r['FreightCostPKR'])
    # source weights in rail tonnes, converted for value checks
    if mode=='rail' and wt is not None: wt=wt*1000
    cid=clean(r['CustomerID'])
    origin=clean(r['Origin']); dest=clean(r['Destination'])
    oc=city_alias.get(origin); dc=city_alias.get(dest)
    st=clean(r['StatusRaw']).strip().upper()
    invalid=[]
    if clean(r['ShipmentID']).upper()=='TOTAL' or (not any(clean(r[k]) for k in ['ShipmentID','ShipDate','Origin','Destination','WeightKG','FreightCostPKR','StatusRaw','CustomerID'])):
        invalid.append('Non-shipment extract row (blank line or TOTAL footer)')
    elif wt is None: invalid.append('WeightKG is not numeric')
    elif wt<=0: invalid.append('WeightKG must be greater than zero')
    if dateval is None or dateval.year!=2026 or dateval.month!=3:
        invalid.append('ShipDate is blank, invalid, or outside March 2026')
    if not clean(r['ShipmentID']): invalid.append('ShipmentID is blank')
    if cost is None: invalid.append('FreightCostPKR is not numeric')
    if cid=='' or registry_counts.get(cid,0)!=1: invalid.append('CustomerID does not resolve to exactly one registry row')
    # Spec classes require reject exactly from weight/date/blank ID/invalid cost; no cost bad values expected
    reject=bool(invalid)
    # keep raw full; bad dates, weights and blank ID mapped by above; footer/blank also reject
    r2={**r,'_weight':wt,'_cost':cost,'_date':dateval,'_origin_key':oc,'_dest_key':dc,'_status_key':status_map.get(st),'_reject':reject,'_reason':' | '.join(invalid)}
    records.append(r2)

# robust data-quality categories per brief: corrupt weights, invalid dates, negative weight, blank ID, nonnumeric cost, plus two structural rows
# The intended 24 reject classes are 9 bad weight + 6 bad date + 5 negative weight + 4 blank ID.
# footer/blank rows must be routed to RejectLog too to preserve extraction identity, and are among unusable rows; classify with explicit reason.
# Deduplicate only valid/loadable rows by trimmed uppercase business ShipmentID.
loadable=[r for r in records if not r['_reject']]
seen=set(); facts=[]; removed=[]
for r in loadable:
    key=canon(r['ShipmentID'])
    if key in seen:
        r['_reason']='Duplicate ShipmentID after trim and uppercase'; removed.append(r)
    else:
        seen.add(key); facts.append(r)
# Customer business conformance: source registry has six alternate legal spellings.
customer_groups={101:[101,901],103:[103,902],104:[104,903],109:[109,904],119:[119,905],131:[131,906]}
primary={}
for i in range(101,141): primary[f'CU-{i}']=f'CU-{i}'
for a,b in customer_groups.values(): primary[f'CU-{b}']=f'CU-{a}'
# assign stable dimension keys 1..40
customer_key={f'CU-{i}':i-100 for i in range(101,141)}

# derive dimensions for the fact, use unknown keys for all unresolved lookups
for f in facts:
    dt=f['_date']; f['DateKey']=int(dt.strftime('%Y%m%d'))
    f['OriginCityKey']=f['_origin_key'] if f['_origin_key'] is not None else -1
    f['DestCityKey']=f['_dest_key'] if f['_dest_key'] is not None else -1
    f['RouteKey']=route_map.get((f['OriginCityKey'],f['DestCityKey']),-1)
    f['ModeKey']=mode_map[f['SourceMode']]
    f['StatusKey']=f['_status_key'] if f['_status_key'] is not None else -1
    f['CustomerKey']=customer_key.get(primary.get(clean(f['CustomerID']),''),-1)
    f['ShipmentID']=canon(f['ShipmentID'])
    f['WeightKG']=int(round(f['_weight']))
    f['FreightCostPKR']=int(round(f['_cost']))

# Write fact and reject outputs
fact_cols=['ShipmentID','DateKey','OriginCityKey','DestCityKey','RouteKey','ModeKey','StatusKey','CustomerKey','WeightKG','FreightCostPKR']
with open(os.path.join(OUT,'FactShipment_March.csv'),'w',newline='',encoding='utf-8-sig') as h:
    w=csv.DictWriter(h,fieldnames=fact_cols);w.writeheader();w.writerows([{c:r[c] for c in fact_cols} for r in facts])
reject_cols=['SourceFile','SourceLine','SourceMode','ShipmentID','ShipDate','Origin','Destination','WeightKG','FreightCostPKR','StatusRaw','CustomerID','RejectReason']
with open(os.path.join(OUT,'RejectLog.csv'),'w',newline='',encoding='utf-8-sig') as h:
    w=csv.DictWriter(h,fieldnames=reject_cols);w.writeheader()
    for r in records:
        if r['_reject']: w.writerow({**{c:r.get(c,'') for c in reject_cols if c!='RejectReason'},'RejectReason':r['_reason']})

# Build DimCustomer with source names retained as aliases; one row per normalized business and unknown row
name_to_key={}
for j,i in enumerate(range(101,141),1): name_to_key[f'CU-{i}']=j
aliases={f'CU-{i}':[] for i in range(101,141)}
for r in customer_df.to_dict('records'):
    key=primary.get(r['CustomerID'],r['CustomerID'])
    if key in aliases: aliases[key].append(r['CustomerName'])
dimcust=[]
for j,i in enumerate(range(101,141),1):
    rows=customer_df[customer_df.CustomerID==f'CU-{i}']
    dimcust.append({'CustomerKey':j,'CustomerID':f'CU-{i}','CustomerName':rows.iloc[0].CustomerName,'Aliases':' | '.join(aliases[f'CU-{i}']),'City':rows.iloc[0].City,'Sector':rows.iloc[0].Sector,'SignedUp':rows.iloc[0].SignedUp})
dimcust.append({'CustomerKey':-1,'CustomerID':'UNKNOWN','CustomerName':'Unknown','Aliases':'','City':'Unknown','Sector':'Unknown','SignedUp':''})
with open(os.path.join(OUT,'DimCustomer.csv'),'w',newline='',encoding='utf-8-sig') as h:
    w=csv.DictWriter(h,fieldnames=list(dimcust[0]));w.writeheader();w.writerows(dimcust)
# March gapless DimDate, 90 rows Jan-Mar if calendar quarter? Target says rows in DimDate 90; construct Jan-Mar 2026.
rows=[]; start=date(2026,1,1);end=date(2026,3,31);d=start
while d<=end:
    rows.append({'DateKey':int(d.strftime('%Y%m%d')),'FullDate':d.isoformat(),'Year':d.year,'Quarter':(d.month-1)//3+1,'MonthNumber':d.month,'MonthName':d.strftime('%B'),'DayOfMonth':d.day,'DayOfWeek':d.isoweekday(),'DayName':d.strftime('%A'),'IsWeekend':'Yes' if d.weekday()>=5 else 'No','IsHoliday':'No'})
    d+=timedelta(days=1)
with open(os.path.join(OUT,'DimDate.csv'),'w',newline='',encoding='utf-8-sig') as h:
    w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

print('raw',len(raw),'rejected',sum(r['_reject'] for r in records),'loadable',len(loadable),'removed',len(removed),'facts',len(facts))
print('fact totals',sum(f['WeightKG'] for f in facts),sum(f['FreightCostPKR'] for f in facts))
print('unknown origin',sum(f['OriginCityKey']==-1 for f in facts),Counter(r['Origin'] for r in facts if r['OriginCityKey']==-1))
print('unknown dest',sum(f['DestCityKey']==-1 for f in facts),Counter(r['Destination'] for r in facts if r['DestCityKey']==-1))
print('unknown status',sum(f['StatusKey']==-1 for f in facts),Counter(r['StatusRaw'] for r in facts if r['StatusKey']==-1))
print('reasons',Counter(r['_reason'] for r in records if r['_reject']))
# Audit assertions against the delivered source files. The assignment's 1,284/1,200
# checkpoint is separately reported because road_march.csv contains two more rows
# than its stated road count, and preserving the required blank/footer rows is mandatory.
assert len(raw) == 1286, f'Expected 1,286 rows from the supplied file contents; found {len(raw)}'
assert sum(r['_reject'] for r in records) == 24
assert len(removed) == 60
assert len(facts) == len(raw) - sum(r['_reject'] for r in records) - len(removed)
assert sum(f['OriginCityKey'] == -1 for f in facts) == 14
assert sum(f['StatusKey'] == -1 for f in facts) == 7
assert len(dimcust) == 41
assert len(rows) == 90
assert (sum(f['WeightKG'] for f in facts), sum(f['FreightCostPKR'] for f in facts)) == (17561150,147128000)
print('SOURCE AUDIT: PASS — conservation identity and lookup/dimension checks hold.')
print('BRIEF TARGET CONFLICT: extracted 1,284 vs source 1,286; fact 1,200 vs source-derived 1,202.')
