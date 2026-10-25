"""Deterministic risk matrix. No AI calls, DB writes, or operation-judgment changes.

Policies are trusted server configuration, never model output. The bundled
policy is deliberately inactive until the domain rules and window are reviewed.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

METHOD = 'vehicle-risk-matrix-v1'
MATRIX = {'high': {'small':'medium','medium':'high','large':'high'},
          'medium': {'small':'low','medium':'medium','large':'high'},
          'low': {'small':'low','medium':'low','large':'medium'}}
LABELS={'low':'低','medium':'中','high':'高','unassessed':'未評価'}
DEFAULT_POLICY={'version':'draft-20261025','status':'draft','reviewed_by':'',
                'window_days':None,'rules':[]}


def load_policy():
    path=Path(__file__).with_name('vehicle_risk_policy.json')
    if not path.is_file():return deepcopy(DEFAULT_POLICY)
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else deepcopy(DEFAULT_POLICY)
    except (OSError,ValueError):return deepcopy(DEFAULT_POLICY)


def matrix_level(severity, likelihood):
    """Pure ordinal lookup; unknown is not zero or low."""
    return MATRIX.get(likelihood,{}).get(severity,'unassessed')


def snapshot_hash(source):
    return hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False,
                                     separators=(',',':'),default=str).encode()).hexdigest()


def _date(value):
    if not isinstance(value,str):return None
    try:return date.fromisoformat(value[:10])
    except ValueError:return None


def _path(source, path):
    value=source
    if not isinstance(path,str):return None
    for key in path.split('.'):
        if not isinstance(value,dict) or key not in value:return None
        value=value[key]
    return value


def _matches(source, predicate):
    path=predicate.get('path');op=predicate.get('op');expected=predicate.get('value')
    if not isinstance(path,str) or not path or any(k.startswith('_') for k in path.split('.')):return False
    value=_path(source,path)
    if value is None:return False
    if op=='eq':return type(value) is type(expected) and value==expected
    if op in ('gte','lte'):
        if type(value) not in (int,float) or type(expected) not in (int,float):return False
        import math
        if not math.isfinite(value) or not math.isfinite(expected):return False
        return value>=expected if op=='gte' else value<=expected
    return False


def _axis(dimension, item, sources, policy, as_of):
    allowed={'severity':{'small','medium','large'},'likelihood':{'low','medium','high'}}[dimension]
    matches=[]
    for rule in policy.get('rules',[]):
        if not isinstance(rule,dict) or rule.get('dimension')!=dimension or rule.get('status')!='approved':continue
        if rule.get('level') not in allowed or not isinstance(rule.get('id'),str) or not rule['id']:continue
        # Rules must identify a failure scenario, not just a component name.
        if rule.get('target')!=item.get('target') or rule.get('risk_condition')!=item.get('risk_condition') or rule.get('risk_effect')!=item.get('risk_effect'):continue
        predicates=rule.get('all')
        if not isinstance(predicates,list) or not predicates:continue
        references=[];valid=True
        for predicate in predicates:
            if not isinstance(predicate,dict):valid=False;break
            sid=predicate.get('source_id');source=sources.get(sid) if isinstance(sid,str) else None
            if sid not in item.get('source_ids',[]) or not isinstance(source,dict) or not _matches(source,predicate):valid=False;break
            # Current source bytes must match what the reviewed rule was based on.
            if snapshot_hash(source)!=predicate.get('snapshot_hash'):valid=False;break
            references.append(sid)
            if dimension=='likelihood':
                observed=_date(_path(source,predicate.get('observed_at_path','date')))
                age=rule.get('max_age_days')
                if type(age) is not int or age<0 or observed is None or not 0<=(as_of-observed).days<=age:valid=False;break
                if sid.startswith('knowledge:'):valid=False;break
        if valid:
            matches.append({'level':rule['level'],'rule_id':rule['id'],'source_ids':sorted(set(references))})
    if not matches:return {'level':'unknown','reason':'no_applicable_reviewed_rule','rule_ids':[],'source_ids':[]}
    if len({m['level'] for m in matches})!=1:return {'level':'unknown','reason':'conflicting_rules','rule_ids':[m['rule_id'] for m in matches],'source_ids':[]}
    return {'level':matches[0]['level'],'reason':'reviewed_rule_matched','rule_ids':[m['rule_id'] for m in matches],
            'source_ids':sorted({sid for m in matches for sid in m['source_ids']})}


def evaluate_scenario(item, sources, context, policy=None):
    policy=deepcopy(policy if policy is not None else DEFAULT_POLICY)
    as_of=_date(context.get('as_of')) or datetime.now(timezone.utc).date()
    unknown={'level':'unknown','reason':'policy_not_approved','rule_ids':[],'source_ids':[]}
    result={'method':METHOD,'policy_version':policy.get('version'),'policy_status':policy.get('status'),
            'evaluated_at':as_of.isoformat(),'as_of':as_of.isoformat(),
            'window_days':policy.get('window_days'),'severity':deepcopy(unknown),'likelihood':deepcopy(unknown),
            'level':'unassessed','label':'未評価','reason':'policy_not_approved',
            'response_priority':{'label':'要確認','tone':'','basis':'risk_unassessed'},
            'deadline_status':'separate','human_reviewed_by':policy.get('reviewed_by') or None}
    if policy.get('status')=='approved' and isinstance(policy.get('reviewed_by'),str) and policy['reviewed_by'].strip():
        window=policy.get('window_days')
        scope=isinstance(context.get('company_code'),str) and bool(context['company_code']) and type(context.get('vehicle_id')) is int and context['vehicle_id']>0 and policy.get('company_code')==context['company_code'] and policy.get('vehicle_id')==context['vehicle_id']
        if not scope:result['reason']='policy_scope_mismatch'
        elif type(window) is not int or window<=0:result['reason']='evaluation_window_not_defined'
        elif context.get('is_current') is not True:result['reason']='input_freshness_unverified'
        elif item.get('risk_status')!='supported' or item.get('risk_basis')=='general_knowledge':result['reason']='scenario_not_supported_by_recorded_evidence'
        else:
            for axis in ('severity','likelihood'):result[axis]=_axis(axis,item,sources,policy,as_of)
            result['level']=matrix_level(result['severity']['level'],result['likelihood']['level'])
            result['label']=LABELS[result['level']]
            result['reason']='matrix_calculated' if result['level']!='unassessed' else 'dimension_not_assessed'
            if result['level']!='unassessed':result['response_priority']={
                'label':{'high':'優先対応','medium':'計画対応','low':'通常管理'}[result['level']],
                'tone':{'high':'高','medium':'中','low':'低'}[result['level']], 'basis':'risk_matrix'}
    # Explicit trusted current operational restrictions take precedence; never infer from prose.
    if context.get('requires_operation_judgment') is True:
        result['response_priority']={'label':'判断を優先','tone':'高','basis':'existing_operation_judgment'}
    return result


def annotate_analysis(analysis, sources=None, company_code=None, vehicle_id=None, is_current=None):
    """Read-time annotation: preserve saved analysis, references and feedback keys."""
    if not isinstance(analysis,dict):return analysis
    output=deepcopy(analysis);policy=load_policy()
    source_map={sid:value.get('snapshot',{}) for sid,value in (sources or {}).items() if isinstance(value,dict)}
    for item in output.get('recommendations',[]):
        if not isinstance(item,dict):continue
        item['risk_assessment']=evaluate_scenario(item,source_map,{
            'company_code':company_code,'vehicle_id':vehicle_id,'is_current':is_current,
            'as_of':datetime.now(timezone.utc).date().isoformat()},policy)
    output['risk_assessment_method']=METHOD
    return output
