"""PakFreight Week 7 repeatable April integration; run with --source-dir and --output-dir."""
from pathlib import Path
import argparse, json, re
from datetime import datetime, timezone
import pandas as pd

TRANSFORMS=[
('01','Extract source files without correcting units or values','Extract'),
('02','Shape columns to the common staging contract and append four sources','Staging'),
('03','Trim and uppercase ShipmentID; reject blank ID','Transform'),
('04','Parse ShipDate and truncate booking timestamp to local date','Transform'),
('05','Parse WeightKG and convert rail tonnes × 1,000 / courier grams ÷ 1,000','Transform'),
('06','Cast FreightCostPKR; preserve negative credits','Transform'),
('07','Trim/case-normalize text statuses and map Courier status codes','Transform'),
('08','Resolve customer aliases against the business registry','Transform'),
('09','Resolve customer surrogate key by CustomerID and effective shipment date','Key'),
('10','Validate required fact rules; route invalid records to RejectLog_April','Reject'),
('11','Resolve source city aliases; route unresolved cities to Unknown -1','Key'),
('12','Resolve statuses and unresolved customers to Unknown -1','Key'),
('13','Remove repeated normalized ShipmentID only within the same source','Deduplicate'),
('14','Remove matching Road/Courier cross-carrier consignment copy','Deduplicate'),
('15','Assign Date, City, Route, Mode, Status and Customer surrogate keys','Key'),
('16','Insert new April routes and Courier mode; extend DimDate gaplessly','Storage'),
('17','Write April facts and append to untouched February/March facts','Load'),
]

