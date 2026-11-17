import unittest
from preflight import validate
class Gate(unittest.TestCase):
 def test_only_local_fixture_allowed(self):
  v='postgresql+psycopg2://dkss_logout_ci:synthetic@127.0.0.1:55432/dkss_q02_ci'
  self.assertEqual(validate(v),v)
 def test_external_or_overrides_rejected_without_secret(self):
  for v in ['', 'sqlite://', 'postgresql://u:secret@db.example.com/prod','postgresql://dkss_logout_ci:secret@127.0.0.1:5432/dkss_q02_ci','postgresql://dkss_logout_ci:secret@127.0.0.1:55432/prod','postgresql://dkss_logout_ci:secret@127.0.0.1:55432/dkss_q02_ci?host=db.example.com','postgresql://dkss_logout_ci:secret@localhost:55432/dkss_q02_ci']:
   with self.subTest(case=v.split(':')[0]):
    with self.assertRaises(ValueError) as e:validate(v)
    self.assertNotIn('secret',str(e.exception));self.assertNotIn('example.com',str(e.exception))

class CallbackContract(unittest.TestCase):
 def test_authentication_callback_tuple_contract(self):
  import ast
  from pathlib import Path
  module=ast.parse(Path(__file__).with_name('test_postgres.py').read_text())
  cls=next(x for x in module.body if isinstance(x,ast.ClassDef) and x.name=='LogoutPG')
  method=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='authenticated')
  ns={};exec(compile(ast.Module(body=[method],type_ignores=[]),'<isolated-callback>','exec'),ns)
  class Client:
   def get(self,path):return type('Response',(),{'status_code':200})()
  client=Client();self.companies=['synthetic'];self.pending=lambda company:(client,'fake-code')
  self.submit=lambda c,code:(302,('synthetic','same'))
  self.assertIs(ns['authenticated'](self),client)
  self.submit=lambda c,code:(302,('other-company','same'))
  with self.assertRaises(AssertionError):ns['authenticated'](self)

if __name__=='__main__':unittest.main()
