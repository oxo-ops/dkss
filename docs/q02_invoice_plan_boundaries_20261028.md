# Q02 請求書実施表示の会社と認証の境界

## 対象

PR #251で追加された点検計画APIの `invoice_actuals` と `sources` の境界を検証する。
既存の `test_invoice_plan_actuals.py` は表示・日付・紐付け、PR #248は計画と実施原本が主対象。
今回は請求書を持つ2社を実際の取込確定経路で用意し、閲覧者の切替と失効を追加する。
アプリ本体の変更はない。Q05の種類判定・日付・登録車両選択は変更しない。

## 新規6件

| 条件 | 期待結果 |
| --- | --- |
| 管理者を一般ユーザーへ降格し、古い管理者Cookieで閲覧 | 自社の請求書表示と複数原本の閲覧は維持。can_edit=false。他社内容・ファイル名を含まない |
| 同名管理者で別会社へ切替、会社コード・車両・原本IDを差替え | 自社請求書は表示。元会社の表示範囲と原本は取得不可。自他社の車両と原本の交差指定も404 |
| 閲覧後の利用者ロック | APIは401、元の原本URLはログインへ戻る |
| 閲覧後の利用者削除 | APIは401。他社の同名利用者が存在しても代用されない |
| 閲覧後のパスワード変更 | 古いCookieでAPI・原本を取得できない |
| 閲覧後の会社停止 | APIは403、原本URLはログインへ戻る |

拒否対象URLのそれぞれで古い認証情報を再設定する。先行要求でログアウトした状態に依存しない。
各経路で整備・変更履歴・書類・下書き原本・計画・計画履歴・実施・根拠・部品・車両の全列を比較し、業務データが変わらないことも確認する。

## 実行

```powershell
$env:PYTHONPATH = "tests"
py -3 -m unittest test_q02_invoice_plan_boundaries.Q02InvoicePlanBoundaryTests test_invoice_plan_actuals.InvoicePlanActualTests test_q02_inspection_plan_boundaries.Q02InspectionPlanBoundaryTests test_q02_import_document_boundaries.Q02ImportDocumentBoundaryTests -v
```

クラス名指定でimportされた既存TestCaseの重複収集を防ぐ。
新規6件＋既存の請求書11件・点検計画境界12件・取込書類境界10件＝39件。
新規6件単独は4.174秒、関連39件は17.378秒で成功（main bab5d1b、実Flask・一時SQLite）。
利用者PC・PR・マージ後CIはこの文書作成時点では未確認。

## 到達範囲

通常DB向け163件とPostgreSQL専用MFA4件は既存main反映分。今回6件は未反映の追加分。
39件は関連試験であり、Q02全件の一括実行でもPostgreSQL試験でもない。
実ブラウザ、SMTP/Web Push、外部処理開始後の失効、実PostgreSQLの業務競合・負荷、本番配備、外部独立レビューは対象外。
Q02全体は引き続き検証中。
