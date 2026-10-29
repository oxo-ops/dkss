"""Fresh-proof adaptation must not insert a GET into Q04's POST schedule."""
import unittest
from unittest.mock import patch

from flask import Flask, session
from patrol_form_fixture import fresh_patrol_data


class PatrolFixtureTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = 'synthetic-fixture-only'
        self.client = app.test_client()
        with self.client.session_transaction() as state:
            state.update(company_code='A', account_identity='synthetic-actor')

    def fresh(self, path):
        data = {'target_type':'user', 'target_user':'synthetic-subject'}
        def issue():
            self.assertEqual(session['company_code'],'A')
            self.assertEqual(session['account_identity'],'synthetic-actor')
            return 'synthetic-signed-proof'
        with patch.object(self.client,'get',side_effect=AssertionError('Unexpected GET inside POST gate')), patch('dkss_app.person_selection.issue',side_effect=issue):
            result = fresh_patrol_data(self.client,path,data)
        self.assertEqual(result,{**data,'person_selection_token':'synthetic-signed-proof'})
        self.assertNotIn('person_selection_token',data)

    def test_new_form_does_not_add_a_candidate_get(self): self.fresh('/pointouts/new')
    def test_edit_form_does_not_add_a_candidate_get(self): self.fresh('/pointouts/42/edit')

    def test_explicit_old_empty_and_forged_proofs_are_preserved(self):
        for proof in ('old-proof','','tampered-proof'):
            with self.subTest(proof=proof):
                data={'target_user':'subject','person_selection_token':proof}
                with patch('dkss_app.person_selection.issue',side_effect=AssertionError('Must not refresh explicit proof')):
                    self.assertIs(fresh_patrol_data(self.client,'/pointouts/42/edit',data),data)

    def test_other_routes_and_nonpersonal_targets_are_unchanged(self):
        for path,data in [('/pointouts/new',{'target_type':'delivery_place','target_user':'unused'}),
                          ('/notifications',{'target_type':'user','target_user':'subject'}),
                          ('/pointouts/42/edit',{'content':'only'})]:
            with patch('dkss_app.person_selection.issue',side_effect=AssertionError('Out of scope')):
                self.assertIs(fresh_patrol_data(self.client,path,data),data)
