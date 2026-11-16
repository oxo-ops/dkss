"""Explicit, default-off release settings. No provisioning and no secret output."""
import os
from uuid import UUID


def load(app):
    if os.environ.get('PUBLIC_DEMO_ENABLED','false').lower() != 'true':
        return
    def required(name):
        value=os.environ.get(name,'').strip()
        if not value:
            raise RuntimeError('Missing public demo release setting: '+name)
        return value
    company=required('PUBLIC_DEMO_COMPANY')
    driver=required('PUBLIC_DEMO_DRIVER')
    manager=required('PUBLIC_DEMO_MANAGER')
    if driver == manager:
        raise RuntimeError('Dedicated demo driver and manager must be different')
    identities={}
    for role in ('DRIVER','MANAGER'):
        value=required('PUBLIC_DEMO_'+role+'_IDENTITY')
        try:UUID(value)
        except ValueError:raise RuntimeError('Invalid dedicated demo identity') from None
        identities['PUBLIC_DEMO_'+role+'_IDENTITY']=value
    try:
        start=int(required('PUBLIC_DEMO_FROM'))
        until=int(required('PUBLIC_DEMO_UNTIL'))
    except ValueError:raise RuntimeError('Public demo times must be explicit UTC epoch seconds') from None
    if start <= 0 or until <= start:
        raise RuntimeError('Invalid public demo release time window')
    if not app.config.get('RATELIMIT_STORAGE_URI','').startswith(('redis://','rediss://')):
        raise RuntimeError('Public demo release needs existing shared Redis')
    app.config.update(PUBLIC_DEMO_CANDIDATE=True,PUBLIC_DEMO_RELEASE=True,
        PUBLIC_DEMO_SHARED_COMPANY=True,PUBLIC_DEMO_WORKFLOW=True,
        PUBLIC_DEMO_COMPANY=company,PUBLIC_DEMO_USERNAME=driver,
        PUBLIC_DEMO_DRIVER=driver,PUBLIC_DEMO_MANAGER=manager,
        PUBLIC_DEMO_FROM=start,PUBLIC_DEMO_UNTIL=until,
        PUBLIC_DEMO_EPOCH=required('PUBLIC_DEMO_EPOCH'),**identities)
