import sys

def guard(event,args):
 if event=='socket.connect':
  a=args[1]
  if not isinstance(a,tuple) or a[:2]!=('127.0.0.1',55439):raise RuntimeError('ONLY_OWNED_CI_PG_ALLOWED')
 if event=='sqlite3.connect':raise RuntimeError('POSTGRES_REQUIRED')
sys.addaudithook(guard)
