import ast, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from flask import Flask, request, session, redirect
class Query:
    def __init__(self,row):self.row=row
    def filter_by(self,**kw):return self
    def first(self):return self.row
class StaticBoundary(unittest.TestCase):
    def test_other_company_path_denied(self):
        with tempfile.TemporaryDirectory() as root:
            static=Path(root)/'static'
            for folder in ('uploads','manuals'):
                for company in ('A','B'):
                    p=static/folder/company;p.mkdir(parents=True);(p/'same.pdf').write_bytes(('SYNTHETIC '+company).encode())
                (static/folder/'same.pdf').write_bytes(b'SYNTHETIC legacy')
            app=Flask(__name__,static_folder=str(static),static_url_path='/static');app.secret_key='synthetic-only'
            user=NS(login_locked=False,account_identity='identity-A',password_changed_at=None,role='user',last_name='',first_name='',office='',company_code='A')
            # Actual authorization helper with all unrelated models empty. A owns a profile reference with same basename.
            models=NS(User=NS(query=Query(NS(profile_image='same.pdf'))))
            common=NS(request=request,session=session,redirect=redirect,os=os)
            scope={'_dkss_common':common,'_dkss_models':models}
            tree=ast.parse((Path(__file__).resolve().parents[1] / 'dkss_app' / 'storage.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='file_belongs_to_current_company')
            exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-storage.py','exec'),scope)
            access_scope={'_dkss_common':common,'_dkss_models':NS(User=NS(query=Query(user)),Company=NS(query=Query(NS(active=True)))),'_dkss_storage':NS(file_belongs_to_current_company=scope['file_belongs_to_current_company'])}
            tree=ast.parse((Path(__file__).resolve().parents[1] / 'dkss_app' / 'access.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='require_login')
            exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-access.py','exec'),access_scope)
            app.before_request(access_scope['require_login'])
            with app.test_client() as c:
                with c.session_transaction() as s:s.update(username='synthetic-user',company_code='A',account_identity='identity-A',password_changed_at=None)
                for folder in ('uploads','manuals'):
                    own=c.get(f'/static/{folder}/A/same.pdf');self.assertEqual(own.status_code,200);self.assertEqual(own.data,b'SYNTHETIC A');own.close()
                    legacy=c.get(f'/static/{folder}/same.pdf');self.assertEqual(legacy.status_code,200);self.assertEqual(legacy.data,b'SYNTHETIC legacy');legacy.close()
                    for path in (f'/static/{folder}/B/same.pdf',f'/static/{folder}/%42/same.pdf',f'/static/{folder}/A/../B/same.pdf'):
                        with self.subTest(path=path):
                            other=c.get(path)
                            print('status=',other.status_code,'foreign_synthetic_bytes_returned=',other.data==b'SYNTHETIC B')
                            try:self.assertEqual(other.status_code,404)
                            finally:other.close()
                with c.session_transaction() as s:s.clear()
                r=c.get('/static/uploads/A/same.pdf');self.assertEqual(r.status_code,302);r.close()
if __name__=='__main__':unittest.main()
