"""Legacy direct-POST fixtures represent a fresh, actually rendered review."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


class ApprovalForms(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.action = None
        self.versions = {}
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.action = attrs.get('action')
        elif tag == 'input' and self.action and attrs.get('name') == 'approval_version':
            self.versions[self.action] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.action = None


def fresh_approval_version(client, path):
    path = urlsplit(path).path
    match = re.fullmatch(r'/(safety|vehicle)/checklist-results/(\d+)/approve/\d+', path)
    if not match:
        return None
    if match[1] == 'safety':
        page = path.rsplit('/approve/', 1)[0]
    else:
        from dkss_app.models import VehicleChecklistResult
        with client.application.app_context():
            row = VehicleChecklistResult.query.filter_by(id=int(match[2])).first()
            if row is None:
                return None
            page = (f'/vehicle/checklists/{row.checklist_id}?vehicle_record_id={row.vehicle_record_id}'
                    f'&year={row.year}&month={row.month}&active_day={row.day}')
    response = client.get(page)
    try:
        return ApprovalForms(response.get_data(as_text=True)).versions.get(path)
    finally:
        response.close()
