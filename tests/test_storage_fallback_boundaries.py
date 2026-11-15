"""Offline extracted production handlers. Synthetic keys; no network or app startup."""
import ast, io, os, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
class S3Error(Exception):
    def __init__(self, code): self.response={'Error':{'Code':code}}
class FallbackTests(unittest.TestCase):
    def run_case(self,name,code,allowed=True,company='A'):
        client=Mock()
        if name=='uploaded_file':
            client.get_object.side_effect=[S3Error(code), {'Body':io.BytesIO(b'legacy synthetic bytes')}]
        else:
            client.head_object.side_effect=[S3Error(code),{}]
            client.generate_presigned_url.return_value='synthetic signed url'
        app=NS(extensions={'dkss':{'s3_client':client}},config={'S3_BUCKET_NAME':'fake'},logger=Mock())
        common=NS(session={'company_code':company},os=os,request=NS(args={}),ClientError=S3Error,BytesIO=io.BytesIO,redirect=lambda x:(x,302),send_file=lambda *a,**kw:('file',200))
        guard=Mock(return_value=allowed)
        scope={'_dkss_common':common,'_dkss_runtime':NS(app=app),'file_belongs_to_current_company':guard}
        tree=ast.parse((Path(__file__).resolve().parents[1] / 'dkss_app' / 'storage.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-storage.py','exec'),scope)
        result=scope[name](*(['uploads','x.pdf'] if name=='uploaded_file' else ['x.pdf']))
        return result,client
    def test_denied_guard_never_accesses_storage(self):
        for name in ('uploaded_file','s3_uploads_file','s3_manual_file'):
            r,c=self.run_case(name,'404',False);self.assertEqual(r[1],404);self.assertFalse(c.mock_calls)
    def test_no_company_denied_before_storage(self):
        for name in ('uploaded_file','s3_uploads_file','s3_manual_file'):
            r,c=self.run_case(name,'404',company=None);self.assertEqual(r[1],404);self.assertFalse(c.mock_calls)
    def test_missing_can_use_legacy_compatibility(self):
        for name in ('uploaded_file','s3_uploads_file','s3_manual_file'):
            for code in ('404','NoSuchKey','NotFound'):
                r,c=self.run_case(name,code);self.assertIn(r[1],(200,302))
                calls = c.get_object.call_args_list if name == 'uploaded_file' else c.head_object.call_args_list
                prefix = 'manuals' if name == 's3_manual_file' else 'uploads'
                self.assertEqual([x.kwargs['Key'] for x in calls], [f'{prefix}/A/x.pdf',f'{prefix}/x.pdf'])
    def test_nonmissing_errors_fail_closed(self):
        for name in ('uploaded_file','s3_uploads_file','s3_manual_file'):
            for code in ('AccessDenied','SlowDown','InternalError'):
                with self.subTest(name=name,code=code):
                    r,c=self.run_case(name,code);self.assertEqual(r[1],404)
                    calls = c.get_object.call_args_list if name == 'uploaded_file' else c.head_object.call_args_list
                    self.assertEqual(len(calls), 1)
                    self.assertIn('/A/', calls[0].kwargs['Key'])
                    c.generate_presigned_url.assert_not_called()
if __name__=='__main__':unittest.main()
