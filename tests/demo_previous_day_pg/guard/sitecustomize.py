"""Python network fence; libpq target independently gated by preflight."""
import sys

def guard(event,args):
 if event=='socket.connect':
  address=args[1]
  if not isinstance(address,tuple) or address[:2]!=('127.0.0.1',55433):raise RuntimeError('NON_FIXTURE_PYTHON_NETWORK_DENIED')
 if event=='sqlite3.connect':raise RuntimeError('POSTGRES_TEST_MUST_NOT_USE_SQLITE')
sys.addaudithook(guard)
