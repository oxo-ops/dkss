"""Pinned public trust material audit; no application or database imports."""
import hashlib
import json
from pathlib import Path
import ssl
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'


class M01PublicCaTests(unittest.TestCase):
    def test_upstream_pin_and_certificate_structure(self):
        manifest = json.loads((ROOT / 'ca/provenance.json').read_text(encoding='utf-8'))
        pem = ROOT / 'ca' / manifest['bundle_file']
        raw = pem.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b')
        self.assertEqual(manifest['bundle_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(raw.count(b'-----BEGIN CERTIFICATE-----'), 118)
        self.assertNotIn(b'PRIVATE KEY', raw)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cafile=str(pem))
        self.assertEqual(ctx.cert_store_stats()['x509_ca'], 118)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_distribution_notice_and_no_runtime_download(self):
        manifest = json.loads((ROOT / 'ca/provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['license'], 'MPL-2.0')
        self.assertTrue(manifest['unchanged_from_official_wheel'])
        self.assertFalse(manifest['yanked'])
        self.assertTrue(manifest['wheel_url'].startswith('https://files.pythonhosted.org/'))
        self.assertIn('Mozilla Public License Version 2.0',
                      (ROOT / 'ca/MPL-2.0.txt').read_text(encoding='utf-8'))
        self.assertIn('MPL', (ROOT / 'ca/CERTIFI-LICENSE.txt').read_text(encoding='utf-8'))
        source = (ROOT / 'm01_client_tls.ps1').read_text(encoding='utf-8')
        for forbidden in ('Invoke-WebRequest', 'Invoke-RestMethod', 'Start-Process', 'TcpClient'):
            self.assertNotIn(forbidden, source)
        patch = (ROOT / 'm01_client_tls_launcher.patch').read_text(encoding='utf-8')
        helper_hash = hashlib.sha256((ROOT / 'm01_client_tls.ps1').read_bytes()).hexdigest()
        self.assertIn("$expectedTlsHelperHash = '" + helper_hash + "'", patch)
        self.assertNotIn('dpg-', patch)
        self.assertNotIn('postgresql://', patch)


if __name__ == '__main__':
    unittest.main()
