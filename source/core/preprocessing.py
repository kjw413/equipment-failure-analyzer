from __future__ import annotations
import re, json, hashlib, math
from datetime import date, datetime, time, timedelta
from typing import Any
import numpy as np
import pandas as pd
from openpyxl.utils.datetime import from_excel
from core.i18n import K
from core.models import LoadedData, AnalysisOptions, UserError, Progress, noop_progress
from core.classifier import RuleClassifier
from core.review_guidance import guidance
from core.equipment_names import resolve_name, code_key

RECORD_COLUMNS = ['record_id','event_id','source_row','source_sheet','date','start','end','minutes',
 'elapsed_minutes','duration_delta','duration_source','kind','line','registered','target','family',
 'equipment','equipment_basis','equipment_code','raw_equipment_name','report_equipment','name_mapped','product','raw_description','normalized','raw_cause','raw_action',
 'raw_big','raw_mid','raw_small','major','middle','minor','type','status','evidence','candidates',
 'issues','review_reason','review_action','aggregation_effect','duplicate']

def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value,str):
        return value.strip().casefold() in ('','nan','nat','none','null')
    try:
        return bool(pd.isna(value))
    except (ValueError,TypeError):
        return False

def text(value: Any) -> str:
    return '' if is_missing(value) else str(value).strip()

def normalize(value: Any, replacements: dict[str,str] | None = None) -> str:
    result = re.sub(r'\s+',' ',text(value).casefold()).strip()
    ordered = sorted((replacements or {}).items(),key=lambda t:-len(t[0]))
    # A few passes let one fix enable another ('솔레노이드 벨브' -> '솔레노이드 밸브' -> '솔밸브').
    for _ in range(3):
        before = result
        for old,new in ordered:
            result=result.replace(old.casefold(),new.casefold())
        if result == before:
            break
    return result

# A clause ends at a line break, slash, bracket, arrow, sentence period or ' - '.
CLAUSE_END = r'(?=\s*(?:$|[\n\r/;|*()\[\]→,]|->|=>|>>|\.(?!\d)|\s-\s))'
# Real words that end in '교'; never expanded to '…교체'.
ENDING_STOPWORDS = {'비교','학교','종교','외교','선교','설교'}

def expand_endings(value: str, endings: dict[str,str] | None) -> str:
    """Restore clause-final syllables cut short in the MES field ('후크 교' -> '후크 교체').

    Only a lone final syllable is expanded, plus a final '교' attached to a noun.
    """
    if not value or not endings:
        return value
    keys='|'.join(map(re.escape,sorted(endings,key=len,reverse=True)))
    result=re.sub(rf'(?:^|(?<=[\s/;|*(\[]))({keys}){CLAUSE_END}',lambda m:endings[m.group(1)],value,flags=re.M)
    if '교' in endings:
        result=re.sub(rf'([가-힣]+)교{CLAUSE_END}',
                      lambda m:m.group(0) if m.group(0) in ENDING_STOPWORDS else m.group(1)+endings['교'],result,flags=re.M)
    return result

def prepare_text(value: Any, normalization: dict | None) -> str:
    """Normalized, classification-ready text; the raw source text is kept separately."""
    settings=normalization or {}
    return expand_endings(normalize(value,settings.get('replacements',{})),settings.get('clause_end_expansions',{}))

def parse_date(value: Any) -> pd.Timestamp:
    if is_missing(value):
        return pd.NaT
    if isinstance(value,(datetime,date,pd.Timestamp)):
        return pd.Timestamp(value).tz_localize(None) if pd.Timestamp(value).tzinfo else pd.Timestamp(value)
    if isinstance(value,(int,float,np.number)) and not isinstance(value,bool):
        if not math.isfinite(float(value)):
            return pd.NaT
        if 20000101 <= value <= 20991231 and float(value).is_integer():
            return pd.to_datetime(str(int(value)),format='%Y%m%d',errors='coerce')
        if 1 <= value < 100000:
            dt=from_excel(float(value))
            return pd.Timestamp(dt) if isinstance(dt,datetime) else pd.NaT
        return pd.NaT
    s=text(value).replace('\ub144','-').replace('\uc6d4','-').replace('\uc77c','').strip()
    try:
        result=pd.to_datetime(s,errors='coerce',format='mixed')
        if pd.isna(result):return pd.NaT
        return result.tz_localize(None) if result.tzinfo else result
    except (ValueError,TypeError,OverflowError):
        return pd.NaT

