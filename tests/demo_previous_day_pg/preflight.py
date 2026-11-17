"""Fail-closed dedicated database target, no external access."""
URL='postgresql+psycopg2://seed_fixture:synthetic_only@127.0.0.1:55433/seed_fixture'
def validate(value):
 if value!=URL:raise ValueError('DEDICATED_SYNTHETIC_DATABASE_REQUIRED')
 return value
if __name__=='__main__':
 validate(URL)
 for value in ['',URL+'?host=example.com',URL.replace('127.0.0.1','localhost'),URL.replace('seed_fixture','production'),URL.replace('55433','5432'),'sqlite://']:
  try:validate(value)
  except ValueError:continue
  raise AssertionError('invalid target accepted')
 print('PREFLIGHT_7_CONDITIONS_PASS')
