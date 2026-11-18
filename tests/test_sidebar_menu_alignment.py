"""Guard the shared sidebar alignment without changing navigation behaviour."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SidebarMenuAlignmentTests(unittest.TestCase):
    def test_direct_links_do_not_override_shared_horizontal_padding(self):
        css = (ROOT / 'static/css/style.css').read_text()
        direct = re.search(r'\.sidebar-nav > a\.menu-item\s*\{([^}]+)\}', css).group(1)
        self.assertNotRegex(direct, r'padding(?:-left|-right)?\s*:')
        common = re.search(r'\n\.menu-item\s*\{([^}]+)\}', css).group(1)
        parent = re.search(r'\n\.sidebar-parent\s*\{([^}]+)\}', css).group(1)
        self.assertIn('padding: 0 18px;', common)
        self.assertIn('padding: 0 18px;', parent)

    def test_direct_link_labels_have_no_vertical_nudge(self):
        css = (ROOT / 'static/css/style.css').read_text()
        self.assertNotIn('.sidebar-nav > a.menu-item .menu-text {', css)
        self.assertNotIn('.sidebar nav a {', css)
        self.assertIn('.sidebar nav a:not(.menu-item) {', css)

    def test_existing_responsive_and_collapsed_rules_remain(self):
        css = (ROOT / 'static/css/style.css').read_text()
        self.assertIn('body.sidebar-collapsed .sidebar-nav > .menu-item:first-child {', css)
        self.assertIn('padding: 0 !important;', css)
        self.assertIn('.menu-item,\n    .sidebar-nav > .menu-item:first-child {', css)

    def test_asset_version_and_navigation_semantics(self):
        html = (ROOT / 'templates/base.html').read_text()
        self.assertIn("v='20261118-sidebar-alignment-2'", html)
        self.assertIn('<a href="/" class="menu-item', html)
        self.assertIn('<button type="button" class="menu-item sidebar-parent">', html)


if __name__ == '__main__':
    unittest.main()