def is_time_only(value: Any) -> bool:
    return isinstance(value,time) or bool(re.fullmatch(r'\d{1,2}:\d{2}(?::\d{2})?',text(value)))

def parse_stamp(value: Any, day: pd.Timestamp) -> pd.Timestamp:
    if not is_time_only(value):
        return parse_date(value)
    if pd.isna(day):
        return pd.NaT
    if isinstance(value,time):
        return pd.Timestamp(datetime.combine(day.date(),value))
    parts=[int(x) for x in text(value).split(':')]
    if parts[0]>23 or parts[1]>59 or (len(parts)>2 and parts[2]>59):
        return pd.NaT
    return day.normalize()+timedelta(hours=parts[0],minutes=parts[1],seconds=parts[2] if len(parts)>2 else 0)

def parse_duration(value: Any, unit: str = 'minutes') -> float | None:
    factors={'minutes':1.0,'hours':60.0,'seconds':1/60,'excel_days':1440.0}
    if unit not in factors:raise UserError('Unknown duration unit')
    if is_missing(value):return None
    if isinstance(value,(timedelta,pd.Timedelta)):
        v=value.total_seconds()/60
    elif isinstance(value,time):
        v=value.hour*60+value.minute+value.second/60
    elif isinstance(value,(int,float,np.number)) and not isinstance(value,bool):
        v=float(value)*factors[unit]
    else:
        s=text(value).lower().replace(',','').replace(' ','')
        if re.fullmatch(r'\d+(?:\.\d+)?',s):
            v=float(s)*factors[unit]
        elif re.fullmatch(r'\d+:\d{2}(?::\d{2})?',s):
            p=[int(x) for x in s.split(':')]
            if p[1]>59 or (len(p)>2 and p[2]>59):return None
            v=p[0]*60+p[1]+(p[2]/60 if len(p)>2 else 0)
        else:
            pattern=r'(\d+(?:\.\d+)?)(\uc2dc\uac04|\ubd84|\ucd08|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)'
            parts=list(re.finditer(pattern,s))
            if not parts or ''.join(m.group(0) for m in parts)!=s:return None
            v=0.0
            for m in parts:
                n=float(m.group(1));u=m.group(2)
                v+=n*(60 if u in ('\uc2dc\uac04','h','hour','hours','hr','hrs') else 1/60 if u in ('\ucd08','s','second','seconds','sec','secs') else 1)
    return float(v) if math.isfinite(v) and v>=0 else None

def normalized_name(value: Any, aliases: dict[str,str]) -> str:
    s=re.sub(r'\s+',' ',text(value)).strip()
    lookup={normalize(k):str(v).strip() for k,v in aliases.items()}
    return lookup.get(normalize(s),s) or K['missing']

def family_candidate(reported: str, description: str, families: list[dict]) -> str:
    # Prefer explicitly reported equipment. Free text is only a candidate, never an asset ID.
    for source in ([reported,description] if reported else [description]):
        names=[r['name'] for r in families if re.search(r['pattern'],source,re.I)]
        if names:return ' / '.join(dict.fromkeys(names))
    return K['unclassified']

EVENT_FIELDS = ('line_id','line_name','equipment_id','equipment_name','start','end','work_date','description',
                'kind','code_big','code_mid','code_small','duration','product_name')

def event_id_for(raw: dict, mapping: dict) -> str:
    """Stable identity of one source record; manual corrections are keyed by it.

    Saved corrections depend on this exact formula: do not change fields or order.
    """
    payload=[text(raw.get(mapping.get(key,''))) for key in EVENT_FIELDS]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()

def event_ids(loaded: LoadedData, mapping: dict) -> list[str]:
    """Record IDs of every source row under a given column mapping."""
    return [event_id_for(raw,mapping) for raw in loaded.frame.to_dict('records')]

def review_target(settings: dict, options: AnalysisOptions) -> bool:
    """A missing failure target only matters when equipment is grouped by target."""
    return settings.get('target_missing_review','target_basis')=='always' or options.equipment_basis=='target'

