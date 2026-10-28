# Q12 第2段階：点検画面CSSの後適用

## 原因と最小変更

main bb3a118の点検計画PC再表示でCLS0.2293を再現。
PerformanceObserverの発生源はsection.card.inspection-plansで、
1440×1000の再表示では高さ624.8→313px、y47→55pxに変化した。
vehicle_inspection_plan_panel.htmlの先頭で、本文末尾からCSSを読み込むため、
ページ内容を既存の共通スタイルで先に描画してから専用CSSを適用していた。

base.html:52〜54で、点検計画と共有パネルを含む車両ページのみheadから同じCSSを読む。
panel.htmlからlinkだけを削除。CSS内容・バージョン・JS・イベント・業務データは不変。
プロフィール画像PR #290を含まない、mainから独立したブランチで検証した。
原本の転送量が残るため、この変更だけで画面全体のロードが速くなるとは主張しない。

## 同条件測定

第1段階と同じ架空200台/JPEG2,627,384B、Chrome headless、PC1440×1000、
mobile390×844/DPR2。slowは150ms/下り200,000B/s/CPU4倍。
各訪問1回で統計的評価ではない。初回はHTTPキャッシュ迂回、再表示は有効。
画像PRは含めず、元の原寸プロフィール画像のまま比較。

|点検計画|訪問|CLS 前→後|load完了ms 前→後|FCP ms 前→後|
|---|---|---:|---:|---:|
|PC通常|再表示|0.2293→0.0005|167→205|測定JSON参照|
|PC低速|初回|0.0953→0.0005|19,940→19,946|12,404→11,708|
|PC低速|再表示|0.2293→0.0005|14,264→14,185|544→524|
|mobile低速|初回|0.1940→0.0601|19,954→19,924|12,040→11,416|
|mobile低速|再表示|0.0581→0.0581|14,332→14,366|580→580|

PCの大きい再配置を解消。mobileのデータ取得後の描画によるCLS0.0581は残る。
通常mobileでは前後ともCLS0。SQL/サブリソース容量は変更なし
（PC点検再表示2,634,143Bのまま、主に元画像）。
初回の大きな転送時間は本PRの対象外。

車両概要もPC/mobile/低速で確認。PC通常再表示CLS0.0010→0、
変更後低速mobile初回0.0112/再表示0.0010。低速車両概要の変更前比較は未実施。
共通responsive_layout.jsの全面変更は不要と判断した。

## 回帰

- test_q12_inspection_styles.py: 2件成功。点検計画/概要/履歴/点検/資料/整備/部品/費用/分析の
  実9ルートでhead内のCSS1回・パネルJS1回を検証。無関係な3画面では取得しない。
- 既存test_inspection_plans.py: 53件成功（177.192秒）。
- PC/mobileで設定の開閉、ブラウザ戻る、画像表示、サイドバー復元、JavaScript例外0を確認。
  mobileの設定で400pxスクロール後、ボタンをDOM経由で押して戻り、ブラウザ戻るで400pxへ復元。
  main/画像PR/本PRで同じ結果。PCは当該画面が収まるためスクロール0→0のみ。
- 第1段階で既存JS25件とresponsive_layoutの2群成功。本PRはJSを変えていない。
- mainに既存の運転分析テスト1失敗あり（run40686833082）。
  readerへ切替時account_identityを更新しないテストfixtureが原因。担当外なので変更しない。
  本PR CIを成功扱いにせず最終状態を報告する。

## 再現・残作業

第1段階のbenchmark_display_fixture.py/benchmark_display_browser.cjsを同じコピーで両版に使用。
Q12_ROUTES=/vehicle/inspection-plans、Q12_PROFILES=pc-fast,mobile-fast,pc-slow,mobile-slow。
レイアウト変動の時刻・対象要素・前後矩形をJSONに記録する。
ツールは#290にあり、両PRに重複追加しない。本番/既存DB/実S3は使わない。

残工数：一覧/添付画像8〜14、CSS/公開アイコン6〜10、
SQL/実PostgreSQL6〜10、mobileデータ取得後の配置と実機受入5〜8。
計25〜42人時。共通SQLの修正はQ03/Q08と調整する。
Q05から、CompanyUsageSummary未作成時の並列初回表示で一意制約違反/500の引継ぎあり。
audit.py:108〜の存在確認後INSERTを確認したが、本担当でPostgreSQL再現はしていない。
他担当と重複実装せず、修正の担当/範囲を合わせてから着手する。
