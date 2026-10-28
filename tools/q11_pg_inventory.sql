-- Read-only inventory of an explicitly marked, synthetic Q11 database.
\set ON_ERROR_STOP on
\if :{?q11_expected_db}
\else
  \warn 'q11_expected_db is required'
  SELECT 1/0 AS q11_expected_database_required;
\endif
SELECT current_database() = :'q11_expected_db'
  AND current_database() LIKE 'q11\_%' ESCAPE '\'
  AND shobj_description(oid, 'pg_database') = 'Q11_SYNTHETIC_ONLY' AS q11_target_ok
FROM pg_database WHERE datname=current_database()
\gset
\if :q11_target_ok
\else
  \warn 'Refusing unmarked or unexpected database'
  SELECT 1/0 AS q11_target_refused;
\endif
BEGIN READ ONLY;
SELECT 'database', current_database(), current_user, session_user,
       current_setting('server_version'), pg_database_size(current_database());
SELECT 'database_acl', d.datname, pg_get_userbyid(d.datdba), d.datacl::text,
       d.datcollate, d.datctype, pg_encoding_to_char(d.encoding)
FROM pg_database d WHERE d.datname=current_database();
SELECT 'role', rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin,
       rolreplication, rolbypassrls FROM pg_roles WHERE rolname LIKE 'q11%' ORDER BY rolname;
SELECT 'membership', pg_get_userbyid(roleid), pg_get_userbyid(member),
       admin_option, inherit_option, set_option FROM pg_auth_members
WHERE pg_get_userbyid(roleid) LIKE 'q11%' ORDER BY 2,3;
SELECT 'extension', e.extname,e.extversion,n.nspname,pg_get_userbyid(e.extowner)
FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname;
SELECT 'schema', nspname,pg_get_userbyid(nspowner),nspacl::text
FROM pg_namespace WHERE nspname='public';
SELECT 'object', c.relname,c.relkind,pg_get_userbyid(c.relowner),c.relacl::text,
       pg_total_relation_size(c.oid),c.relrowsecurity,c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') ORDER BY c.relname;
SELECT 'default_acl',pg_get_userbyid(defaclrole),n.nspname,defaclobjtype,defaclacl::text
FROM pg_default_acl a LEFT JOIN pg_namespace n ON n.oid=a.defaclnamespace
ORDER BY 2,3,4;
SELECT 'row_policy',schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check
FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname;
SELECT 'function_acl',p.oid::regprocedure::text,pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' ORDER BY 2;
COMMIT;