def standardize(loaded: LoadedData, config: dict, options: AnalysisOptions,
                progress: Progress = noop_progress) -> pd.DataFrame:
    m=loaded.mapping.copy()
    if not any(m.get(k) for k in ('equipment_id','equipment_name','line_name','line_id','code_mid')):
        raise UserError(K['missing_equipment'])
    for key,column in m.items():
        if column is not None and column not in loaded.headers:
            raise UserError(f'{key}: \uceec\ub7fc\uc744 \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694.')
    settings=config['settings'];classifier=RuleClassifier(config['rules'],settings.get('classifier'))
    target_review=review_target(settings,options)
    fault_labels={normalize(v) for v in settings['fault_labels']}
    rows=[]
    for index,raw in enumerate(loaded.frame.to_dict('records')):
        def get(key):return raw.get(m.get(key,''))
        issues=[]
        original_kind=text(get('kind'))
        kind=original_kind or settings['kind_codes'].get(text(get('kind_code')),'')
        if normalize(kind) in fault_labels:kind=K['fault']
        if not kind:
            if not m.get('kind') and not m.get('kind_code') and settings.get('assume_generic_is_failure',False):
                kind=K['fault'];issues.append(K['kind_assumed'])
            else:
                kind=K['missing'];issues.append(K['no_kind'])
        dt=parse_date(get('work_date'))
        start=parse_stamp(get('start'),dt);end=parse_stamp(get('end'),dt)
        if pd.isna(dt) and not pd.isna(start):dt=start.normalize()
        if pd.isna(dt):issues.append(K['date_invalid'])
        elapsed=None
        if not pd.isna(start) and not pd.isna(end):
            if end<start and is_time_only(get('start')) and is_time_only(get('end')) and settings.get('allow_time_only_overnight',False):
                end+=timedelta(days=1);issues.append(K['overnight'])
            if end<start:issues.append(K['time_negative'])
            else:elapsed=(end-start).total_seconds()/60
        supplied=parse_duration(get('duration'),options.duration_unit)
        minutes=supplied
        source=K['supplied'] if supplied is not None else K['unknown']
        if supplied is None and not is_missing(get('duration')):issues.append(K['time_invalid'])
        if supplied is None and elapsed is not None:
            minutes=elapsed;source=K['calculated']
        if minutes is None:issues.append(K['time_missing'])
        delta=supplied-elapsed if supplied is not None and elapsed is not None else None
        if delta is not None and abs(delta)>float(settings['duration_tolerance_minutes']):issues.append(K['time_diff'])
        line=normalized_name(get('line_name') or get('line_id'),{})
        # NaN is truthy: fall back explicitly rather than relying on Python's 'or'.
        if line==K['missing']:line=normalized_name(get('line_id'),{})
        registered=normalized_name(get('equipment_name'),config['equipment_aliases'])
        raw_equipment_name = text(get('equipment_name'))
        equipment_code = text(get('equipment_id'))
        report_equipment, name_mapped = resolve_name(equipment_code, raw_equipment_name, config.get('equipment_names', {}).get('mappings', {}))
        raw_mid=text(get('code_mid'))
        if loaded.profile=='mes_downtime_v1':
            target=normalized_name(raw_mid,config['equipment_aliases']) if re.search(settings['equipment_prefix_pattern'],raw_mid) else K['target_missing']
            target_basis=K['raw_mid'] if target!=K['target_missing'] else K['target_missing']
        else:
            target=normalized_name(raw_mid,config['equipment_aliases']) if raw_mid and m.get('code_mid')=='\uace0\uc7a5\ub300\uc0c1\uc124\ube44' else registered
            target_basis=K['registered'] if target==registered else K['raw_mid']
            if target==K['missing']:target=K['target_missing']
        description=text(get('description'));cause=text(get('cause'));action=text(get('action'))
        norm=prepare_text(description,config['normalization'])
        combined=prepare_text(' | '.join(v for v in (description,cause,action) if v),config['normalization'])
        product=normalized_name(get('product_name'),config['product_aliases'])
        event_id=event_id_for(raw,m)
        override=config.get('overrides',{}).get(event_id,{})
        classification=classifier.classify(combined,text(get('code_small'))) if kind==K['fault'] else {
            'major':K['nonfault'],'middle':K['nonfault'],'minor':K['nonfault'],'status':K['nonfault'],'evidence':'','candidates':''}
        if all(override.get(k) for k in ('major','middle','minor')):
            classification.update({k:override[k] for k in ('major','middle','minor')})
            classification.update(status=K['manual'],evidence=K['manual'],candidates='')
        if override.get('product'):product=override['product']
        if override.get('work_date'):
            new_date=parse_date(override['work_date'])
            if not pd.isna(new_date):
                dt=new_date.normalize()
                issues=[i for i in issues if i!=K['date_invalid']]
        if override.get('minutes') not in (None,''):
            try:
                revised=float(override['minutes'])
                if math.isfinite(revised) and revised>=0:
                    minutes=revised;source=K['manual']
                    issues=[i for i in issues if i not in (K['time_invalid'],K['time_missing'],K['time_diff'])]
            except (TypeError,ValueError):pass
        if override.get('target'):target=override['target'];target_basis=K['manual']
        family=family_candidate(target if target!=K['target_missing'] else '',combined,config['equipment_families'])
        if kind==K['fault']:
            if target==K['target_missing']:issues.append(K['target_missing'])
            if not combined:issues.append(K['no_text'])
            if classification['status']==K['review']:issues.append(K['multi_rule'])
        equipment={'mapped':report_equipment,'registered':registered,'target':target,'family':family}[options.equipment_basis]
        if options.equipment_basis=='target' and target==K['target_missing']:
            equipment=f'{line} / {K["target_missing"]}'
        source_row=int(raw['__source_row'])
        record={'record_id':f'{loaded.file_hash[:16]}:{loaded.sheet}:{source_row}','event_id':event_id,
          'source_row':source_row,'source_sheet':loaded.sheet,'date':dt.normalize() if not pd.isna(dt) else pd.NaT,
          'start':start,'end':end,'minutes':minutes,'elapsed_minutes':elapsed,'duration_delta':delta,'duration_source':source,
          'kind':kind,'line':line,'registered':registered,'target':target,'family':family,'equipment':equipment,
          'equipment_code':equipment_code,'raw_equipment_name':raw_equipment_name,'report_equipment':report_equipment,'name_mapped':name_mapped,
          'equipment_basis':target_basis if options.equipment_basis=='target' else K[options.equipment_basis],
          'product':product,'raw_description':description,'normalized':norm,'raw_cause':cause,'raw_action':action,
          'raw_big':text(get('code_big')),'raw_mid':raw_mid,'raw_small':text(get('code_small')),
          **classification,'type':' / '.join(classification[k] for k in ('major','middle','minor')),
          'issues':' | '.join(dict.fromkeys(issues)),'duplicate':False}
        reason,action,effect=guidance(record,target_review)
        record.update(review_reason=reason,review_action=action,aggregation_effect=effect)
        rows.append(record)
        if index % 200==0:progress(10+int(65*(index+1)/max(1,len(loaded.frame))),K['processing'])
    result=pd.DataFrame(rows,columns=RECORD_COLUMNS)
    if not result.empty:
        identities = result[['equipment_code', 'raw_equipment_name', 'report_equipment']].copy()
        identities['_key'] = [code_key(c) or code_key(n) for c,n in zip(identities.equipment_code,identities.raw_equipment_name)]
        identities['_display'] = identities.report_equipment.astype(str).str.casefold()
        clashes = identities.groupby('_display')['_key'].nunique()
        if (clashes > 1).any():
            raise UserError('\uc11c\ub85c \ub2e4\ub978 \uc124\ube44 \ucf54\ub4dc\uac00 \uac19\uc740 \ud45c\uc2dc\uba85\uc73c\ub85c \ubcc0\ud658\ub429\ub2c8\ub2e4. \uc124\ube44\uba85 \ubcc0\ud658 \uc124\uc815\uc5d0\uc11c \uc774\ub984\uc744 \uad6c\ubd84\ud558\uc138\uc694.')
    for key in ('minutes','elapsed_minutes','duration_delta'):
        result[key]=pd.to_numeric(result[key],errors='coerce')
    for key in ('date','start','end'):
        result[key]=pd.to_datetime(result[key],errors='coerce')
    if not result.empty:
        result['duplicate']=result.duplicated('event_id',keep=False)
    return result
