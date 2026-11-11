-- Fresh disposable CI PostgreSQL container only; run before generating app data.
ALTER SYSTEM SET logging_collector = 'off';
ALTER SYSTEM SET log_destination = 'stderr';
ALTER SYSTEM SET log_statement = 'none';
ALTER SYSTEM SET log_min_messages = 'panic';
ALTER SYSTEM SET log_min_error_statement = 'panic';
ALTER SYSTEM SET log_error_verbosity = 'terse';
ALTER SYSTEM SET log_parameter_max_length = '0';
ALTER SYSTEM SET log_parameter_max_length_on_error = '0';
ALTER SYSTEM SET log_duration = 'off';
ALTER SYSTEM SET log_min_duration_statement = '-1';
ALTER SYSTEM SET log_min_duration_sample = '-1';
ALTER SYSTEM SET log_statement_sample_rate = '0';
ALTER SYSTEM SET log_transaction_sample_rate = '0';
ALTER SYSTEM SET log_statement_stats = 'off';
ALTER SYSTEM SET log_parser_stats = 'off';
ALTER SYSTEM SET log_planner_stats = 'off';
ALTER SYSTEM SET log_executor_stats = 'off';
ALTER SYSTEM SET debug_print_parse = 'off';
ALTER SYSTEM SET debug_print_plan = 'off';
ALTER SYSTEM SET debug_print_rewritten = 'off';
DO $$ BEGIN
 IF NOT pg_reload_conf() THEN RAISE EXCEPTION 'CI_LOGGING_RELOAD_FAILED'; END IF;
END $$;
