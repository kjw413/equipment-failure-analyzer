from __future__ import annotations
import math, re
import pandas as pd
from core.i18n import K
from core.sorting import descending
from core.models import AnalysisOptions, AnalysisResult, LoadedData
from core.preprocessing import review_target
from core.review_guidance import review_issues

STAT_COLUMNS=['count','count_share','valid_count','total_minutes','mean_minutes','max_minutes','time_share','top_type','top_equipment']

def mode_text(series: pd.Series) -> str:
    counts=series.value_counts(dropna=False)
    return str(counts.index[0]) if len(counts) else ''

def grouped(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    columns=keys+STAT_COLUMNS
    if df.empty:return pd.DataFrame(columns=columns)
    groups=df.groupby(keys,dropna=False,sort=True,observed=True)
    agg=groups.agg(count=('record_id','size'),valid_count=('minutes','count'),
                   total_minutes=('minutes',lambda s:s.sum(min_count=1)),mean_minutes=('minutes','mean'),
                   max_minutes=('minutes','max'),top_type=('type',mode_text),top_equipment=('equipment',mode_text)).reset_index()
    agg['count_share']=agg['count']/len(df)
    denominator=df['minutes'].sum(min_count=1)
    agg['time_share']=agg['total_minutes']/denominator if pd.notna(denominator) and denominator>0 else float('nan')
    return descending(agg[columns], 'total_minutes')

def select_records(records: pd.DataFrame, options: AnalysisOptions) -> pd.DataFrame:
    selected=records.copy()
    if options.scope=='fault':selected=selected.loc[selected['kind'].eq(K['fault'])]
    elif options.scope!='all':raise ValueError('Unknown scope')
    if options.date_from:selected=selected.loc[selected['date'].ge(pd.Timestamp(options.date_from).normalize())]
    if options.date_to:selected=selected.loc[selected['date'].le(pd.Timestamp(options.date_to).normalize())]
    if options.deduplicate:selected=selected.drop_duplicates('event_id',keep='first')
    return selected.reset_index(drop=True)

def trend(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    valid=df.loc[df['date'].notna()].copy()
    if valid.empty:return pd.DataFrame(columns=['period',*STAT_COLUMNS])
    if freq=='day':valid['period']=valid['date'].dt.strftime('%Y-%m-%d');periods=pd.date_range(valid['date'].min(),valid['date'].max(),freq='D').strftime('%Y-%m-%d')
    elif freq=='week':
        starts=valid['date'].dt.to_period('W-SUN').dt.start_time
        valid['period']=starts.dt.strftime('%Y-%m-%d');periods=pd.date_range(starts.min(),starts.max(),freq='W-MON').strftime('%Y-%m-%d')
    elif freq=='year':valid['period']=valid['date'].dt.strftime('%Y');periods=[str(y) for y in range(valid['date'].min().year,valid['date'].max().year+1)]
    else:valid['period']=valid['date'].dt.strftime('%Y-%m');periods=pd.period_range(valid['date'].min(),valid['date'].max(),freq='M').astype(str)
    table=grouped(valid,['period']).set_index('period').reindex(periods)
    for col in ('count','valid_count'):
        table[col]=table[col].fillna(0).astype(int)
    empty=table['count'].eq(0)
    table.loc[empty,['total_minutes','count_share','time_share']]=0
    table.loc[empty,['top_type','top_equipment']]=''
    table.index.name='period'
    return descending(table.reset_index(), 'total_minutes')

def analyze(loaded: LoadedData, records: pd.DataFrame, config: dict, options: AnalysisOptions) -> AnalysisResult:
    if options.date_from and options.date_to and options.date_from>options.date_to:
        raise ValueError('Date range is reversed')
    d=select_records(records,options)
    known_products=d.loc[d['product'].ne(K['missing'])]
    tables={
      'equipment':grouped(d,['equipment']), 'line':grouped(d,['line']),
      'product':grouped(d,['product']) if len(known_products) else grouped(d.iloc[:0],['product']),
      'type':grouped(d,['type']), 'raw_kind':grouped(records,['kind']),
      'equipment_type':grouped(d,['equipment','type']), 'product_type':grouped(d,['product','type']),
      'equipment_product':grouped(d,['equipment','product']),
      'triple':grouped(d,['equipment','product','type']),
      **{f'trend_{f}':trend(d,f) for f in ('day','week','month','year')},
      'long_stops':descending(d, 'minutes').head(options.top_n).copy(),
    }
    valid_count=int(d['minutes'].count())
    total=float(d['minutes'].sum(min_count=1)) if valid_count else None
    def period_of(frame):
        dates=frame['date'].dropna()
        return f'{dates.min():%Y-%m-%d} ~ {dates.max():%Y-%m-%d}' if len(dates) else K['unknown']
    flagged=[re.escape(K[key]) for key in review_issues(review_target(config['settings'],options))]
    review_mask=d['status'].isin([K['review'],K['unclassified']]) | d['issues'].str.contains('|'.join(flagged),regex=True,na=False)
    review_columns=['source_row','raw_description','review_reason','review_action','aggregation_effect',
                    'status','type','minutes','target','issues','candidates']
    review_frame=d.loc[review_mask]
    tables['review']=descending(review_frame[review_columns+[c for c in review_frame.columns if c not in review_columns]], 'minutes')
    metrics={'source_rows':len(records),'selected_rows':len(d),'excluded_rows':len(records)-len(d),
       'fault_rows_source':int(records['kind'].eq(K['fault']).sum()),'valid_time_rows':valid_count,
       'total_minutes':total,'mean_minutes':float(d['minutes'].mean()) if valid_count else None,
       'max_minutes':float(d['minutes'].max()) if valid_count else None,
       'mapped_name_rows':int(d['name_mapped'].sum()),'equipment_count':int(d['equipment'].nunique()),
       'line_count':int(d.loc[d['line'].ne(K['missing']),'line'].nunique()),
       'registered_count':int(d.loc[d['registered'].ne(K['missing']),'registered'].nunique()),
       'target_count':int(d.loc[~d['target'].isin([K['missing'],K['target_missing']]),'target'].nunique()),
       'missing_target_rows':int(d['target'].eq(K['target_missing']).sum()),
       'product_count':int(known_products['product'].nunique()),
       'auto_rows':int(d['status'].eq(K['auto']).sum()),'manual_rows':int(d['status'].eq(K['manual']).sum()),
       'unclassified_rows':int(d['status'].eq(K['unclassified']).sum()),'ambiguous_rows':int(d['status'].eq(K['review']).sum()),
       'auto_resolved_rows':int((d['status'].eq(K['auto'])&d['evidence'].str.contains(K['auto_resolved'],regex=False,na=False)).sum()),
       'review_rows':int(review_mask.sum()),'date_missing_rows':int(d['date'].isna().sum()),
       'duplicate_candidate_rows':int(d['duplicate'].sum()),'period':period_of(d),'source_period':period_of(records)}
    notes=[K['names_note'],K['record_note'],K['no_cause'],K['time_note'],K['exposure_note'],K['fuzzy_note']]
    if loaded.profile=='mes_downtime_v1':notes.extend([K['reported_note'],K['rounding_note']])
    if not loaded.mapping.get('kind') and not loaded.mapping.get('kind_code') and config['settings'].get('assume_generic_is_failure',False):notes.append(K['kind_assumed'])
    if metrics['date_missing_rows']:notes.append(f'{K["date_invalid"]}: {metrics["date_missing_rows"]} / {K["trend_tab"]} \uc81c\uc678')
    if options.equipment_basis=='family':notes.append('\uc124\ube44\uad70\uc740 \ud0a4\uc6cc\ub4dc \uae30\ubc18 \ud6c4\ubcf4\uc774\uba70 \ud655\uc815 \uc124\ube44\uac00 \uc544\ub2d9\ub2c8\ub2e4.')
    if not total:notes.append(K['zero_total'])
    return AnalysisResult(loaded,records,d,tables,options,metrics,notes,config['hash'],config)
