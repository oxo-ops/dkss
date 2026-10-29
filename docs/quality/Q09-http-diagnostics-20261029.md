# Q09 HTTP共通例外ログの限定修正

基準mainは`1741c64426f75f682a331f99b9249a45caf7a612`（#329マージ後）。
#329の導入・設定・停止・CI・DB変更追跡資料、OCRの2ログ経路は変更しない。
Q06・Q10とQ05の開発完了状態は維持する。

## 再現と変更

`handle_unexpected_error`はrollback後に`logger.exception`を呼んでいた。
実HTTP要求で発生させたSQLiteのNOT NULL違反では、例外に含まれるINSERTの
バインド値がログへ出た。模擬StatementErrorのSQL文・接続情報・例外チェーンも
同じ経路で出力された。利用者向けAPI応答へ出る問題とは区別する。
架空値だけの一時SQLiteを使用し、本番・保護DB・実外部サービスへ接続していない。

#329と同じく、例外本文やtracebackを出さない固定イベントへ置き換えた。

```text
HTTP_UNEXPECTED_ERROR stage=request error_type=IntegrityError
```

固定識別コード・処理段階・例外種別を保持する。URL・パス・クエリ・フォーム値・
SQL・接続情報・例外の原文/チェーンは記録しない。リクエスト相関IDの導入や
全機能のログ形式変更は対象外。その他のログに秘匿を保証する変更でもない。

製品差分は`dkss_app/http.py`の当該ログ呼出しだけ。rollbackの順序、
HTTPExceptionの分岐、HTMLの安全な戻り先とflash、API/plain応答、
取込の確認画面へ戻る案内・JSON errors・no-storeヘッダーは変更しない。

## 再現テストと応答の保持

`tests/test_q09_http_diagnostics.py`の8件は、実アプリを生成し、認証した
Flask test clientのHTTP要求から既存エラーハンドラーを通す。
直接のハンドラー単体呼出しやloggerのmockだけではない。
一時SQLiteの実制約違反と実rollbackを検証する。
取込では既存endpointのviewだけへ故障を注入し、HTTP処理・認証・復帰画面を実行する。
取込業務そのものの正常・再試行は既存の関連回帰を利用する。

- 実SQL制約違反のAPI500、バインド値の非出力、未確定変更のrollback、正常再試行。
- 模擬SQL例外の接続情報・チェーン・SQL文の非出力。
- HTMLの302/flash、非HTMLのplain 500。
- 取込HTML/JSONの500、復帰案内と既存ヘッダー。
- HTTPExceptionの429、Retry-After、取込の復帰応答。予期しない障害ログは出さない。

ログrecordの`exc_info`/`stack_info`がなく、固定コードと例外種別だけであること、
架空秘密値・URLパス・クエリ・送信内容を記録しないことも検査する。
CSRFを無効にする設定は隔離fixture内だけ。製品設定は変更しない。

同じ8件は修正前に6失敗・2成功・エラー/skipなし（9.269秒）、
修正後に8成功・失敗/エラー/skipなし（15.471秒）。期待値や入力を変えて通していない。
関連回帰と最終headのCI結果はPR本文・最終報告へ記録する。

```text
PYTHONPATH=.:tests python -m unittest -v test_q09_http_diagnostics.HTTPDiagnosticsTests
```

WindowsのPYTHONPATH区切りは`;`。代表回帰は既存ImportFlow、Q02 CSRF、
ApplicationFoundation、Q10のHTTP業務フローを再利用する。
これは移行主管の6処理/388件、Q11復旧、Q12性能、Q03/Q08本人識別の再実装・
専用受入の再実行ではない。DB定義・移行・外部サービス構成は変更しない。

## 重複を除いた残工数

旧Q09の8〜16人時に含めた資料統合・導入手順・OCRログ・Linux起動確認は、
#329の成果/担当範囲として除外する。本担当の残対象はこのHTTPログ修正のみ。
本修正・関連回帰・PR/CI確認と引渡しが完了すれば、担当範囲の残実装は0人時。
#329側の運用構成・判断待ちの2〜4人時は本担当へ加算しない。
Q06・Q10の完了工数へ戻して計上しない。本番運用やログ全体の監査完了は意味しない。
