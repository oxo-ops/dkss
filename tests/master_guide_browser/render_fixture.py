"""Reuse product fixture; add only a second office and missing GET targets."""
from pathlib import Path
import os

file = Path(os.environ["PRODUCT_REPO"]) / "tests/header_mobile_browser/render_pages.py"
source = file.read_text()
changes = {
    "  self.db.session.add(m.Driver": "  self.db.session.add(m.Office(company_code='B',name='並べ替え確認用営業所'))\n  self.db.session.add(m.Driver",
    "'new_driver','new_manual']": "'new_driver','new_manual','new_checklist','vehicle_registration_method']",
}
for old, new in changes.items():
    assert source.count(old) == 1, f"Fixture changed: {old}"
    source = source.replace(old, new)
exec(compile(source, str(file), "exec"), {"__name__": "__main__", "__file__": str(file)})
