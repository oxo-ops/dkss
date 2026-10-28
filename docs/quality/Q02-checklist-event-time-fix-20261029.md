# Q02 日常点検イベント日時の保存修正

基準main `0832720`（#283・#297反映）。Q10修正前は専用PostgreSQL18.6の29件中12失敗。うち8件は初回セル保存でSQLSTATE22001。`driving_vehicle_links.preserve_inspection_origin`はJSTのISO日時（例 `2026-10-29T07:00:38.516391+09:00`、32文字）を作り、ChecklistEvent.created_atはVARCHAR(30)だった。

生成する日時・タイムゾーン・精度は変更せず、ORMとPostgreSQLの保存幅を40へ広げる。既存の19文字日時、SQLiteに保存済みの32文字ISO日時、イベントのdetail_json・人物・点検対象日は書き換えない。起点候補の認定はdetail_jsonと点検対象日を使い、created_atの文字数を本人判定には使っていない。既存のDrivingVehicleCorrection.created_atも40文字である。新旧日時の意味や並び順を変更するデータ変換は行わない。

## 既存DBの適用順

実DBへは実施していない。検証/運用担当が書込・ワーカー停止とバックアップを確認し、明示した対象へ `Q02_TIMESTAMP_MIGRATION_DATABASE_URL=... python tools/upgrade_checklist_event_timestamps.py` を実行してから新版を起動する。汎用DATABASE_URLへのフォールバックはない。PostgreSQLはVARCHARを40へ拡幅するだけで、繰返し実行は変更しない。既に40以上/無制限の文字列は縮小しない。SQLiteのVARCHARは長さを強制しないため、旧表の再構築・行書換えをしない。文字列以外の独自スキーマは停止して調査する。

移行はDDLロックを取るため、実データ量での停止時間は別途確認が必要。旧アプリへ戻しても列幅を30へ縮小しない。起動/GETでの自動DDLは追加していない。

## 検証とQ10の保全

SQLiteで旧VARCHAR(30)宣言にある19/32文字値を保持し、PostgreSQLで旧幅による32文字拒否→拡幅→元の値を保持したまま32文字保存、冪等性を検証する。既存Q02日常点検6ケースをPGで再利用する。

Q10テストの本体・入力・期待値は変更しない。500解消後に、元のQ02正常2ケースが呼ぶassert_integrityをQ10の共有アダプターへ接続し忘れていたことが判明したため、`test_q10_business_flows.DailyFlowFailuresTests`に元の検査メソッドのaliasを1行追加した。検査をskip/削除する変更ではなく、従来500に阻まれていた回答・履歴・整備整合性の検査を実行する修正である。

OCR所有者の問題は別ブランチ/PRで修正する。このPR単独ではQ10のOCR4失敗を成功扱いしない。最終CIと固定headはPR本文で報告する。本番DB・S3・配信・デプロイ・main push・自動mergeは行わない。
