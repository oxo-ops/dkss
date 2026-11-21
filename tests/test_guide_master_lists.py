"""Guide checks against nine real application GETs, on synthetic SQLite only."""
import unittest

from test_demo_inspection_compact import CompactDemoTests
from test_guide_karte_patrol_lists import Markup


MASTER_LISTS = {
    "/master/drivers": ("driver_master", "所属・免許・使用車両", "driver", False),
    "/master/offices": ("office_master", "営業所を確認", None, True),
    "/master/vehicles": ("vehicle_master", "車両の登録内容", "vehicle", False),
    "/master/vehicle-types": ("vehicle_type_master", "車両登録時に使用する車種", None, True),
    "/master/license-types": ("license_type_master", "ドライバーの免許種別", None, True),
    "/master/delivery-places": ("delivery_place_master", "納入先を確認", None, True),
    "/master/checklists": ("checklist_master", "安全管理・車両管理", "checklist", True),
    "/master/patrol-content-types": ("patrol_content_type_master", "安全パトロールの指摘やGood", None, True),
    "/master/manuals": ("manual_master", "システムで参照するマニュアル", None, True),
}


class MasterGuideTests(CompactDemoTests):
    def _assert_master(self, path, populated, query=""):
        endpoint, purpose, filter_name, can_order = MASTER_LISTS[path]
        page = self.request("GET", f"{path}{query}")
        self.assertEqual(page.status_code, 200)
        dom = Markup(page.text)
        guides = dom.attrs("section", id="firstUseGuide")
        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0]["data-page"], endpoint)
        self.assertEqual(guides[0]["data-master-guide"], "1")
        self.assertEqual(len(dom.with_attribute("button", "data-guide-open")), 1)
        self.assertIn("master_toolbar.js", page.text)
        self.assertRegex(page.text,
            r'<header class="master-unified-heading" data-master-guided>\s*<h2>[^<]+</h2>\s*</header>')
        tabs = [a for a in dom.attrs("a", href=path) if "is-current" in a.get("class","").split()]
        self.assertEqual(len(tabs), 1)
        self.assertIn(purpose, tabs[0]["data-guide-text"])
        self.assertNotIn("右端のハンドル", page.text)
        add = [a for a in dom.attrs("a") if "entry-add-icon" in a.get("class","").split()]
        self.assertEqual(len(add), 1)
        self.assertEqual(add[0]["href"], path + ("/register" if endpoint == "vehicle_master" else "/new"))
        filters = dom.with_attribute("button", "data-master-filter")
        self.assertEqual([item["data-master-filter"] for item in filters], [] if filter_name is None else [filter_name])
        excel = dom.with_attribute("a", "data-guide-master-excel")
        self.assertEqual([item["href"] for item in excel],
                         ["/master/delivery-places/import"] if endpoint == "delivery_place_master" else [])
        edits = [a for a in dom.attrs("a") if "btn-edit" in a.get("class","").split()]
        self.assertEqual(bool(edits), populated)
        if can_order:
            lists = [item for tag, item in dom.elements if "data-master-order-url" in item]
            self.assertTrue(lists)
            for item in lists:
                self.assertEqual(item["data-master-order-url"], path + "/order")
                matching = [elem for _, elem in dom.elements if elem.get("id") == item["data-master-status-id"]]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("role"), "status")
                self.assertEqual(matching[0].get("aria-live"), "polite")
            handles = [b for b in dom.attrs("button") if "master-order-handle" in b.get("class","").split()]
            standard_only = endpoint == "checklist_master" and not query and not populated
            self.assertEqual(bool(handles), populated or standard_only)
            if standard_only:
                self.assertTrue(dom.with_attribute("button", "data-standard-checklist-preview"))
                self.assertFalse(any(a.get("action", "").startswith("/master/checklists/") and a.get("action", "").endswith("/delete") for a in dom.attrs("form")))
        return dom

    def test_all_nine_empty_and_populated_admin_pages(self):
        self.demo_active = False
        self.login("admin", "B")
        m = self.models
        # Company B starts without custom records. Checklist GET adds its normal standard template.
        m.Vehicle.query.filter_by(company_code="B").delete()
        self.db.session.commit()
        for path in MASTER_LISTS:
            with self.subTest(path=path, populated=False):
                self._assert_master(path, False)
        for model in (m.Office, m.VehicleType, m.LicenseType, m.DeliveryPlace, m.PatrolContentType):
            self.db.session.add(model(company_code="B", name="合成マスタ"))
        self.db.session.add(m.Manual(company_code="B", title="合成マニュアル"))
        self.db.session.add(m.Driver(company_code="B", employee_id="SYN", name="合成ドライバー", office="合成マスタ"))
        self.db.session.add(m.Vehicle(company_code="B", chassis_number="B-SYN", office="合成マスタ", deleted=False))
        self.db.session.add(m.Checklist(company_code="B", name="合成点検表", target="安全管理",
                                       display_type="日", items_json="[]"))
        self.db.session.commit()
        for path in MASTER_LISTS:
            with self.subTest(path=path, populated=True):
                self._assert_master(path, True)
        for path, query in [
            ("/master/drivers", "?keyword=存在しない"),
            ("/master/vehicles", "?plate_number_search=ZZZ"),
            ("/master/checklists", "?keyword=存在しない"),
        ]:
            with self.subTest(filtered=path):
                self._assert_master(path, False, query)
        pending = self.request("GET", "/master/vehicles?view=pending")
        self.assertEqual(pending.status_code, 200)
        self.assertIn('data-master-guide="1"', pending.text)
        self.assertNotIn('id="vehicleFilterPanel"', pending.text)
        self.assertEqual(m.MasterDisplayOrder.query.count(), 0)

    def test_access_and_nonlist_policy_unchanged(self):
        self.demo_active = False
        self.login("checker", "B")
        for path in MASTER_LISTS:
            self.assertEqual(self.request("GET", path).status_code, 302)
        self.login("support", "B")
        self._assert_master("/master/offices", False)
        self.login("admin", "B")
        ordinary_form = self.request("GET", "/master/offices/new")
        self.assertEqual(ordinary_form.status_code, 200)
        self.assertNotIn('data-master-guide="1"', ordinary_form.text)
        guest = self.app.test_client()
        for path in MASTER_LISTS:
            self.assertEqual(guest.get(path).status_code, 302)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(MasterGuideTests(name) for name in (
        "test_all_nine_empty_and_populated_admin_pages", "test_access_and_nonlist_policy_unchanged"))
