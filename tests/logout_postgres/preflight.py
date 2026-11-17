"""Offline URL gate. No DB connection, no secret values in exceptions."""
from sqlalchemy.engine import make_url

def validate(value):
 try:u=make_url(value)
 except Exception:raise ValueError('ISOLATED_POSTGRES_URL_REQUIRED') from None
 if (u.drivername not in ('postgresql','postgresql+psycopg2') or u.host!='127.0.0.1'
   or u.database!='dkss_q02_ci' or u.port!=55432 or u.username!='dkss_logout_ci'
   or u.query or not u.password):raise ValueError('ISOLATED_POSTGRES_TARGET_REJECTED')
 return value
