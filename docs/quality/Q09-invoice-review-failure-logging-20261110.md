# Q09 請求書確認の保存失敗ログ

基準は公開済み #368 `07ed6aa4151ade76892226cc9491e699aefe67ce`。
品質改善Wordの第26章「ログの保持と閲覧を管理する」にある、秘密値や不要な
個人情報を出力しない方針への限定対応です。#369の画面表示と#370の資料取込ログは
含めず、公開・マージは別途判断します。

## 対象

`dkss_app/vehicle_documents.py` の3つのSQLAlchemy例外ハンドラーだけを対象にします。

- 登録済み請求書の確認。
- 初回費用・追加請求・請求訂正の確認。
- 交換部品の確認。

従来の `logger.exception` はSQL文・引数・例外チェーンを含み得ます。
架空のSQL例外でこの出力を再現する検証を用い、実データの漏えいがあったとは
断定しません。例外本文・動的な型名・tracebackをログへ渡さない方式へ変更します。

## 診断イベント

`INVOICE_REVIEW_FAILED action=<action> error_type=<category>`

ERRORレベルを維持します。actionは `already_recorded`、`initial_cost`、
`additional_cost`、`correction`、`parts_review` の既知の文字列だけです。
未知値やstr派生型は `unknown` に置き換えます。

error_typeは既知のSQLAlchemy型によって `integrity`、`operational`、`data`、
`statement`、`database` に分類し、それ以外は `unexpected` とします。
SQL・DB接続先・利用者・会社・文書ID・金額・原本名・SQLSTATE・原文は出力しません。
例外の具体的な発生段階や根本原因をこの分類だけで確定してはいけません。

既存監視が「請求書の確認結果を保存できませんでした。」、
「初回の請求費用を保存できませんでした。」、
「請求書の交換部品を保存できませんでした。」に一致させている場合、
採用時には新イベントと対応actionへのマッピングを確認してください。
外部監視の設定変更・通知到達は今回の実装に含みません。

## 維持する境界

権限・会社スコープ・原本検証・入力検証・版確認・ロック順・金額計算・履歴・
commit/rollback・HTTP応答・再試行条件は変更しません。DBモデル・スキーマ・
依存版・起動保護・TLS/CA・サービス設定も変更しません。

既存Q07の業務修正を再実装するものではありません。対象ハンドラー以外のログ、
rollback自体の失敗、上位ログハンドラーの追加情報、ログ保持・閲覧権限、
実PostgreSQL・外部AI・運用受入は別の範囲です。

## 検証の入口

新規の使い捨てSQLiteと架空原本のみを使い、外部サービスへ接続しません。

`PYTHONPATH=.:tests python -m unittest -v test_invoice_review_safe_logging test_invoice_review_logging_metadata`

WindowsのPYTHONPATH区切りは `;` です。最終対象SHA/tree、修正前後の結果、
独立レビューと自動CIの実測値はPRに記録します。既存の合格件数を新しい検証の
成功件数へ合算しません。全品質改善や本番受入の完了を意味しません。
