"""Vehicle-combination validation, tenant isolation and bidirectional rendering."""
from identity_fixture import identity_for
from datetime import datetime
from types import SimpleNamespace
import unittest

from dkss_app import create_app
from dkss_app.extensions import db
from dkss_app.models import AuditLog, Company, User, Vehicle, VehicleCoupling
from dkss_app.vehicle_couplings import coupling_context, coupling_role, pair_kind


class CouplingTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"SECRET_KEY": "coupling-test", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                               "TESTING": True, "WTF_CSRF_ENABLED": False, "MFA_ENABLED": False,
                               "RATELIMIT_ENABLED": False, "S3_BUCKET_NAME": ""})
        self.ctx = self.app.app_context(); self.ctx.push()
        db.create_all()
        self.stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.add(Company(company_code="TEST", company_name="Test", active=True))
        self.user = User(company_code="TEST", username="admin", role="admin", password="unused",
                         password_changed_at=self.stamp, last_name="検証", first_name="管理者")
        db.session.add(self.user)
        self.tractor = self.vehicle("トラクタ", "1813")
        self.trailer = self.vehicle("トレーラ", "2001")
        self.trailer2 = self.vehicle("トレーラ", "2002")
        self.truck = self.vehicle("大型", "3001")
        self.foreign = self.vehicle("トレーラ", "foreign", company="OTHER")
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state.update(account_identity=identity_for("TEST", "admin", app=(self.client).application), company_code="TEST", username="admin", role="admin", password_changed_at=self.stamp)

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.ctx.pop()

    def vehicle(self, kind, plate, company="TEST", body=""):
        row = Vehicle(company_code=company, type=kind, body_type=body,
                      plate_area="三河", plate_number=plate, chassis_number=f"chassis-{plate}", office="安城")
        db.session.add(row); db.session.flush(); return row

    def add(self, first=None, second=None, confirmed="yes"):
        return self.client.post(f"/vehicle/karte/{(first or self.tractor).id}/couplings",
                                data={"vehicle_id": (second or self.trailer).id, "confirmed": confirmed})

    def context(self, vehicle):
        with self.app.test_request_context('/'):
            from flask import session
            session.update(company_code="TEST", role="admin")
            return coupling_context(vehicle, Vehicle.query.filter_by(company_code="TEST").all())

    def test_classification_uses_shape_and_normalizes_aliases(self):
        cases = [("大型", "トラクタ", "tractor"), ("ﾄﾚｰﾗｰ", "", "trailer"),
                 ("トレーラーヘッド", "", "tractor"), ("大型", "", "truck"),
                 ("中型ウイング", "", "truck"), ("普通乗用車", "", None),
                 ("大型バス", "", None), ("未分類", "", None)]
        for kind, body, expected in cases:
            with self.subTest(kind=kind):
                self.assertEqual(coupling_role(SimpleNamespace(type=kind, body_type=body)), expected)

    def test_add_from_either_vehicle_and_render_both_headers(self):
        self.assertEqual(self.add(first=self.trailer, second=self.tractor).status_code, 302)
        row = VehicleCoupling.query.one()
        self.assertEqual((row.towing_vehicle_id, row.trailer_vehicle_id, row.kind),
                         (self.tractor.id, self.trailer.id, "semi"))
        for source, peer in [(self.tractor, self.trailer), (self.trailer, self.tractor)]:
            self.assertEqual(self.context(source)["links"][0]["vehicle_id"], peer.id)
            html = self.client.get(f"/vehicle/karte/{source.id}").get_data(as_text=True)
            self.assertIn('id="vehicle-couplings"', html)
            self.assertIn('id="vehicle-coupling-dialog"', html)
            self.assertIn(peer.plate_number, html)
        self.assertEqual(AuditLog.query.filter_by(action="vehicle_coupling_add").count(), 1)

    def test_hide_unavailable_button_but_keep_existing_links_manageable(self):
        self.trailer.deleted = True
        self.trailer2.deleted = True
        db.session.commit()
        self.assertTrue(self.context(self.tractor)["visible"])
        self.assertFalse(self.context(self.truck)["visible"])
        html = self.client.get(f"/vehicle/karte/{self.tractor.id}").get_data(as_text=True)
        self.assertIn('data-coupling-open', html)
        self.trailer.deleted = False
        db.session.commit()
        self.assertTrue(self.context(self.tractor)["visible"])
        self.add()
        state = self.context(self.tractor)
        self.assertTrue(state["visible"])
        self.assertFalse(state["can_add"])
        html = self.client.get(f"/vehicle/karte/{self.tractor.id}").get_data(as_text=True)
        self.assertIn('data-coupling-open', html)
        self.assertIn('data-coupling-remove', html)
        self.assertNotIn('class="vc-add-form"', html)

    def test_dedicated_roles_in_either_field_keep_button_without_candidates(self):
        vehicles = [self.tractor, self.trailer, self.trailer2, self.truck]
        for vehicle in vehicles:
            vehicle.deleted = True
        source = self.tractor
        source.deleted = False
        for field in ("type", "body_type"):
            for name in ("トラクタ", "トレーラー", "ﾄﾚｰﾗｰ"):
                with self.subTest(field=field, name=name):
                    source.type = ""
                    source.body_type = ""
                    setattr(source, field, name)
                    db.session.commit()
                    state = self.context(source)
                    self.assertTrue(state["visible"])
                    self.assertFalse(state["can_add"])
                    self.assertEqual(state["candidates"], [])
                    html = self.client.get(f"/vehicle/karte/{source.id}").get_data(as_text=True)
                    self.assertIn('data-coupling-open', html)
                    self.assertIn("追加できる車両がありません。", html)
        source.type = "乗用車"
        source.body_type = "セダン"
        db.session.commit()
        self.assertFalse(self.context(source)["visible"])
        source.type = "トラクタ"
        source.deleted = True
        db.session.commit()
        self.assertFalse(self.context(source)["visible"])

    def test_many_to_many_and_duplicate_pair_guard(self):
        self.assertEqual(self.add().status_code, 302)
        self.assertEqual(self.add(second=self.trailer2).status_code, 302)
        self.assertEqual(self.add(first=self.trailer, second=self.truck).status_code, 302)
        self.assertEqual(len(self.context(self.tractor)["links"]), 2)
        self.assertEqual(len(self.context(self.trailer)["links"]), 2)
        self.assertEqual(self.add().status_code, 409)
        self.assertEqual(VehicleCoupling.query.count(), 3)

    def test_large_truck_can_link_full_but_not_explicit_semi_trailer(self):
        self.trailer.type = "フルトレーラ"; db.session.commit()
        self.assertEqual(self.add(first=self.truck).status_code, 302)
        self.assertEqual(VehicleCoupling.query.one().kind, "full")
        self.trailer2.type = "セミトレーラ"; db.session.commit()
        self.assertEqual(self.add(first=self.truck, second=self.trailer2).status_code, 400)

    def test_reject_self_same_role_invalid_confirm_and_inactive(self):
        self.assertEqual(self.add(second=self.tractor).status_code, 400)
        self.assertEqual(self.add(first=self.trailer, second=self.trailer2).status_code, 400)
        self.assertEqual(self.add(first=self.truck, second=self.tractor).status_code, 400)
        self.assertEqual(self.add(confirmed="").status_code, 400)
        self.trailer.deleted = True; db.session.commit()
        self.assertEqual(self.add().status_code, 400)
        self.assertEqual(VehicleCoupling.query.count(), 0)

    def test_other_company_cannot_be_linked_or_unlinked(self):
        self.assertEqual(self.add(second=self.foreign).status_code, 404)
        self.assertEqual(self.add(first=self.foreign, second=self.tractor).status_code, 404)
        self.add()
        row = VehicleCoupling.query.one()
        response = self.client.post(f"/vehicle/karte/{self.foreign.id}/couplings/{row.id}/remove")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(VehicleCoupling.query.count(), 1)
        self.assertNotIn(self.foreign.id, [item["id"] for item in self.context(self.tractor)["candidates"]])

    def test_general_user_can_view_but_not_write(self):
        self.add()
        row_id = VehicleCoupling.query.one().id
        self.user.role = "user"; db.session.commit()
        html = self.client.get(f"/vehicle/karte/{self.tractor.id}").get_data(as_text=True)
        self.assertIn("連結車両を見る", html)
        dialog = html.split('id="vehicle-coupling-dialog"', 1)[1].split("</dialog>", 1)[0]
        self.assertNotIn('name="confirmed"', dialog)
        self.assertEqual(self.add(second=self.trailer2).status_code, 403)
        self.assertEqual(self.client.post(f"/vehicle/karte/{self.tractor.id}/couplings/{row_id}/remove").status_code, 403)

    def test_remove_only_owned_link_preserves_vehicles_and_other_pairs(self):
        self.add(); self.add(second=self.trailer2)
        row_id = VehicleCoupling.query.filter_by(trailer_vehicle_id=self.trailer.id).one().id
        self.assertEqual(self.client.post(f"/vehicle/karte/{self.truck.id}/couplings/{row_id}/remove").status_code, 404)
        self.trailer.deleted = True; db.session.commit()
        self.assertTrue(self.context(self.tractor)["links"][0]["deleted"])
        self.assertEqual(self.client.post(f"/vehicle/karte/{self.trailer.id}/couplings/{row_id}/remove").status_code, 302)
        self.assertEqual(VehicleCoupling.query.count(), 1)
        self.assertEqual(Vehicle.query.count(), 5)
        self.assertEqual(AuditLog.query.filter_by(action="vehicle_coupling_remove").count(), 1)

    def test_no_ddl_or_broken_karte_before_explicit_migration(self):
        VehicleCoupling.__table__.drop(db.engine)
        self.app.extensions["dkss"].pop("vehicle_couplings_schema_ready", None)
        response = self.client.get(f"/vehicle/karte/{self.tractor.id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('data-coupling-open', response.get_data(as_text=True))
        self.assertEqual(self.add().status_code, 503)
        from sqlalchemy import inspect
        self.assertFalse(inspect(db.engine).has_table("vehicle_coupling"))
        result = self.app.test_cli_runner().invoke(args=["init-vehicle-couplings"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(inspect(db.engine).has_table("vehicle_coupling"))
        self.assertEqual(self.add().status_code, 302)
        again = self.app.test_cli_runner().invoke(args=["init-vehicle-couplings"])
        self.assertEqual(again.exit_code, 0, again.output)
        self.assertEqual(VehicleCoupling.query.count(), 1)

    def test_worker_startup_prepares_missing_table_and_preserves_existing_links(self):
        import runpy
        from unittest.mock import patch

        VehicleCoupling.__table__.drop(db.engine)
        self.app.extensions["dkss"].pop("vehicle_couplings_schema_ready", None)
        vehicle_count = Vehicle.query.count()
        before = self.client.get(f"/vehicle/karte/{self.tractor.id}").get_data(as_text=True)
        self.assertNotIn('data-coupling-open', before)

        hook = runpy.run_path("gunicorn.conf.py")["post_worker_init"]
        with patch("dkss_app.document_import_worker.start_worker") as start_worker:
            hook(SimpleNamespace(wsgi=self.app))
            start_worker.assert_not_called()
        after = self.client.get(f"/vehicle/karte/{self.tractor.id}").get_data(as_text=True)
        self.assertIn('data-coupling-open', after)
        self.assertEqual(self.add().status_code, 302)
        link_id = VehicleCoupling.query.one().id

        with patch("dkss_app.document_import_worker.start_worker"):
            hook(SimpleNamespace(wsgi=self.app))
        self.assertEqual(VehicleCoupling.query.one().id, link_id)
        self.assertEqual(Vehicle.query.count(), vehicle_count)

    def test_csrf_required_and_stale_unlink_does_not_remove_recreated_pair(self):
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.assertEqual(self.add().status_code, 400)
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.add()
        old_id = VehicleCoupling.query.one().id
        remove = f"/vehicle/karte/{self.tractor.id}/couplings/{old_id}/remove"
        self.assertEqual(self.client.post(remove).status_code, 302)
        self.add()
        self.assertNotEqual(VehicleCoupling.query.one().id, old_id)
        self.assertEqual(self.client.post(remove).status_code, 404)
        self.assertEqual(VehicleCoupling.query.count(), 1)
