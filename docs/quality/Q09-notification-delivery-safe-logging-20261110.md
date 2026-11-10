# 通知配信失敗ログの情報保護

## 対象と目的

品質改善Word「輸送版DX 品質改善と検証計画 4社見積反映 確認用 20261110」の26.3.5、Q08・Q09に対応する限定修正です。SMTP通知、同じ送信関数を利用するMFAコード、メールアドレス変更確認、Web Pushの失敗ログから、外部例外の本文・tracebackを取り除きます。宛先、認証情報、コード、本文、Push endpoint等が例外に含まれても、これらの捕捉済みエラー経路からログへ渡しません。

PR #361のソースtreeを基点とする独立候補です。PR #363は添付削除、#364は履歴・ナビ表示、#362は隔離された条件プレビューが対象で、本修正と製品ファイルが重複しません。品質計画全体やログ管理全体の完了ではありません。

## 記録する情報

SMTPは固定イベント `EMAIL_DELIVERY_FAILED` と固定値のみを記録します。

- purpose: notification / email_change。MFAは従来どおり通知メール関数を経由するためnotificationに含まれます。
- stage: connect / starttls / authenticate / send / close。
- error_type: authentication / recipient_refused / sender_refused / data_rejected / tls / connection / smtp / unexpected。
- 呼出側のpurposeとstageが許可された文字列でなければunknownに置き換えます。任意の例外クラス名やSMTP返信本文・コード・宛先辞書を記録しません。

stageは「最後に開始した操作」です。先の操作の失敗を処理中にSMTPコンテキスト終了も失敗すると、最終例外とstageの発生箇所が異なる場合があります。この変更では元の例外処理・送信成否の意味を変えません。closeの失敗は送信前失敗を意味しないため、自動再送を判断する根拠にはしません。

Web Pushは固定イベント `WEB_PUSH_SEND_FAILED` とprovider（既知のWebPushException、WARNING）またはunexpected（その他、ERROR）だけを記録します。response本文・endpoint・鍵・例外名はログに渡しません。

## 維持する動作

SMTP接続先、20秒timeout、STARTTLS、認証順序、送信内容、通知のopt-in、MFAのopt-in除外、戻り値、捕捉例外、自動再送なしを維持します。Web Pushの所有者条件、payload、TTL300秒、timeout20秒、後続購読の処理、404/410だけの購読削除・commit、cleanup失敗の伝播を維持します。

DBモデル、schema、既存データ、起動・初期化、依存ライブラリ、Render設定、Start Commandは変更しません。再復元・再初期化・本番送信・merge/deployは実施していません。

## 検証範囲

- 新規27件: 実モジュール関数を呼び出し、SMTP/Web Push/DBをmock化。成功、各SMTP失敗段階・分類、MFA/確認コード、非通知設定、404/410、response無し、後続購読成功、cleanup失敗、例外のstr/repr禁止、provider本文読取禁止を確認。27件成功、skip0、ネットワーク/DB接続試行0。
- 既存21件: 変更したauthと同じアプリ構成を通るMFA境界15件、CSRF6件だけを対象に実行。合成SQLite2個の接続、メールmock、外部通信禁止。21件成功、skip0、禁止IO試行0。
- 修正前契約試験は20件実行、13失敗（subtestを含む）で不足を再現。初回runnerのimport-path不備は別記録とし、検証成功には数えません。
- 独立静的レビューで阻害指摘なし。提案された境界を追加して再レビュー済み。

標準実行は `python -m unittest discover -s tests -p 'test_notification_delivery_safe_logging.py'` です。厳格な隔離実行記録・runnerは納品する監査資料に含めます。実環境の設定や資格情報を引き継がず、合成値だけで実行します。

## 残事項

全体回帰CI、他PRとの統合版検証、実運用loggerのfilter/handlerの追加情報、他の例外経路、保持期間、閲覧権限、保管先、監視の通知到達・受付は別作業です。監視が旧日本語ログ本文を条件にしている場合は、採用時に固定イベントへの照合変更が必要です。稼働中の監視設定は今回変更していません。

採用前はこの独立patchを戻せます。将来承認されて配備した後の切戻しは、同じ008ed6e復旧修正を保持した採用直前ソースへ戻し、既存Start CommandのSHA固定条件との一致を確認する手順に接続します。DB逆移行・再復元は不要です。現時点の本番反映承認を意味しません。
