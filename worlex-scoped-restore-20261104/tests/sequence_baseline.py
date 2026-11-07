"""Exact sequence_states oracle from 124e6ee7; tests only."""
from sqlalchemy import Integer,text
from worlex_restore import require,q
def sequence_states(connection,tables,lock=False):
 states={}
 for name,t in sorted(tables.items()):
  for col in t.primary_key:
   seq=connection.scalar(text('SELECT pg_get_serial_sequence(:table,:column)'),{'table':'public.'+q(name),'column':col.name})
   if not seq:
    require(not (col.name=='id' and isinstance(col.type,Integer)),'OWNED_ID_SEQUENCE_MISSING:'+name)
    continue
   meta=connection.execute(text("SELECT n.nspname,c.relname,c.oid,c.relowner,c.relacl::text,c.relpersistence,c.reloptions,c.reltablespace,c.relfilenode,s.seqtypid,s.seqstart,s.seqincrement,s.seqmin,s.seqmax,s.seqcache,s.seqcycle FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=CAST(:seq AS regclass)"),{'seq':seq}).one()
   schema,sn,oid,owner,acl,persistence,options,tablespace,filenode,type_oid,start,inc,mn,mx,cache,cycle=meta
   ownership=[list(r) for r in connection.execute(text("SELECT d.refobjid,d.refobjsubid,d.deptype FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=CAST(:seq AS regclass) AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i') ORDER BY 1,2,3"),{'seq':seq}).tuples()]
   require(schema=='public' and inc==1 and mn==1 and cache==1 and not cycle and len(ownership)==1,'UNSUPPORTED_SEQUENCE:'+name)
   qualified=q(schema)+'.'+q(sn)
   # Even a no-op ALTER touches sequence state/catalog. Never issue one for
   # the preserved push sequence. All writer sessions and tables are locked.
   if lock and name!='push_subscription':connection.exec_driver_sql('ALTER SEQUENCE '+qualified+' CACHE 1')
   last,called,log_cnt=connection.exec_driver_sql('SELECT last_value,is_called,log_cnt FROM '+qualified).one()
   states[(name,col.name)]={'qualified':qualified,'last':last,'called':called,'next':last+1 if called else last,'max':mx,
    'catalog':{'schema':schema,'name':sn,'oid':oid,'owner':owner,'acl':acl,'type_oid':type_oid,'start':start,'increment':inc,'min':mn,'max':mx,'cache':cache,'cycle':cycle,'ownership':ownership}}
   if name=='push_subscription':
    states[(name,col.name)]['log_cnt']=log_cnt
    states[(name,col.name)]['catalog'].update(persistence=persistence,options=options,tablespace=tablespace,filenode=filenode)
 return states
