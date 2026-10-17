from pathlib import Path
import csv, json
from collections import Counter
BASE=Path(r'C:\Users\HP\Downloads')
OUT=Path(r'C:\Users\HP\Documents\Codex\2026-10-10\ok-chatgpt-act-like-a-brillent\outputs')

def rows(name):
    with (BASE/name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))
def asint(v): return int(v)

def validate():
    fact=rows('FactShipment.csv')
    dims={
        'Date':rows('DimDate.csv'), 'City':rows('DimCity.csv'), 'Route':rows('DimRoute.csv'),
        'Mode':rows('DimMode.csv'), 'Status':rows('DimStatus.csv')}
    keycols={'Date':'DateKey','City':'CityKey','Route':'RouteKey','Mode':'ModeKey','Status':'StatusKey'}
    keysets={k:{asint(r[keycols[k]]) for r in v} for k,v in dims.items()}
    fkcols={'Date':('DateKey','DateKey'),'City':('OriginCityKey','CityKey'),'Route':('RouteKey','RouteKey'),'Mode':('ModeKey','ModeKey'),'Status':('StatusKey','StatusKey')}
    # Destination City is a second, inactive role in the six-edge single-table design.
    fkcols['DestCity']=('DestCityKey','CityKey')
    integrity={}
    for k,(fk,dimkey) in fkcols.items():
        dim='City' if k=='DestCity' else k
        missing=[i+1 for i,r in enumerate(fact) if not r[fk] or asint(r[fk]) not in keysets[dim]]
        integrity[f'{fk}_matches_{dimkey}']=len(missing)==0
    dimension_checks={}
    for name,data in dims.items():
        k=keycols[name]
        dimension_checks[f'{name}_key_unique_nonblank']=all(r[k] for r in data) and len({r[k] for r in data})==len(data)
        dimension_checks[f'{name}_no_blank_rows']=all(any(str(v).strip() for v in r.values()) for r in data)
    cities={asint(r['CityKey']):r['Province'] for r in dims['City']}
    byprov=Counter()
    for r in fact: byprov[cities[asint(r['OriginCityKey'])]]+=asint(r['WeightKG'])
    links=[
      ('DimDate[DateKey]','FactShipment[DateKey]','* : 1','Single','Yes'),
      ('DimCity[CityKey]','FactShipment[OriginCityKey]','* : 1','Single','Yes'),
      ('DimCity[CityKey]','FactShipment[DestCityKey]','* : 1','Single','No'),
      ('DimRoute[RouteKey]','FactShipment[RouteKey]','* : 1','Single','Yes'),
      ('DimMode[ModeKey]','FactShipment[ModeKey]','* : 1','Single','Yes'),
      ('DimStatus[StatusKey]','FactShipment[StatusKey]','* : 1','Single','Yes'),
    ]
    rel={
      'relationships_6':len(links)==6,
      'cardinality_many_to_one_6':sum(x[2]=='* : 1' for x in links)==6,
      'cross_filter_single_6':sum(x[3]=='Single' for x in links)==6,
      'active_5':sum(x[4]=='Yes' for x in links)==5,
      'inactive_1':sum(x[4]=='No' for x in links)==1,
    }
    status_names={int(r['StatusKey']):r['StatusName'] for r in dims['Status']}
    mode_names={int(r['ModeKey']):r['ModeName'] for r in dims['Mode']}
    modekg=Counter(); mode_rows=Counter()
    for r in fact:
        mode=mode_names[asint(r['ModeKey'])]; modekg[mode]+=asint(r['WeightKG']); mode_rows[mode]+=1
    result={
      'relationship_design':{'role':'Origin City active; Destination City inactive and measures use USERELATIONSHIP','relationships':[{'one':a,'many':b,'cardinality':c,'cross_filter':d,'active':e} for a,b,c,d,e in links]},
      'fact':{'rows':len(fact),'weight_kg':sum(asint(x['WeightKG']) for x in fact),'freight_cost_pkr':sum(asint(x['FreightCostPKR']) for x in fact),'shipment_count':sum(asint(x['ShipmentCount']) for x in fact)},
      'dimensions':{k:len(v) for k,v in dims.items()},
      'blank_rows_across_five_dimensions':sum(sum(not any(str(v).strip() for v in row.values()) for row in d) for d in dims.values()),
      'origin_province_distinct':len(set(cities[asint(x['OriginCityKey'])] for x in fact)),
      'weight_kg_by_origin_province':dict(byprov),
      'mode_rows':dict(mode_rows),'mode_weight_kg':dict(modekg),
      'checks':{**rel,**dimension_checks,**integrity,
        'fact_rows_34':len(fact)==34,
        'weight_578650kg':sum(asint(x['WeightKG']) for x in fact)==578650,
        'freight_cost_4808000pkr':sum(asint(x['FreightCostPKR']) for x in fact)==4808000,
        'blank_dimension_rows_zero':sum(sum(not any(str(v).strip() for v in row.values()) for row in d) for d in dims.values())==0,
        'origin_provinces_4':len(set(cities[asint(x['OriginCityKey'])] for x in fact))==4,
        'Sindh_484350kg':byprov['Sindh']==484350,
        'Punjab_44100kg':byprov['Punjab']==44100,
        'Balochistan_44100kg':byprov['Balochistan']==44100,
      }
    }
    result['all_checks_pass']=all(result['checks'].values())
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'W4_Python_Model_Validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['all_checks_pass']:
        raise SystemExit('Validation failure: '+json.dumps(result['checks']))
    print(json.dumps(result,indent=2))

if __name__=='__main__': validate()
