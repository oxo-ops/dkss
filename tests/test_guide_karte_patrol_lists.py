"""Real route HTML and existing links; synthetic SQLite, no mutations via tested GETs."""
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from test_demo_inspection_compact import CompactDemoTests


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))

    def attrs(self, tag, **expected):
        return [attrs for name, attrs in self.elements if name == tag and all(
            attrs.get(k) == v for k, v in expected.items())]

    def with_attribute(self, tag, key):
        return [attrs for name, attrs in self.elements if name == tag and key in attrs]


class GuideKartePatrolTests(CompactDemoTests):
    def _assert_guide(self, page, endpoint, mode):
        self.assertEqual(page.status_code, 200)
        markup = Markup(page.text)
        guides = markup.attrs("section", id="firstUseGuide")
        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0]["data-mode"], mode)
        self.assertEqual(guides[0]["data-page"], endpoint)
        self.assertEqual(len(markup.with_attribute("button", "data-guide-open")), 1)
        self.assertNotIn("車番か車台番号を入力し", page.text)
        self.assertNotIn("同じ状態をもう一度押すと解除", page.text)
        return markup

    def test_karte_selection_keeps_original_search_and_navigation(self):
        for mode in ("normal", "demo"):
            self.demo_active = mode == "demo"
            for role in ("admin", "checker"):
                with self.subTest(mode=mode, role=role):
                    self.login(role)
                    with self.client.session_transaction() as sess:
                        if self.demo_active:
                            sess["demo_role_selected"] = True
                    page = self.request("GET", "/vehicle/karte")
                    markup = self._assert_guide(page, "vehicle_karte_list", mode)
                    self.assertEqual(len(markup.attrs("input", id="karte_vehicle_search", type="search")), 1)
                    self.assertEqual(markup.attrs("div", id="karte_vehicle_search_results")[0]["data-karte-url"], "/vehicle/karte")
                    self.assertEqual(len(markup.attrs("script", id="karte_vehicle_search_data")), 1)
                    chosen = self.request("GET", f"/vehicle/karte?vehicle_record_id={self.vehicle_id}")
                    self.assertEqual(chosen.status_code, 302)
                    self.assertEqual(chosen.location, f"/vehicle/karte/{self.vehicle_id}")
                    other = self.models.Vehicle.query.filter_by(company_code="B").one().id
                    self.assertEqual(self.request("GET", f"/vehicle/karte?vehicle_record_id={other}").status_code, 404)

    def test_patrol_list_links_match_roles_and_empty_filters(self):
        model = self.models.PatrolResult
        owner = self.models.User.query.filter_by(company_code="A", username="checker").one()
        row = model(
            company_code="A", created_by_username=owner.username,
            created_by_user_id=owner.id, created_by_identity=owner.account_identity,
            created_by_name="Test checker", target_type="user",
            target_username=owner.username, target_user_id=owner.id,
            target_identity=owner.account_identity, target_user="Test checker",
            date="2026-11-20", office="test", category="安全", content="合成の通路点検",
        )
        self.db.session.add(row)
        self.db.session.commit()
        with patch("dkss_app.notifications_delivery.send_web_push_notification") as push, patch(
            "dkss_app.notifications_delivery.send_email_notification"
        ) as mail:
            for mode in ("normal", "demo"):
                self.demo_active = mode == "demo"
                for role in ("admin", "checker"):
                    with self.subTest(mode=mode, role=role):
                        self.login(role)
                        if self.demo_active:
                            with self.client.session_transaction() as sess:
                                sess["demo_role_selected"] = True
                        page = self.request("GET", "/pointouts?type=user")
                        markup = self._assert_guide(page, "pointouts", mode)
                        links = markup.with_attribute("a", "data-guide-patrol-record")
                        self.assertEqual([link["href"] for link in links], [f"/pointouts/{row.id}"] * 2)
                        self.assertTrue(any("patrol-record-link" in link["class"].split() for link in links))
                        self.assertEqual(len(markup.attrs("input", id="pointout_keyword", name="keyword")), 1)
                        self.assertEqual(len(markup.attrs("summary", **{"aria-label": "検索・絞り込み条件を開閉"})), 1)
                        self.assertEqual(len(markup.attrs("a", href="/pointouts/new?target_type=user")), 1)
                        empty = self.request("GET", "/pointouts", query_string={"type": "user", "keyword": "存在しない語"})
                        self.assertFalse(self._assert_guide(empty, "pointouts", mode).with_attribute("a", "data-guide-patrol-record"))
            self.assertEqual(model.query.count(), 1)
            push.assert_not_called()
            mail.assert_not_called()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(GuideKartePatrolTests(name) for name in ("test_karte_selection_keeps_original_search_and_navigation", "test_patrol_list_links_match_roles_and_empty_filters"))
