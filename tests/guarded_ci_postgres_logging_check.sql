-- Check effective values on a fresh connection; never print settings or data.
DO $$ BEGIN
 IF EXISTS (
  SELECT 1 FROM (VALUES
   ('logging_collector','off'), ('log_destination','stderr'),
   ('log_statement','none'), ('log_min_messages','panic'),
   ('log_min_error_statement','panic'), ('log_error_verbosity','terse'),
   ('log_parameter_max_length','0'), ('log_parameter_max_length_on_error','0'),
   ('log_duration','off'), ('log_min_duration_statement','-1'),
   ('log_min_duration_sample','-1'), ('log_statement_sample_rate','0'),
   ('log_transaction_sample_rate','0'), ('log_statement_stats','off'),
   ('log_parser_stats','off'), ('log_planner_stats','off'), ('log_executor_stats','off'),
   ('debug_print_parse','off'), ('debug_print_plan','off'), ('debug_print_rewritten','off')
  ) AS expected(name,value) LEFT JOIN pg_settings actual ON actual.name=expected.name
  WHERE actual.setting IS DISTINCT FROM expected.value OR actual.pending_restart
 ) THEN RAISE EXCEPTION 'CI_LOGGING_BOUNDARY_NOT_EFFECTIVE'; END IF;
END $$;
