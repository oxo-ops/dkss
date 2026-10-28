# Q02 点検計画・Excel・実施原本の境界検証（2026-10-28）

基準: `4615ad41e1782069e23137459c2aaee24b5613a0`（PR #243反映後）。
正本の品質改善計画は版1.16・ファイルバージョン22を参照。本補足は正本の置換ではない。

## 追加対象と選定根拠

既存の `test_inspection_plans.py` と `test_inspection_plan_excel.py` は会社・営業所の絞り込み、外国車両ID、一般利用者の更新拒否、トークン改変等を検証している。今回の12件は、これらの再作成ではなく、確認後の権限失効と原本配信時の再照合を対象とする。

| 対象 | 追加した確認 |
| --- | --- |
| 計画と実施のpreview/save | 先に正規のpreviewを成功させ、管理者降格、ロック、利用者削除、パスワード変更、会社停止後の古いセッション・確認トークンを拒否。各URLで古いCookieを再設定し、拒否後に計画・イベント・実施・根拠・原本・車両が変わらないことを確認 |
| 別会社の同名管理者 | 正規にログインした別会社の同名管理者が元会社のトークンでpreview/saveできず、元会社の実施原本も取得できない |
| 一般利用者の閲覧 | 同社の計画API、Excel、実施原本は許可。APIのcan_editはfalse。別会社の車両名・計画メモがAPIとExcelに含まれず、会社コードの差替えで範囲が広がらない |
| ロック・会社停止後の出力 | API、Excel、実施原本をそれぞれ古いセッションで要求して拒否。ファイル本体・ダウンロードヘッダーを返さない |
| 実施原本の再照合 | 登録後に原本の車両紐付け・会社・状態・ハッシュが変わった場合は404。拒否でデータが変わらない |

テスト: `tests/test_q02_inspection_plan_boundaries.py`（12メソッド）。実HTTPのFlaskテストクライアントと一時SQLite、合成データのみ。アプリ本体は変更しない。

## 実行

```powershell
$env:PYTHONPATH = "tests;."
python -m unittest -v test_q02_inspection_plan_boundaries.Q02InspectionPlanBoundaryTests test_inspection_plans.InspectionPlanTests test_inspection_plan_excel.InspectionPlanExcelTests
```

クラス名まで指定し、他モジュールにimportされた既存TestCaseの重複収集を防ぐ。追加12件＋既存53件＋既存Excel9件＝74件。検証ログ・Windows実行結果・PR/CIの証拠は混同しない。

ローカル検証結果: Python 3.12、一時SQLite。配布スクリプトから新規worktreeを作成して上記74件を実行し、30.800秒でOK。追加12件単独も5.064秒でOK。Windows PC実行および新規PRのCIは未実施。

## 状態と未検証

本変更はローカル検証・引渡し用で、push・PR作成・マージは未実施。main反映済みQ02通常DB151件には加算しない。反映後の候補は通常DB163件であり、PostgreSQL専用MFA4件は別環境として扱う。

品質改善計画のQ02状態は引き続き「検証中」。全API・全出力の網羅、実ブラウザー、SMTP/Web Push到達、本番配備版、外部独立レビュー、外部処理開始後の権限失効、MFA以外のPostgreSQL競合・負荷試験を完了扱いにしない。確認トークンは変更確認用であり、作成者専有を仕様として追加しない。日報・Q05・DB移行/復旧は今回の対象外。
