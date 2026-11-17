"""Full safety content stays intact, escaped and reachable without JS."""
import unittest
from test_dashboard_safety_attention import DashboardSafetyAttentionTests as Base

class DashboardMobileDisclosureTests(unittest.TestCase):
    setUpClass=classmethod(Base.setUpClass.__func__)
    tearDownClass=classmethod(Base.tearDownClass.__func__)
    setUp=Base.setUp
    tearDown=Base.tearDown
    configure=Base.configure
    page=Base.page
    patrol=Base.patrol
    def test_long_record_keeps_complete_first_sentence_and_full_content(self):
        self.configure()
        text='【体験用・架空】'+('路面と歩行者動線の確認。'*50)+'接触・負傷なし。'
        row=self.patrol(text, countermeasure_due_date='2026-11-19')
        html,root=self.page()
        card=root.find(cls='dashboard-safety-content')[0]
        details=card.find(cls='dashboard-safety-story')[0]
        summary=card.find(cls='dashboard-safety-opening')[0]
        self.assertIn('路面と歩行者動線の確認。',summary.text)
        self.assertNotIn('【体験用・架空】',summary.text)
        self.assertIn('冒頭の文を表示',summary.text)
        self.assertEqual(summary.attrs['href'],f'/pointouts/{row.id}')
        self.assertNotIn('…',summary.text)
        self.assertIn(text,details.text)
        self.assertEqual(details.find(tag='a')[0].attrs['href'],f'/pointouts/{row.id}')
        self.assertIn('2026-11-19',card.text)
        self.assertNotIn('2026-11-19',details.text)
        self.assertIn('写真と対策内容を確認',card.text)
        self.assertNotIn('写真と対策内容を確認',details.text)
    def test_short_record_keeps_direct_link_and_escaped_content(self):
        self.configure();self.patrol('<img src=x onerror=alert(1)> 負傷なし。')
        html,root=self.page();card=root.find(cls='dashboard-safety-content')[0]
        self.assertFalse(card.find(cls='dashboard-safety-story'))
        self.assertIn('負傷なし',card.find(tag='a')[0].text)
        self.assertNotIn('<img src=x onerror=alert(1)>',html)

    def test_no_sentence_or_overlong_sentence_uses_neutral_heading(self):
        self.configure()
        for text in ['異常とは判断していない確認中の記録'*20, '確認中の内容'*30+'。続き。', '「引用文。まだ引用内の文」'+'続き'*40]:
            row=self.patrol(text)
        _,root=self.page()
        for opening in root.find(cls='dashboard-safety-opening'):
            self.assertIn('記録の内容・確認事項',opening.text)
    def test_three_reference_records_have_distinct_complete_openings(self):
        self.configure()
        examples=[
          '【体験用・架空】雨天の構内で路面が滑りやすいことを確認し、減速して停止位置を手前に変更した。接触・負傷なし。確認事項：天候に応じた速度と歩行者動線の確認。',
          '【体験用・架空】102号車の荷卸し前照合で荷札の向きが分かりにくいことに気付き、照合しやすい向きへ整理した。誤納・破損なし。確認事項：積込時と荷卸し時の二重照合。',
          '【体験用・架空】102号車の荷卸し準備で荷台端の荷物に緩みを発見し、作業を止めて固定を確認した。落下・破損・負傷なし。改善の確認事項：出発前と荷卸し前に固定状態を確認する。']
        for text in examples:self.patrol(text,countermeasure_due_date='2026-11-19')
        _,root=self.page()
        titles=[d.text for d in root.find(cls='dashboard-safety-story-title')]
        self.assertEqual(set(titles),{s.removeprefix('【体験用・架空】').split('。',1)[0]+'。' for s in examples})
        self.assertEqual(len(set(titles)),3)
        for full in examples:self.assertIn(full,root.text)

# Do not rediscover the imported source TestCase as extra tests.
del Base
