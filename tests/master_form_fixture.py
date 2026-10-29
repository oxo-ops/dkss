"""Give existing route tests a fresh signed form, without changing assertions.

Explicit master_token values are never replaced. New stale/unsigned-form tests
use plain FlaskClient and actual rendered forms instead of this adapter.
Historical baseline checkouts without generation support retain their old API.
"""
import re
from flask.testing import FlaskClient


def fresh_master_data(client, path, data):
    match = re.fullmatch(r'/master/(offices|vehicle-types|delivery-places|license-types|patrol-content-types)/(\d+)/(edit|delete)', path)
    if not match or 'master_token' in (data or {}):
        return data
    try:
        from dkss_app.master_generations import KINDS, issue_token
    except ModuleNotFoundError as error:
        if error.name != 'dkss_app.master_generations':
            raise
        return data
    from dkss_app import models
    kind, ident, operation = match.groups()
    model = next(m for m in (models.Office, models.VehicleType, models.DeliveryPlace,
                            models.LicenseType, models.PatrolContentType) if m.__tablename__ == KINDS[kind])
    with client.session_transaction() as session:
        company = session.get('company_code')
        role = session.get('role')
    if role not in {'admin', 'itc'}:
        return dict(data or {}, master_token='')
    with client.application.app_context():
        row = model.query.filter_by(company_code=company, id=int(ident)).first()
        if row is None:
            return dict(data or {}, master_token='')
        token = issue_token(kind, company, row.id, row.master_generation, operation)
    return dict(data or {}, master_token=token)


class FreshMasterFormsClient(FlaskClient):
    def open(self, *args, **kwargs):
        path = args[0] if args and isinstance(args[0], str) else kwargs.get('path', '')
        if kwargs.get('method', 'GET').upper() == 'POST':
            kwargs['data'] = fresh_master_data(self, path, kwargs.get('data'))
        return super().open(*args, **kwargs)
