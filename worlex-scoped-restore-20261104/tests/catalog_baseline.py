"""Test-only oracle from published commit 29a549a04d1c3f20a7220cfcb50a3cb70c086e74.

Only the exact historical check_empty_and_itc function is copied below. Shared
helpers are unchanged and checked by a byte hash of all other core source.
This module has no command-line or database connection path.
"""
from sqlalchemy import func, inspect, select, tuple_
from worlex_restore import TENANT, Stop, require, valid_uuid

BASELINE_COMMIT = '29a549a04d1c3f20a7220cfcb50a3cb70c086e74'
BASELINE_CORE_SHA256 = '30b7bd20e669541181ed037fe596d57bd855f364e3bb804c75bd6b779c60680a'
BASELINE_FUNCTION_SHA256 = 'b6b267bc9837318e29bc6854e065096939c80f06fcdec25a818d95893331b231'
UNCHANGED_CORE_SHA256 = '7c43c8cf7f125a330563fb75af5887c1be7d702ce3091a7e8d9dfcded3e26d34'

def check_empty_and_itc(connection,tables,typed):
 for name,t in tables.items():
  if 'company_code' in t.c and name!='audit_log':
   require(connection.scalar(select(func.count()).select_from(t).where(func.lower(t.c.company_code)==TENANT.lower()))==0,'TARGET_WORLEX_OR_CASE_ALIAS_EXISTS:'+name)
 for name,rows in typed.items():
  table=tables[name]
  for pk in table.primary_key:
   values=[r[pk.name] for r in rows]
   if values:require(connection.execute(select(pk).where(pk.in_(values))).first() is None,'PRIMARY_KEY_COLLISION:'+name)
 for name,table in tables.items():
  for field in ('account_identity','master_generation'):
   if field not in table.c:continue
   existing=list(connection.scalars(select(table.c[field])))
   require(all(valid_uuid(v) for v in existing) and len(existing)==len(set(existing)),'INVALID_EXISTING_GENERATION:'+name)
   require(not set(existing).intersection(r[field] for r in typed.get(name,[]) if field in r),'GENERATED_IDENTIFIER_COLLISION:'+name)
 inspector=inspect(connection)
 for name,rows in typed.items():
  if not rows:continue
  table=tables[name]
  indexes=inspector.get_unique_constraints(name,schema='public')+ [i for i in inspector.get_indexes(name,schema='public') if i.get('unique')]
  for index in indexes:
   cols=index.get('column_names') or []
   require(cols and all(c in table.c for c in cols),'EXPRESSION_UNIQUE_INDEX_BLOCKED:'+name)
   # Apply full-key checks conservatively for partial indexes. False positives stop.
   require(not index.get('dialect_options',{}).get('postgresql_nulls_not_distinct'),'NULLS_NOT_DISTINCT_INDEX_BLOCKED:'+name)
   seen=set()
   for row in rows:
    values=tuple(row.get(c) for c in cols)
    if None in values:continue
    require(values not in seen,'SOURCE_UNIQUE_KEY_COLLISION:'+name);seen.add(values)
   values=list(seen)
   for offset in range(0,len(values),500):
    require(connection.execute(select(*[table.c[c] for c in cols]).where(tuple_(*[table.c[c] for c in cols]).in_(values[offset:offset+500])).limit(1)).first() is None,'TARGET_UNIQUE_KEY_COLLISION:'+name)
 user=tables['user']; company=tables['company']
 require(connection.scalar(select(func.count()).select_from(company).where(company.c.company_code=='ITC'))==1,'ITC_COMPANY_MISSING')
 require(connection.scalar(select(func.count()).select_from(user).where(user.c.company_code=='ITC',user.c.username=='itc',user.c.role=='itc'))>=1,'ITC_ADMIN_MISSING')
