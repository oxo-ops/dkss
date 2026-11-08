"""Verbatim SQL-only guard nodes extracted from the reviewed diagnostic.

No operational helper, local personal paths, connection input, database/client
capability, CLI entrypoint, or network functionality is included.
Original full-file SHA256: 60d91e7ed844a90850b4928f57bbfc9e261f1f0dbb877d5e5f52ba26925daf8f
"""
import re

CORE_PHASES = ('validate_schema', 'typed_payload', 'prepare_deferred_push', 'check_empty_and_itc', 'snapshot', 'sequence_states', 'identity')

PHASES = frozenset((*CORE_PHASES, 'local_validation', 'url_input', 'offline_source', 'dbapi_connect', 'sqlalchemy_initialize', 'tls_check', 'transaction_setup', 'server_context', 'plan', 'rollback', 'connection_close', 'engine_dispose', 'preservation_check', 'complete'))

SET_RO = 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'

SHOW_RO = 'SHOW transaction_read_only'

SERVER_CONTEXT = "SELECT pg_backend_pid(), to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), current_setting('transaction_read_only')"

TIMEOUT_CONTEXT = "SELECT name, setting, unit FROM pg_catalog.pg_settings WHERE name IN ('statement_timeout','lock_timeout','idle_in_transaction_session_timeout','transaction_timeout') ORDER BY name"

INIT_SQL = frozenset(('select pg_catalog.version()', 'select current_schema()', 'show transaction isolation level', 'show standard_conforming_strings'))

SAFE_FUNCTIONS = frozenset(('count','lower','coalesce','cast','any','all','array','unnest','array_agg','array_length','array_to_string','generate_subscripts','json_agg','json_build_object','string_agg','regexp_replace','substring','concat','max','min','sum','abs','nullif','pg_get_expr','pg_get_constraintdef','pg_get_indexdef','pg_get_triggerdef','pg_get_serial_sequence','pg_table_is_visible','pg_type_is_visible','format_type','obj_description','col_description','current_database','current_user','current_schema','inet_server_addr','inet_server_port','current_setting','pg_backend_pid','clock_timestamp','to_char','version','exists','in','not','and','or','over','filter','values','when','then','join','from','bool_and'))

BLOCKED_WORDS = frozenset(('insert','update','delete','merge','alter','create','drop','truncate','grant','revoke','copy','call','do','execute','prepare','deallocate','vacuum','analyze','refresh','into','listen','notify','unlisten','lock','commit','rollback','nextval','setval','set_config','pg_sleep','pg_advisory_lock','pg_try_advisory_xact_lock','pg_cancel_backend','pg_terminate_backend','dblink','lo_export','lo_import'))

class Stop(Exception): pass

def require(value, code):
    if not value: raise Stop(code)

def sql_tokens(statement):
    require(type(statement) is str and 0<len(statement)<=1000000,'SQL_TEXT_INVALID')
    # Strip quoted literals/identifiers without ever emitting them. Reject all
    # comment forms, dollar quoting and multi-statements outside string literals.
    result=[];i=0
    while i<len(statement):
        ch=statement[i]
        if ch in "'\"":
            quote=ch;i+=1
            while i<len(statement):
                if statement[i]==quote:
                    if i+1<len(statement) and statement[i+1]==quote:i+=2;continue
                    i+=1;break
                i+=1
            else:raise Stop('SQL_QUOTE_UNTERMINATED')
            result.append(' quoted ');continue
        require(ch!=';' and not statement.startswith(('--','/*','*/','$$'),i),'SQL_MULTISTATEMENT_OR_COMMENT_BLOCKED')
        result.append(ch);i+=1
    return ''.join(result).lower()

def guard_sql(statement, phase, trusted_origin):
    require(phase in PHASES,'QUERY_PHASE_INVALID')
    if phase=='transaction_setup' and statement in (SET_RO,SHOW_RO):return 'setup_query'
    if phase=='server_context' and statement in (SERVER_CONTEXT,TIMEOUT_CONTEXT):return 'server_context_query'
    if phase=='sqlalchemy_initialize' and statement.lower().strip() in INIT_SQL:return 'initialization_query'
    require(trusted_origin and phase in CORE_PHASES,'QUERY_ORIGIN_NOT_PINNED_CORE')
    text=sql_tokens(statement);words=set(re.findall(r'\b[a-z_][a-z_0-9]*\b',text))
    require(not words & BLOCKED_WORDS,'MUTATING_OR_UNREVIEWED_SQL_BLOCKED')
    if text.strip().startswith('show '):
        require(statement in ('SHOW server_version_num','SHOW session_replication_role'),'SHOW_NOT_ALLOWLISTED')
    else:
        require(text.lstrip().startswith('select ') or (phase=='sequence_states' and text.lstrip().startswith('with requested(')), 'SELECT_ONLY_REQUIRED')
        # WHERE (...) is SQL clause syntax, not a function. Keep qualified
        # identifiers such as public.where(...) subject to the function gate.
        candidates=re.finditer(r'\b([a-z_][a-z_0-9]*)\s*\(',text)
        functions={match.group(1) for match in candidates if not (phase=='check_empty_and_itc' and match.group(1)=='where' and not text[:match.start()].rstrip().endswith('.'))}
        require(functions <= (SAFE_FUNCTIONS | (frozenset(('requested','resolved','as')) if phase=='sequence_states' else frozenset())), 'SQL_FUNCTION_NOT_ALLOWLISTED')
    return {'validate_schema':'reflection_query' if 'pg_catalog.' in text else 'schema_query',
            'prepare_deferred_push':'tenant_collision_query','check_empty_and_itc':'tenant_collision_query',
            'snapshot':'preserved_rows_query','sequence_states':'sequence_query','identity':'identity_query'}.get(phase,'schema_query')
