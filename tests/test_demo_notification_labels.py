"""Only four exact demo display aliases; no stored-message/workflow mutation."""
import ast
import importlib.util
from pathlib import Path
import unittest
from flask import Flask, session
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('labels', ROOT/'dkss_app/demo_label_display.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class NotificationLabels(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__); self.app.secret_key = 'isolated-test'
        self.app.config.update(PUBLIC_DEMO_CANDIDATE=True, PUBLIC_DEMO_SHARED_COMPANY=True, PUBLIC_DEMO_COMPANY='AONAGI')
        for endpoint in ('notifications', 'notification_recent', 'notification_detail', 'other'):
            self.app.add_url_rule('/'+endpoint, endpoint, lambda: '', methods=['GET','POST'])

    def test_exact_display_and_negative_boundaries(self):
        for endpoint in ('notifications', 'notification_recent', 'notification_detail'):
            with self.app.test_request_context('/'+endpoint):
                session.update(aonagi_readonly_demo=True, company_code='AONAGI')
                for nid, (raw, label) in m._NOTIFICATION_LABELS.items():
                    args = dict(raw=raw, company='AONAGI', notification_id=nid)
                    for role in ('driver','admin'):
                        session['role']=role
                        self.assertEqual(m.notification_text(raw, **args), raw.replace(label,'',1))
                    # Both exact full body and its displayed summary use same guard.
                    self.assertEqual(m.notification_text('理由：'+label+'内容', **args), '理由：内容')
                    for changed in ({'company':'OTHER'}, {'notification_id':999}, {'raw':raw+'changed'}):
                        self.assertEqual(m.notification_text(raw, **(args|changed)),raw)
                    session['aonagi_readonly_demo']=False
                    self.assertEqual(m.notification_text(raw,**args),raw)
                    session['aonagi_readonly_demo']=True
                    for key in ('PUBLIC_DEMO_CANDIDATE','PUBLIC_DEMO_SHARED_COMPANY'):
                        self.app.config[key]=False
                        self.assertEqual(m.notification_text(raw,**args),raw)
                        self.app.config[key]=True
                    self.assertEqual(raw, m._NOTIFICATION_LABELS[nid][0])

    def test_non_get_unrelated_endpoint_and_no_context(self):
        for nid,(raw,label) in m._NOTIFICATION_LABELS.items():
            args=dict(raw=raw,company='AONAGI',notification_id=nid)
            self.assertEqual(m.notification_text(raw,**args),raw)
            for endpoint,method in [('notifications','POST'),('other','GET')]:
                with self.app.test_request_context('/'+endpoint,method=method):
                    session.update(aonagi_readonly_demo=True,company_code='AONAGI')
                    self.assertEqual(m.notification_text(raw,**args),raw)

    def test_summary_workflow_and_raw_serialization_unchanged(self):
        tree=ast.parse((ROOT/'dkss_app/notifications.py').read_text())
        summary=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_notification_summary')
        self.assertNotIn('_demo_notification_text',ast.unparse(summary))
        for node in ast.walk(tree):
            if isinstance(node,ast.Dict):
                for key,val in zip(node.keys,node.values):
                    if isinstance(key,ast.Constant) and key.value=='message':
                        self.assertNotIn('_demo_notification_text',ast.unparse(val))
        template=(ROOT/'templates/notification_detail.html').read_text()
        self.assertIn('data-value="{{ full_display_message }}"',template)
        self.assertNotIn('| safe',template)

if __name__=='__main__': unittest.main()
