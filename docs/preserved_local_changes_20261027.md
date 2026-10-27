# 退避したローカル変更から必要な3機能を反映

基準main: `68f304b527666a9963856f92a1b2662901d5c329`（PR #207）。
対象は `backup/local-before-main-20261027-134704` から書き出した `dkss_backup_review.txt`。最新版と照合して未反映と確認した以下の3機能だけを移植した。既存の整備費・OCR・分析キャッシュ、日報の権限や画面構成、DB定義は変更しない。

## 保持した変更

| 機能 | 変更後 |
| --- | --- |
| 点検Excel | 実際の絞込みに合わせて営業所を見出し・ファイル名へ反映。会社全体では利用者の既定営業所を付けない。車両指定ではその車両の営業所を使う。ファイル名の禁止文字・改行を除去し長さを制限。年度見出しを簡潔化 |
| 車両候補 | 車番の下に車種を表示。車種が未登録ならボディ形式、それも不明なら空欄。他社車両を候補に含めない。車種はtextContentで表示 |
| 車両履歴 | 種別ラベルを折り返さず、日付列と種別列の幅を調整 |

共有JSの2つの読込み箇所と共通CSSの版を更新し、旧キャッシュで表示が変わらない問題を避ける。

## 照合記録

添付の34ファイル中、22ファイル分は現在のmainと一致、mainに存在した旧版、または同じ変更が最新版に存在していた。5ファイルは一時適用スクリプト・未参照の旧UI資材で、復元対象にしない。未反映の本体変更7ファイルを上記3機能として移植した。

| 退避側のパス | 退避側のGit blob |
| --- | --- |
| dkss_app/vehicle_karte.py | 54b8dcffe35146358fb19de7ccc2450bfc24845f |
| inspection_plan_excel.py | 94447f77d02e50758eba6461b54f8cc6a4365c42 |
| static/css/style.css | 9a7bb6429bf9ce6345c0b1ede69f1c4829ab0649 |
| static/js/vehicle_karte_selector.js | 15bbf2f51c462345caf978fc550214d8c6b3b1fe |
| templates/ocr_searchable_select_assets.html | a2e87698e1ac866b232c7d496c762d39d6d2d567 |
| tests/test_inspection_plan_excel.py | 8a25c21d899d2a2d453f9f8cb2e3c16513199f77 |
| vehicle_inspection_plans.py | 0640b5ae774364583271413472f9489594e5617e |

添付の日本語には出力時の文字化けがあるため、パッチ全体を直接適用せず、Gitのblob情報と現行コードを照合して必要な変更をUTF-8で移植した。古いファイル全体の上書きではない。

旧UIの `vehicle_karte_overview_20261026_v7.css` と `.js`、適用用の `add_inspection_year_excel_20261026.py`・`adjust_import_spacing_20261026.py`・`apply_inspection_excel_after_merge_20261026.py` は追加しない。配布用bundle・zipもアプリ本体には含めない。

## 確認

点検Excelの会社・営業所・車両のスコープ、保存名の禁止文字、会社境界、車種の代替表示と不明表示、JSでの安全な文字列表示と選択動作を確認する。既存の年度月列・帳票印刷設定・読取り専用性・他社分離の検証も維持する。

DB移行は不要。PC内の退避ブランチはこの作業では削除していない。mainへのマージ確認後に不要な退避データを再判定する。GitHub未反映の状態で退避を削除しない。


最終結果: Python回帰テスト649件、JavaScript 8件、レスポンシブ確認、スキーマ生成一致、compileall、git diff --checkが成功した。実ブラウザでの全画面確認は未実施。
