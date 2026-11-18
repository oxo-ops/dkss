"""Menu guidance follows real shared navigation, never imagined role permissions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MenuGuideCopyTests(unittest.TestCase):
    def test_names_are_present_in_shared_navigation(self):
        template = (ROOT / 'templates/base.html').read_text()
        guide = (ROOT / 'static/js/first_use_guide.js').read_text()
        for name in ('安全管理', '車両管理'):
            self.assertIn(f'<span class="menu-text">{name}</span>', template)
            self.assertIn(f'「{name}」', guide)
        self.assertIn('メニューを開き、', guide)
        self.assertIn('使いたい画面を選べます。', guide)
        self.assertNotIn('点検や車両の一覧へ移動できます', guide)

    def test_no_role_only_menu_is_promised_to_everyone(self):
        guide = (ROOT / 'static/js/first_use_guide.js').read_text()
        self.assertNotIn('マスタ管理', guide)
        self.assertNotIn('登録URL・申請', guide)

    def test_new_copy_can_bypass_stale_asset_cache_without_resetting_seen(self):
        partial = (ROOT / 'templates/partials/first_use_guide.html').read_text()
        guide = (ROOT / 'static/js/first_use_guide.js').read_text()
        self.assertIn("v='20261118-native-detail-3x-right-1'", partial)
        self.assertIn("dkss:first-guide:v1:", guide)

if __name__ == '__main__':
    unittest.main()
