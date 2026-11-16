import os
import unittest
from unittest.mock import patch
from flask import Flask
from dkss_app.public_demo_release import load

class DemoReleaseConfigTests(unittest.TestCase):
    def env(self):
        return {'PUBLIC_DEMO_ENABLED':'true','PUBLIC_DEMO_COMPANY':'SYNTHETIC',
            'PUBLIC_DEMO_DRIVER':'demo.driver','PUBLIC_DEMO_MANAGER':'demo.manager',
            'PUBLIC_DEMO_DRIVER_IDENTITY':'11111111-1111-4111-8111-111111111111',
            'PUBLIC_DEMO_MANAGER_IDENTITY':'22222222-2222-4222-8222-222222222222',
            'PUBLIC_DEMO_FROM':'1800000000','PUBLIC_DEMO_UNTIL':'1800003600','PUBLIC_DEMO_EPOCH':'isolated'}
    def app(self):
        app=Flask(__name__);app.config['RATELIMIT_STORAGE_URI']='redis://localhost:6379/15';return app
    def test_default_off(self):
        with patch.dict(os.environ,{'PUBLIC_DEMO_ENABLED':'false'}):
            app=self.app();load(app);self.assertNotIn('PUBLIC_DEMO_CANDIDATE',app.config)
    def test_release_requires_explicit_window_and_two_identities(self):
        with patch.dict(os.environ,self.env()):
            app=self.app();load(app)
            self.assertTrue(app.config['PUBLIC_DEMO_SHARED_COMPANY'])
            self.assertEqual(app.config['PUBLIC_DEMO_USERNAME'],'demo.driver')
            self.assertNotIn('PUBLIC_DEMO_VEHICLE_ID',app.config)
    def test_invalid_release_config_fails_closed(self):
        for key,value in [('PUBLIC_DEMO_MANAGER','demo.driver'),('PUBLIC_DEMO_UNTIL','1799999999'),('PUBLIC_DEMO_FROM',''),('PUBLIC_DEMO_DRIVER_IDENTITY','not-an-identity')]:
            with self.subTest(key=key),patch.dict(os.environ,{**self.env(),key:value}):
                with self.assertRaises(RuntimeError):load(self.app())
    def test_memory_storage_not_allowed_for_release(self):
        with patch.dict(os.environ,self.env()):
            app=self.app();app.config['RATELIMIT_STORAGE_URI']='memory://'
            with self.assertRaises(RuntimeError):load(app)