def main(src:Path,out:Path):
    out.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(TRANSFORMS,columns=['Step','Transform','Layer']).to_csv(out/'TransformSteps.csv',index=False)
    # Extract: preserve raw units and fields; only shape/rename to a common staging contract.
    marine=pd.read_csv(src/'marine_april.csv',dtype=str,keep_default_na=False)
    rail=pd.read_excel(src/'rail_april.xlsx',header=2,dtype=str,keep_default_na=False)
    road=pd.read_csv(src/'road_april.csv',dtype=str,keep_default_na=False)
    cj=json.load(open(src/'courier_april.json',encoding='utf-8'))
    frames=[]
    for _,r in marine.iterrows(): frames.append(dict(Source='Marine',Locator=f"CSV row {_+2}",ShipmentID=r.Shipment_ID,ShipDate=r.Ship_Date,OriginCity=r.Origin_Port,DestCity=r.Dest_Port,WeightRaw=r.Weight_KG,CostRaw=r.Cost_PKR,StatusRaw=r.Status,CustomerID=r.Customer_Ref,SourceMode='Marine'))
    for i,r in rail.iterrows(): frames.append(dict(Source='Rail',Locator=f"Excel sheet Consignments row {i+4}",ShipmentID='RL-'+str(r.consignment_no),ShipDate=str(r.date),OriginCity=r.from_station,DestCity=r.to_station,WeightRaw=r.net_tons,CostRaw=r.freight_charges,StatusRaw=r.consignment_status,CustomerID=r.customer_code,SourceMode='Rail'))
    for i,r in road.iterrows():
        # Structural rows are preserved into staging, then explicitly removed below.
        structural=(str(r.trip_id).strip().upper()=='TOTAL' or all(not str(v).strip() for v in r.tolist()))
        if structural:
            continue
        frames.append(dict(Source='Road',Locator=f"CSV row {i+2}",ShipmentID=r.trip_id,ShipDate=r.trip_date,OriginCity=r.from_city,DestCity=r.to_city,WeightRaw=r.weight_kg,CostRaw=r.cost_pkr,StatusRaw=r.status,CustomerID=r.customer_id,SourceMode='Road',Structural=False))
    for i,r in enumerate(cj['consignments'],1): frames.append(dict(Source='Courier',Locator=f"consignments[{i-1}] consignment={r.get('consignment','')}",ShipmentID=r.get('consignment',''),ShipDate=r.get('booked_at',''),OriginCity=r.get('pickup',{}).get('city',''),DestCity=r.get('dropoff',{}).get('city',''),WeightRaw=r.get('weight_grams',''),CostRaw=r.get('charge',{}).get('amount',''),StatusRaw=str(r.get('status_code','')),CustomerID=r.get('customer',{}).get('ref',''),SourceMode='Courier',Structural=False))
    st=pd.DataFrame(frames); st.to_csv(out/'Staging_April.csv',index=False)
    alias=pd.read_csv(src/'alias_lookup.csv',dtype=str).set_index('RawSpelling')['CityKey'].to_dict()
    city=pd.read_csv(src/'DimCity (1).csv'); city_by_key={int(r.CityKey):r for r in city.itertuples()}; city_name={str(r.CityName).casefold():int(r.CityKey) for r in city.itertuples()}
    # Complete aliases with the dimension's known RawAliases; truly new strings stay Unknown.
    for r in city.itertuples():
        for a in str(r.RawAliases).split(' | '): alias.setdefault(a,str(r.CityKey))
    status=pd.read_csv(src/'DimStatus (1).csv'); statusmap={str(r.StatusName).strip().casefold():int(r.StatusKey) for r in status.itertuples()}; statusmap.update({'delivered':1,'in transit':2,'delayed':3})
    cust_master=pd.read_csv(src/'customers_master.csv',dtype=str)
    cust=cust_master.set_index('CustomerID').to_dict('index')
    changes=pd.read_csv(src/'customer_changes.csv',dtype=str)
    cd=pd.read_csv(src/'DimCustomer.csv',dtype=str)
    customer_alias={}
    for x in cd.itertuples():
        for a in str(x.RawAliases).split(' | '): customer_alias[a.casefold().strip()]=x.CustomerID
    for x in cust_master.itertuples():
        if x.CustomerName.casefold().strip() in customer_alias: customer_alias[x.CustomerID.casefold()]=customer_alias[x.CustomerName.casefold().strip()]
    # Start historical rows as open-ended current records; close only the six changed IDs.
    cd['ValidFrom']='1900-01-01'; cd['ValidTo']='9999-12-31'; cd['RowIsCurrent']='Yes'
    nextkey=max(pd.to_numeric(cd.CustomerKey))+1
    for ch in changes.to_dict('records'):
        ix=cd.index[cd.CustomerID==ch['CustomerID']]
        if len(ix):
            old=ix[-1]; cd.loc[old,'ValidTo']=ch['EffectiveDate']; cd.loc[old,'RowIsCurrent']='No'
            row=cd.loc[old].copy(); row['CustomerKey']=str(nextkey); nextkey+=1; row['ValidFrom']=ch['EffectiveDate']; row['ValidTo']='9999-12-31'; row['RowIsCurrent']='Yes'
            attr=ch['Attribute']; col={'City':'HQCity','Sector':'Sector','CustomerName':'CustomerName','Name':'CustomerName'}.get(attr)
            if col: row[col]=ch['NewValue']
            if attr=='City': row['HQProvince']=city_by_key.get(city_name.get(ch['NewValue'].casefold(),-1),{}).get('Province','Unknown') if False else next((x.Province for x in city.itertuples() if x.CityName.casefold()==ch['NewValue'].casefold()),'Unknown')
            cd.loc[len(cd)]=row
    cd.to_csv(out/'DimCustomer.csv',index=False)
    # Extend DimDate gaplessly through April.
    dates=pd.read_csv(src/'DimDate (1).csv')
    dates['DateKey']=pd.to_numeric(dates.DateKey)
    additions=[]
    for d in pd.date_range('2026-04-01','2026-04-30'):
        k=int(d.strftime('%Y%m%d'))
        if k not in set(dates.DateKey): additions.append(dict(DateKey=k,FullDate=d.strftime('%Y-%m-%d'),Day=d.day,Month=d.month,MonthName=d.strftime('%B'),Quarter='Q2',Year=d.year,DayOfWeek=d.strftime('%A'),IsWeekend='Yes' if d.weekday()>4 else 'No'))
    # Match existing dimension schema and append generated April date rows.
    extra=pd.DataFrame(additions)
    for col in dates.columns:
        if col not in extra.columns: extra[col]=None
    extra=extra.reindex(columns=dates.columns); dates=pd.concat([dates,extra],ignore_index=True); dates.to_csv(out/'DimDate.csv',index=False)
    # New Courier mode and April lanes are inserts. Unknown members stay at -1.
    modes=pd.read_csv(src/'DimMode (1).csv'); courier_key=max(modes.ModeKey)+1
    modes.loc[len(modes)]=[courier_key,'Courier','ShaheenEx','Light (under 1 t)','Parcel / subcontracted truck','No']; modes.to_csv(out/'DimMode.csv',index=False)
    routes=pd.read_csv(src/'DimRoute (1).csv'); route_map={(int(r.OriginCityKey),int(r.DestCityKey)):int(r.RouteKey) for r in routes.itertuples()}
    # Normalize + validate. Parse errors/nulls are rejects; unresolved conformed attributes map to -1.
    rejects=[]; clean=[]; id_seen=set(); samefile=0
    def num(x):
        try: return float(str(x).strip())
        except: return None
    for n,r in st.iterrows():
        if pd.notna(r.get('Structural')) and bool(r.get('Structural')):
            continue
        source=r.Source; rawid=str(r.ShipmentID); sid=rawid.strip().upper()
        if not sid: rejects.append((n,r,'ShipmentID blank')); continue
        # Date truncation handles ISO, DD/MM and timezone timestamps.
        raw_date=str(r.ShipDate).strip()
        valid_shape=(source=='Marine' and re.fullmatch(r'\d{2}/\d{2}/\d{4}',raw_date)) or (source=='Road' and re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw_date)) or (source=='Courier' and re.fullmatch(r'\d{4}-\d{2}-\d{2}T[^ ]+[+-]\d{2}:\d{2}',raw_date)) or (source=='Rail')
        try:
            if not valid_shape: raise ValueError('date shape')
            dt=pd.to_datetime(raw_date,dayfirst=(source=='Marine'),utc=True).tz_convert('Asia/Karachi').normalize().tz_localize(None)
        except: dt=None
        if dt is None or dt.year!=2026 or dt.month!=4: rejects.append((n,r,'ShipDate invalid or outside April 2026')); continue
        w=num(r.WeightRaw)
        if w is None: rejects.append((n,r,'WeightKG is nonnumeric')); continue
        if source=='Rail': w*=1000
        if source=='Courier': w/=1000
        if w<=0: rejects.append((n,r,'WeightKG must be greater than zero')); continue
        cap={'Marine':25000,'Rail':35000,'Road':8000,'Courier':8000}[source]
        if w>cap: rejects.append((n,r,'WeightKG exceeds mode vehicle capacity')); continue
        cost=num(r.CostRaw)
        if cost is None: rejects.append((n,r,'FreightCostPKR is blank or nonnumeric')); continue
        stxt=str(r.StatusRaw).strip(); sk=statusmap.get(stxt.casefold(),-1)
        if source=='Courier': sk={'1':1,'2':2,'3':3}.get(stxt,-1)
        if source=='Courier' and stxt in ('7','9'): sk=-1
        oc=alias.get(str(r.OriginCity).strip(),-1); dc=alias.get(str(r.DestCity).strip(),-1)
        try: oc=int(oc)
        except: oc=-1
        try: dc=int(dc)
        except: dc=-1
        raw_customer=str(r.CustomerID).strip(); customer=customer_alias.get(raw_customer.casefold(),raw_customer)
        customer=customer if customer in cust else ''
        # Exact repeated ID within a source is duplicate; different shipments with shared business key remain.
        ident=(source,sid)
        if ident in id_seen: samefile+=1; clean.append(dict(_remove='same-file duplicate')); continue
        id_seen.add(ident)
        # SCD lookup is effective-date based. Unknown/blank refs use -1.
        ck=-1
        if customer:
            cand=cd[(cd.CustomerID==customer)&(cd.ValidFrom<=dt.strftime('%Y-%m-%d'))&(cd.ValidTo>dt.strftime('%Y-%m-%d'))]
            if len(cand): ck=int(cand.iloc[0].CustomerKey)
        clean.append(dict(Source=source,Locator=r.Locator,ShipmentID=sid,ShipDate=dt.strftime('%Y-%m-%d'),OriginCityKey=oc,DestCityKey=dc,WeightKG=w,FreightCostPKR=cost,StatusKey=sk,CustomerKey=ck,SourceMode=source))
    # Remove second filed representation only when road and courier match same-day shipment signature.
    ready=[x for x in clean if not x.get('_remove')]; gone=set(); sigs={}
    for i,x in enumerate(ready):
        if x['SourceMode'] in ('Road','Courier'):
            sig=(x['ShipDate'],x['OriginCityKey'],x['DestCityKey'],x['WeightKG'],x['CustomerKey'])
            if sig in sigs and {x['SourceMode'],ready[sigs[sig]]['SourceMode']}=={'Road','Courier'}:
                gone.add(i)
            else: sigs[sig]=i
    fact=[]; removed_same=samefile; removed_cross=len(gone)
    for i,x in enumerate(ready):
        if i in gone: continue
        dk=int(x['ShipDate'].replace('-','')); pair=(x['OriginCityKey'],x['DestCityKey']); rk=route_map.get(pair,-1)
        fact.append(dict(DateKey=dk,OriginCityKey=x['OriginCityKey'],DestCityKey=x['DestCityKey'],RouteKey=rk,ModeKey=courier_key if x['SourceMode']=='Courier' else int(modes.loc[modes.ModeName==x['SourceMode'],'ModeKey'].iloc[0]),StatusKey=x['StatusKey'],CustomerKey=x['CustomerKey'],ShipmentID=x['ShipmentID'],WeightKG=x['WeightKG'],FreightCostPKR=x['FreightCostPKR']))
    f=pd.DataFrame(fact)
    new_pairs=sorted(set(zip(f.OriginCityKey,f.DestCityKey))-set(route_map))
    for o,d in new_pairs:
        if o==-1 or d==-1: continue
        on=city_by_key[o].CityName; dn=city_by_key[d].CityName; rk=int(routes.RouteKey.max())+1
        routes.loc[len(routes)]=[rk,o,d,f'{on} -> {dn}','April added lane','New lane']; route_map[(o,d)]=rk
    routes.to_csv(out/'DimRoute.csv',index=False)
    for x in fact:
        x['RouteKey']=route_map.get((x['OriginCityKey'],x['DestCityKey']),-1)
    f=pd.DataFrame(fact); f.insert(0,'ShipmentKey',range(1,len(f)+1)); f.to_csv(out/'FactShipment_April.csv',index=False)
    rej=[]
    for _,r,reason in rejects:
        code={'ShipmentID blank':'BLANK_ID','ShipDate invalid or outside April 2026':'INVALID_DATE','WeightKG is nonnumeric':'WEIGHT_NONNUMERIC','WeightKG must be greater than zero':'WEIGHT_NONPOSITIVE','WeightKG exceeds mode vehicle capacity':'WEIGHT_OVER_CAPACITY','FreightCostPKR is blank or nonnumeric':'COST_NONNUMERIC'}.get(reason,'VALIDATION_ERROR')
        raw={k:(None if pd.isna(v) else str(v)) for k,v in r.to_dict().items()}
        source_file={'Marine':'marine_april.csv','Rail':'rail_april.xlsx','Road':'road_april.csv','Courier':'courier_april.json'}[r.Source]
        rej.append(dict(Source=source_file,Locator=r.Locator,ShipmentID=str(r.ShipmentID).strip().upper(),RawRecord=json.dumps(raw,ensure_ascii=False),ReasonCode=code,ReasonDetail=reason,RejectedAt=datetime.now(timezone.utc).isoformat(timespec='seconds')))
    rej=pd.DataFrame(rej); rej.to_csv(out/'RejectLog_April.csv',index=False)
    # Integrated fact reuses untouched Feb/March fact rows exactly.
    feb=pd.read_csv(src/'FactShipment_Feb.csv'); mar=pd.read_csv(src/'FactShipment_March.csv'); old=pd.concat([feb,mar],ignore_index=True)
    april=f.drop(columns='ShipmentKey').copy(); april.insert(0,'ShipmentKey',range(int(old.ShipmentKey.max())+1,int(old.ShipmentKey.max())+1+len(april)))
    integrated=pd.concat([old,april],ignore_index=True); integrated.to_csv(out/'FactShipment_FebToApril.csv',index=False)
    # Useful machine-readable quality summary and assertions.
    summary={'staging_rows':len(st),'reject_rows':len(rej),'same_file_duplicates':removed_same,'cross_carrier_duplicates':removed_cross,'april_rows':len(f),'april_weight_kg':float(f.WeightKG.sum()),'april_cost_pkr':float(f.FreightCostPKR.sum()),'quarter_rows':len(integrated),'quarter_weight_kg':float(integrated.WeightKG.sum()),'quarter_cost_pkr':float(integrated.FreightCostPKR.sum()),'unknown_city_rows':int(((f.OriginCityKey==-1)|(f.DestCityKey==-1)).sum()),'unknown_status_rows':int((f.StatusKey==-1).sum()),'unknown_customer_rows':int((f.CustomerKey==-1).sum()),'dimcustomer_rows':len(cd),'dimdate_rows':len(dates),'route_rows':len(routes),'identity':len(st)-len(rej)-removed_same-removed_cross-len(f)}
    (out/'load_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8'); print(json.dumps(summary,indent=2))
    # Required checks are deliberately explicit and loud on mismatch.
    assert summary['staging_rows']==1805
    assert summary['reject_rows']==35 and summary['april_rows']==1700
    assert summary['april_weight_kg']==17915700 and summary['april_cost_pkr']==158037000
    assert summary['quarter_rows']==2934 and summary['quarter_weight_kg']==36036400 and summary['quarter_cost_pkr']==309882000
    assert summary['identity']==0 and summary['dimcustomer_rows']==47 and summary['dimdate_rows']==120
    assert (f.OriginCityKey==-1).sum()+(f.DestCityKey==-1).sum()>=18

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source-dir',type=Path,default=Path(r'C:\Users\HP\Downloads\Week7DataWarehousing')); p.add_argument('--output-dir',type=Path,default=Path(__file__).parent); a=p.parse_args(); main(a.source_dir,a.output_dir)
